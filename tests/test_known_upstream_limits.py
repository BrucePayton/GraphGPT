from __future__ import annotations

import operator
from importlib.metadata import version
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


class ValuesState(TypedDict, total=False):
    values: Annotated[list[str], operator.add]
    result: str


LANGGRAPH_1_2_16_OR_OLDER = tuple(map(int, version("langgraph").split(".")[:3])) <= (1, 2, 16)


@pytest.mark.xfail(
    LANGGRAPH_1_2_16_OR_OLDER,
    reason="upstream langgraph#9344 duplicates Command(update=...) on a new thread",
    strict=False,
)
def test_upstream_new_thread_command_update_is_applied_once() -> None:
    def step(_: ValuesState) -> Command:
        return Command(update={"values": ["node"]}, goto=END)

    builder = StateGraph(ValuesState)
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    graph = builder.compile(checkpointer=InMemorySaver())

    result = graph.invoke(
        Command(update={"values": ["input"]}),
        config={"configurable": {"thread_id": "upstream-9344"}},
    )
    assert result["values"] == ["input", "node"]


@pytest.mark.xfail(
    LANGGRAPH_1_2_16_OR_OLDER,
    reason="upstream langgraph#9346 may repeat checkpointer=True subgraphs after a breakpoint",
    strict=False,
)
def test_upstream_persistent_subgraph_is_not_repeated_after_static_breakpoint() -> None:
    calls: list[str] = []

    def child_step(_: ValuesState) -> dict[str, str]:
        calls.append("child")
        return {"result": "child-complete"}

    child_builder = StateGraph(ValuesState)
    child_builder.add_node("child_step", child_step)
    child_builder.add_edge(START, "child_step")
    child_builder.add_edge("child_step", END)
    child = child_builder.compile(checkpointer=True)

    parent_builder = StateGraph(ValuesState)
    parent_builder.add_node("child", child)
    parent_builder.add_node("finish", lambda state: state)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", "finish")
    parent_builder.add_edge("finish", END)
    parent = parent_builder.compile(
        checkpointer=InMemorySaver(),
        interrupt_before=["finish"],
    )
    config = {"configurable": {"thread_id": "upstream-9346"}}

    parent.invoke({}, config=config)
    parent.invoke(None, config=config)
    assert calls == ["child"]
