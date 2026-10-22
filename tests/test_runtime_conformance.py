from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from graphgpt import BindingRegistry, compile_workflow


class ValueState(TypedDict, total=False):
    value: int
    values: Annotated[list[str], operator.add]
    request: str
    result: str
    left: str
    right: str


def test_conformance_first_execution(tmp_path: Path) -> None:
    def increment(state: ValueState) -> dict[str, int]:
        return {"value": state["value"] + 1}

    generated = _compile(tmp_path, LINEAR, {"increment": increment})
    builder = StateGraph(ValueState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    native = builder.compile()

    assert generated.invoke({"value": 1})["value"] == native.invoke({"value": 1})["value"]


def test_conformance_parallel_state_merge(tmp_path: Path) -> None:
    def left(_: ValueState) -> dict[str, list[str]]:
        return {"values": ["left"]}

    def right(_: ValueState) -> dict[str, list[str]]:
        return {"values": ["right"]}

    generated = _compile(tmp_path, PARALLEL, {"left": left, "right": right})
    builder = StateGraph(ValueState)
    builder.add_node("left", left)
    builder.add_node("right", right)
    builder.add_edge(START, "left")
    builder.add_edge(START, "right")
    builder.add_edge("left", END)
    builder.add_edge("right", END)
    native = builder.compile()

    expected = native.invoke({"values": []})
    assert generated.invoke({"values": []}) == expected
    assert expected["values"] == ["left", "right"]


def test_conformance_interrupt_resume(tmp_path: Path) -> None:
    generated_review = _review_node([])
    native_calls: list[str] = []
    native_review = _review_node(native_calls)
    generated = _compile(tmp_path, INTERRUPT, {"review": generated_review})
    builder = StateGraph(ValueState)
    builder.add_node("review", native_review)
    builder.add_edge(START, "review")
    builder.add_edge("review", END)
    native = builder.compile(checkpointer=InMemorySaver())

    generated_config = {"configurable": {"thread_id": "generated-interrupt"}}
    native_config = {"configurable": {"thread_id": "native-interrupt"}}
    generated_paused = generated.invoke({"request": "deploy"}, config=generated_config)
    native_paused = native.invoke({"request": "deploy"}, config=native_config)
    assert generated_paused["__interrupt__"][0].value == native_paused["__interrupt__"][0].value
    assert generated.invoke(Command(resume="approved"), config=generated_config)["result"] == (
        native.invoke(Command(resume="approved"), config=native_config)["result"]
    )
    assert native_calls == ["approved"]


def test_conformance_parallel_resume_by_interrupt_id(tmp_path: Path) -> None:
    generated = _compile(
        tmp_path,
        PARALLEL_INTERRUPT,
        {"left": _approval_node("left"), "right": _approval_node("right")},
    )
    builder = StateGraph(ValueState)
    builder.add_node("left", _approval_node("left"))
    builder.add_node("right", _approval_node("right"))
    builder.add_edge(START, "left")
    builder.add_edge(START, "right")
    builder.add_edge("left", END)
    builder.add_edge("right", END)
    native = builder.compile(checkpointer=InMemorySaver())

    generated_result = _resume_all(generated, "generated-parallel")
    native_result = _resume_all(native, "native-parallel")
    assert {generated_result["left"], generated_result["right"]} == {
        "approved-left",
        "approved-right",
    }
    assert generated_result["left"] == native_result["left"]
    assert generated_result["right"] == native_result["right"]


def test_conformance_subgraph_resume(tmp_path: Path) -> None:
    child = tmp_path / "child.yaml"
    child.write_text(INTERRUPT, encoding="utf-8")
    parent = tmp_path / "parent.yaml"
    parent.write_text(SUBGRAPH_PARENT, encoding="utf-8")
    generated = compile_workflow(
        parent,
        registry=BindingRegistry({"review": _review_node([])}, discover_plugins=False),
    )

    child_builder = StateGraph(ValueState)
    child_builder.add_node("review", _review_node([]))
    child_builder.add_edge(START, "review")
    child_builder.add_edge("review", END)
    native_child = child_builder.compile(checkpointer=True)
    parent_builder = StateGraph(ValueState)
    parent_builder.add_node("child", native_child)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", END)
    native = parent_builder.compile(checkpointer=InMemorySaver())

    generated_result = _pause_and_resume(generated, "generated-subgraph")
    native_result = _pause_and_resume(native, "native-subgraph")
    assert generated_result["result"] == native_result["result"] == "approved"


def test_conformance_history_branch(tmp_path: Path) -> None:
    def first(state: ValueState) -> dict[str, int]:
        return {"value": state["value"] + 1}

    def second(state: ValueState) -> dict[str, int]:
        return {"value": state["value"] * 2}

    generated = _compile(tmp_path, HISTORY, {"first": first, "second": second})
    builder = StateGraph(ValueState)
    builder.add_node("first", first)
    builder.add_node("second", second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    native = builder.compile(checkpointer=InMemorySaver())

    assert _branch_from_history(generated, "generated-history") == _branch_from_history(
        native, "native-history"
    )


def _compile(tmp_path: Path, workflow: str, bindings: dict[str, Any]) -> Any:
    path = tmp_path / f"workflow-{len(list(tmp_path.iterdir()))}.yaml"
    path.write_text(workflow, encoding="utf-8")
    return compile_workflow(
        path,
        registry=BindingRegistry(bindings, discover_plugins=False),
    )


def _review_node(calls: list[str]) -> Any:
    def review(state: ValueState) -> dict[str, str]:
        decision = str(interrupt({"request": state["request"]}))
        calls.append(decision)
        return {"result": decision}

    return review


def _approval_node(side: str) -> Any:
    def approve(_: ValueState) -> dict[str, str]:
        decision = str(interrupt({"side": side}))
        return {side: f"{decision}-{side}"}

    return approve


def _resume_all(graph: Any, thread_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    paused = graph.invoke({}, config=config)
    answers = {item.id: "approved" for item in paused["__interrupt__"]}
    return graph.invoke(Command(resume=answers), config=config)


def _pause_and_resume(graph: Any, thread_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke({"request": "deploy"}, config=config)
    return graph.invoke(Command(resume="approved"), config=config)


def _branch_from_history(graph: Any, thread_id: str) -> int:
    config = {"configurable": {"thread_id": thread_id}}
    assert graph.invoke({"value": 1}, config=config)["value"] == 4
    snapshot = next(item for item in graph.get_state_history(config) if item.next == ("second",))
    branch_config = graph.update_state(snapshot.config, {"value": 10}, as_node="first")
    return graph.invoke(None, config=branch_config)["value"]


LINEAR = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: linear}
spec:
  state:
    fields: {value: {type: integer, required: true}}
  nodes: {increment: {use: registry:increment, writes: [value]}}
  edges:
    - {from: $start, to: increment}
    - {from: increment, to: $end}
"""

PARALLEL = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: parallel_merge}
spec:
  state:
    fields: {values: {type: array, reducer: add}}
  nodes:
    left: {use: registry:left, writes: [values]}
    right: {use: registry:right, writes: [values]}
  edges:
    - {from: $start, to: left}
    - {from: $start, to: right}
    - {from: left, to: $end}
    - {from: right, to: $end}
"""

INTERRUPT = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: interrupt_resume}
spec:
  state:
    fields:
      request: {type: string, required: true}
      result: {type: string}
  nodes: {review: {use: registry:review, writes: [result]}}
  edges:
    - {from: $start, to: review}
    - {from: review, to: $end}
  runtime: {checkpointer: memory}
"""

PARALLEL_INTERRUPT = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: parallel_resume}
spec:
  state:
    fields:
      left: {type: string}
      right: {type: string}
  nodes:
    left: {use: registry:left, writes: [left]}
    right: {use: registry:right, writes: [right]}
  edges:
    - {from: $start, to: left}
    - {from: $start, to: right}
    - {from: left, to: $end}
    - {from: right, to: $end}
  runtime: {checkpointer: memory}
"""

SUBGRAPH_PARENT = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: subgraph_resume}
spec:
  state:
    fields:
      request: {type: string, required: true}
      result: {type: string}
  nodes:
    child:
      subgraph:
        path: child.yaml
        persistence: per-thread
  edges:
    - {from: $start, to: child}
    - {from: child, to: $end}
  runtime: {checkpointer: memory}
"""

HISTORY = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: history_branch}
spec:
  state:
    fields: {value: {type: integer, required: true}}
  nodes:
    first: {use: registry:first, writes: [value]}
    second: {use: registry:second, writes: [value]}
  edges:
    - {from: $start, to: first}
    - {from: first, to: second}
    - {from: second, to: $end}
  runtime: {checkpointer: memory}
"""
