import asyncio
from pathlib import Path

from graphgpt import BindingRegistry, compile_workflow, validate_workflow


def test_compiles_shared_state_subgraph_as_native_node(tmp_path: Path) -> None:
    root = tmp_path / "root.yaml"
    child = tmp_path / "child.yaml"
    root.write_text(ROOT_SHARED, encoding="utf-8")
    child.write_text(CHILD_SHARED, encoding="utf-8")
    graph = compile_workflow(
        root,
        registry=BindingRegistry(
            {"increment": lambda state: {"value": state["value"] + 1}},
            discover_plugins=False,
        ),
    )

    assert graph.invoke({"value": 1})["value"] == 2
    assert "child" in graph.get_graph().nodes


def test_maps_parent_and_child_state_for_sync_and_async_invocation(tmp_path: Path) -> None:
    root = tmp_path / "root.yaml"
    child = tmp_path / "child.yaml"
    root.write_text(ROOT_MAPPED, encoding="utf-8")
    child.write_text(CHILD_MAPPED, encoding="utf-8")

    async def transform(state: dict[str, str]) -> dict[str, str]:
        return {"answer": state["question"].upper()}

    graph = compile_workflow(
        root,
        registry=BindingRegistry({"transform": transform}, discover_plugins=False),
    )

    assert asyncio.run(graph.ainvoke({"request": "hello"}))["response"] == "HELLO"


def test_per_thread_subgraph_accumulates_child_state(tmp_path: Path) -> None:
    root = tmp_path / "root.yaml"
    child = tmp_path / "child.yaml"
    root.write_text(ROOT_PER_THREAD, encoding="utf-8")
    child.write_text(CHILD_PER_THREAD, encoding="utf-8")

    def count(state: dict[str, object]) -> dict[str, int]:
        return {"count": len(state["items"])}  # type: ignore[arg-type]

    graph = compile_workflow(
        root,
        registry=BindingRegistry({"count": count}, discover_plugins=False),
    )
    config = {"configurable": {"thread_id": "subgraph-thread"}}

    assert graph.invoke({"batch": ["a"]}, config=config)["result"] == 1
    assert graph.invoke({"batch": ["b"]}, config=config)["result"] == 2


def test_validates_mapping_persistence_cycles_and_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "root.yaml"
    child = tmp_path / "child.yaml"
    root.write_text(ROOT_INVALID, encoding="utf-8")
    child.write_text(CHILD_CYCLE, encoding="utf-8")

    diagnostics = validate_workflow(root)
    codes = {item.code for item in diagnostics}

    assert codes >= {
        "GRAPHGPT-SUBGRAPH-002",
        "GRAPHGPT-SUBGRAPH-004",
        "GRAPHGPT-SUBGRAPH-005",
        "GRAPHGPT-SUBGRAPH-006",
        "GRAPHGPT-SUBGRAPH-007",
        "GRAPHGPT-SUBGRAPH-008",
        "GRAPHGPT-SUBGRAPH-009",
        "GRAPHGPT-SEC-002",
    }
    cycle = next(item for item in diagnostics if item.code == "GRAPHGPT-SUBGRAPH-002")
    mapping = next(item for item in diagnostics if item.code == "GRAPHGPT-SUBGRAPH-004")
    assert cycle.location is not None
    assert cycle.location.file == str(child)
    assert mapping.location is not None
    assert mapping.location.file == str(root)


ROOT_SHARED = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: root_shared}
spec:
  state:
    fields:
      value: {type: integer, required: true}
  nodes:
    child:
      subgraph: {path: child.yaml}
  edges:
    - {from: $start, to: child}
    - {from: child, to: $end}
"""

CHILD_SHARED = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: child_shared}
spec:
  state:
    fields:
      value: {type: integer, required: true}
  nodes:
    increment: {use: registry:increment}
  edges:
    - {from: $start, to: increment}
    - {from: increment, to: $end}
"""

ROOT_MAPPED = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: root_mapped}
spec:
  state:
    fields:
      request: {type: string, required: true}
      response: {type: string}
  nodes:
    child:
      subgraph:
        path: child.yaml
        input: {request: question}
        output: {answer: response}
  edges:
    - {from: $start, to: child}
    - {from: child, to: $end}
"""

CHILD_MAPPED = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: child_mapped}
spec:
  state:
    fields:
      question: {type: string, required: true}
      answer: {type: string}
  nodes:
    transform: {use: registry:transform}
  edges:
    - {from: $start, to: transform}
    - {from: transform, to: $end}
"""

ROOT_PER_THREAD = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: root_per_thread}
spec:
  state:
    fields:
      batch: {type: array}
      result: {type: integer}
  nodes:
    child:
      subgraph:
        path: child.yaml
        input: {batch: items}
        output: {count: result}
        persistence: per-thread
  edges:
    - {from: $start, to: child}
    - {from: child, to: $end}
  runtime:
    checkpointer: memory
"""

CHILD_PER_THREAD = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: child_per_thread}
spec:
  state:
    fields:
      items: {type: array, reducer: add}
      count: {type: integer}
  nodes:
    count: {use: registry:count}
  edges:
    - {from: $start, to: count}
    - {from: count, to: $end}
"""

ROOT_INVALID = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: root_invalid}
spec:
  state:
    fields:
      request: {type: string}
      response: {type: string}
  nodes:
    cycle:
      subgraph:
        path: child.yaml
        input: {request: child_value, response: child_value, missing_parent: missing_child}
        output: {child_value: response, missing_child: missing_parent}
        persistence: per-thread
    escape:
      subgraph: {path: ../outside.yaml}
  edges:
    - {from: $start, to: cycle}
    - {from: cycle, to: escape}
    - {from: escape, to: $end}
"""

CHILD_CYCLE = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: child_cycle}
spec:
  state:
    fields:
      child_value: {type: integer}
      required_extra: {type: boolean, required: true}
  nodes:
    root:
      subgraph: {path: root.yaml}
  edges:
    - {from: $start, to: root}
    - {from: root, to: $end}
"""
