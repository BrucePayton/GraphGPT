from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Annotated, TypedDict

import pytest
import yaml
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from graphgpt import BindingRegistry, compile_workflow


class State(TypedDict):
    values: Annotated[list[str], operator.add]


def fail(_):
    raise ValueError("recoverable")


def recover(_):
    return {"values": ["recovered"]}


def ok(_):
    return {"values": ["ok"]}


def workflow(nodes, edges, *, reducer="add", frequency=100):
    return {
        "apiVersion": "graphgpt.dev/v1alpha1",
        "kind": "Workflow",
        "metadata": {"name": "recovery"},
        "spec": {
            "state": {"fields": {"values": {"type": "array", "reducer": reducer}}},
            "nodes": nodes,
            "edges": [{"from": a, "to": b} for a, b in edges],
            "runtime": {"checkpointer": "memory", "deltaSnapshotFrequency": frequency},
        },
    }


@pytest.mark.parametrize("mode", ["values", "updates", "tasks"])
@pytest.mark.parametrize("nested", [False, True])
def test_parallel_and_subgraph_recovery_matches_native(tmp_path: Path, mode, nested) -> None:
    nodes = {
        "bad": {"use": "registry:fail", "errorHandler": "registry:recover"},
        "good": {"use": "registry:ok"},
    }
    edges = [("$start", "bad"), ("$start", "good"), ("bad", "$end"), ("good", "$end")]
    doc = workflow(nodes, edges)
    native_builder = StateGraph(State)
    native_builder.add_node("bad", fail, error_handler=recover)
    native_builder.add_node("good", ok)
    for a, b in edges:
        native_builder.add_edge({"$start": START}.get(a, a), {"$end": END}.get(b, b))
    if nested:
        (tmp_path / "child.yaml").write_text(yaml.safe_dump(doc))
        doc = workflow(
            {"child": {"subgraph": {"path": "child.yaml"}}},
            [("$start", "child"), ("child", "$end")],
        )
        parent = StateGraph(State)
        parent.add_node("child", native_builder.compile())
        parent.add_edge(START, "child")
        parent.add_edge("child", END)
        native_builder = parent
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(doc))
    generated = compile_workflow(
        path, registry=BindingRegistry({"fail": fail, "recover": recover, "ok": ok})
    )
    native = native_builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "recovery"}}
    streams = [
        list(graph.stream({"values": []}, config, stream_mode=mode))
        for graph in (generated, native)
    ]
    assert sorted(generated.get_state(config).values["values"]) == ["ok", "recovered"]
    assert generated.get_state(config).values == native.get_state(config).values
    if mode == "tasks":
        # IDs and timestamps differ; compare externally visible task outcomes.
        def normalize(events):
            return [(e["name"], bool(e.get("error"))) for e in events]

        assert sorted(normalize(streams[0])) == sorted(normalize(streams[1]))
        if not nested:
            assert any(e.get("error") for e in streams[0])
    elif mode == "updates":
        # Parallel nodes finish in either order; compare all updates including duplicates.
        assert sorted(json.dumps(e, sort_keys=True) for e in streams[0]) == sorted(
            json.dumps(e, sort_keys=True) for e in streams[1]
        )
    else:
        assert streams[0] == streams[1]


@pytest.mark.parametrize("frequency", [2, 100])
def test_long_thread_delta_replay_and_branch_isolation(tmp_path: Path, frequency: int) -> None:
    doc = workflow(
        {"step": {"use": "registry:step"}},
        [("$start", "step"), ("step", "$end")],
        reducer="delta-add",
        frequency=frequency,
    )
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(doc))

    def step(_):
        return {"values": ["x"]}

    generated = compile_workflow(path, registry=BindingRegistry({"step": step}))

    def fold(current, updates):
        return list(current or []) + [item for update in updates for item in update]

    class DeltaState(TypedDict):
        values: Annotated[list[str], DeltaChannel(fold, snapshot_frequency=frequency)]

    # Local annotations must contain the actual channel instance, not a forward reference.
    DeltaState.__annotations__["values"] = Annotated[
        list[str], DeltaChannel(fold, snapshot_frequency=frequency)
    ]
    builder = StateGraph(DeltaState)
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    native = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "long"}}
    old = []
    for graph in (generated, native):
        for i in range(105):
            graph.invoke({"values": []}, config)
            if i == 2:
                old.append(graph.get_state(config).config)
        assert graph.get_state(config).values["values"] == ["x"] * 105
    for graph, checkpoint in zip((generated, native), old, strict=True):
        assert graph.get_state(checkpoint).values["values"] == ["x"] * 3
        branch = graph.update_state(checkpoint, {"values": ["branch"]})
        assert graph.get_state(branch).values["values"] == ["x"] * 3 + ["branch"]
        assert graph.get_state(checkpoint).values["values"] == ["x"] * 3
