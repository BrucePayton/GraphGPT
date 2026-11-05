from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graphgpt import AsyncTaskIR, AsyncTaskRunner, LangfuseEvaluationAdapter, evaluation_manifest
from graphgpt.application.transform import to_ir
from graphgpt.domain.ir import DecisionIR, EdgeIR, GraphIR, NodeIR
from graphgpt.dsl.models import WorkflowDocument
from graphgpt.tracing import trace_metadata


def test_task_lifecycle_idempotency_and_resources() -> None:
    async def run():
        runner = AsyncTaskRunner()
        event = asyncio.Event()

        async def work(payload, config):
            await event.wait()
            return {"payload": payload, "parent": config["metadata"]["parent_thread_id"]}

        graph = SimpleNamespace(ainvoke=work)
        spec = AsyncTaskIR("a", "parent", "child", resources=("sandbox",))
        assert runner.start(spec, graph, {"x": 1}).status == "running"
        assert runner.start(spec, graph, {"x": 1}).status == "running"
        with pytest.raises(ValueError, match="idempotency"):
            runner.start(spec, graph, {"x": 2})
        with pytest.raises(ValueError, match="owned"):
            runner.start(AsyncTaskIR("b", "parent", "child2", resources=("sandbox",)), graph, {})
        event.set()
        result = await runner.result("parent", "a")
        assert result.status == "completed" and result.output["parent"] == "parent"
        result.output["payload"]["x"] = 9
        assert runner.status("parent", "a").output["payload"]["x"] == 1
        assert (await runner.cancel("parent", "a")).status == "completed"
        with pytest.raises(ValueError, match="only interrupted"):
            runner.resume("parent", "a", "ok")
        with pytest.raises(ValueError, match="associated"):
            runner.start(AsyncTaskIR("c", "parent", "child"), graph, {})

    asyncio.run(run())


@pytest.mark.parametrize("started", [False, True])
def test_cancel_releases_resource(started) -> None:
    async def run():
        event = asyncio.Event()

        async def work(payload, config):
            event.set()
            await asyncio.Event().wait()

        graph = SimpleNamespace(ainvoke=work)
        runner = AsyncTaskRunner()
        runner.start(AsyncTaskIR("a", "p", "c", resources=("disk",)), graph, {})
        if started:
            await event.wait()
        assert (await runner.cancel("p", "a")).status == "cancelled"
        runner.start(AsyncTaskIR("b", "p", "d", resources=("disk",)), graph, {})
        await runner.cancel("p", "b")

    asyncio.run(run())


def test_timeout_and_interrupt_resume() -> None:
    async def run():
        runner = AsyncTaskRunner()

        async def wait(payload, config):
            await asyncio.Event().wait()

        runner.start(
            AsyncTaskIR("slow", "p", "s", timeout_seconds=0.01), SimpleNamespace(ainvoke=wait), {}
        )
        result = await runner.result("p", "slow")
        assert result.status == "failed" and result.error == "TimeoutError"
        builder = StateGraph(dict)
        builder.add_node("review", lambda state: {"answer": interrupt("approve?")})
        builder.add_edge(START, "review")
        builder.add_edge("review", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        runner.start(AsyncTaskIR("review", "p", "r"), graph, {})
        assert (await runner.result("p", "review")).status == "interrupted"
        runner.resume("p", "review", "yes")
        result = await runner.result("p", "review")
        assert result.status == "completed" and result.output == {"answer": "yes"}

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"task_id": ""},
        {"thread_id": "p"},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"resources": ("a", "a")},
    ],
)
def test_invalid_task_spec(kwargs) -> None:
    with pytest.raises(ValueError):
        AsyncTaskIR(**{"task_id": "a", "parent_thread_id": "p", "thread_id": "c", **kwargs})


def test_evaluation_stream_and_unknown_checks() -> None:
    graph = GraphIR(
        "test",
        "graphgpt.dev/v1alpha1",
        "dict",
        (),
        (NodeIR("decide", decision=DecisionIR("p", {"type": "predicate"}, "answer", "interrupt")),),
        (EdgeIR("$start", "decide"), EdgeIR("decide", "$end")),
    )
    manifest = evaluation_manifest(graph)
    assert manifest == evaluation_manifest(graph)
    assert manifest["compiler_version"]
    calls = []

    def get_many(**kwargs):
        calls.append(kwargs)
        if kwargs["cursor"] is None:
            return SimpleNamespace(data=[], meta=SimpleNamespace(cursor="next-page"))
        observations = []
        for answer in (True, "bad"):
            observations.append(
                SimpleNamespace(
                    id=str(answer),
                    trace_id="trace-1",
                    name="decide",
                    metadata=json.dumps(trace_metadata(graph, node_id="decide")),
                    level="DEFAULT",
                    end_time="now",
                    output=json.dumps({"answer": answer}),
                )
            )
        observations.append(SimpleNamespace(metadata={"graph_id": "different"}))
        observations.append(
            SimpleNamespace(name="provider", metadata=trace_metadata(graph, node_id="decide"))
        )
        return SimpleNamespace(data=observations, meta=SimpleNamespace(cursor=None))

    adapter = LangfuseEvaluationAdapter(
        SimpleNamespace(api=SimpleNamespace(observations=SimpleNamespace(get_many=get_many)))
    )
    time_range = {
        "from_start_time": datetime(2026, 11, 1, tzinfo=UTC),
        "to_start_time": datetime(2026, 11, 5, tzinfo=UTC),
    }
    rows = list(adapter.evaluate(graph, **time_range, node_id="decide"))
    assert len(rows) == 8
    assert [r["status"] for r in rows if r["check"] == "typed_decision"] == ["passed", "failed"]
    assert {r["status"] for r in rows if r["check"] == "rejection_has_no_side_effects"} == {
        "not_evaluated"
    }
    assert "graph_version" in calls[0]["filter"] and calls[0]["limit"] == 100
    assert calls[1]["cursor"] == "next-page"
    assert rows[0]["trace_id"] == "trace-1"
    assert rows[0]["observation_id"] == rows[0]["run_id"]
    rows = list(
        adapter.evaluate(
            graph, **time_range, evaluators={"rejection_has_no_side_effects": lambda _: False}
        )
    )
    assert all(
        r["status"] == "failed" for r in rows if r["check"] == "rejection_has_no_side_effects"
    )
    with pytest.raises(ValueError):
        list(adapter.evaluate(graph, **time_range, node_id="missing"))
    with pytest.raises(ValueError):
        list(adapter.evaluate(graph, **time_range, limit=0))


def test_new_ir_roundtrip() -> None:
    from graphgpt.adapters.converters import _graph_ir_to_dsl

    doc = WorkflowDocument.model_validate(
        {
            "apiVersion": "graphgpt.dev/v1alpha1",
            "kind": "Workflow",
            "metadata": {"name": "roundtrip"},
            "spec": {
                "state": {"fields": {"a": {"type": "boolean"}}},
                "nodes": {
                    "x": {
                        "decision": {
                            "provider": "registry:p",
                            "question": {"type": "predicate", "prompt": "go?"},
                            "outputKey": "a",
                        },
                        "errorHandler": "registry:recover",
                    }
                },
                "edges": [{"from": "$start", "to": "x"}, {"from": "x", "to": "$end"}],
            },
        }
    )
    ir = to_ir(doc)
    assert to_ir(WorkflowDocument.model_validate(_graph_ir_to_dsl(ir.to_dict()))) == ir
