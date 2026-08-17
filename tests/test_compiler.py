from pathlib import Path

from langgraph.types import Command, Send

from graphgpt import BindingRegistry, compile_workflow, validate_workflow


def test_compiles_and_invokes_native_langgraph(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(WORKFLOW, encoding="utf-8")
    registry = BindingRegistry(
        {
            "increment": lambda state: {"count": state["count"] + 1},
            "route": lambda state: "$end" if state["count"] == 3 else "increment",
        }
    )
    graph = compile_workflow(path, registry=registry)
    assert graph.invoke({"count": 0})["count"] == 3
    assert "increment" in graph.get_graph().nodes


def test_compiles_native_command_with_declared_destinations(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(COMMAND_WORKFLOW, encoding="utf-8")

    def decide(state: dict[str, object]) -> Command:
        target = "accept" if state["approved"] else "reject"
        return Command(goto=target)

    registry = BindingRegistry(
        {
            "decide": decide,
            "accept": lambda _: {"result": "accepted"},
            "reject": lambda _: {"result": "rejected"},
        },
        discover_plugins=False,
    )

    assert validate_workflow(path) == []
    graph = compile_workflow(path, registry=registry)
    assert graph.invoke({"approved": True})["result"] == "accepted"
    assert graph.invoke({"approved": False})["result"] == "rejected"


def test_compiles_send_fan_out_with_aggregate_reducer(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(FAN_OUT_WORKFLOW, encoding="utf-8")
    registry = BindingRegistry(
        {
            "seed": lambda _: {"items": [1, 2, 3]},
            "fan_out": lambda state: [
                Send("worker", {"item": item}) for item in state["items"]
            ],
            "worker": lambda state: {"results": [state["item"] * 2]},
        },
        discover_plugins=False,
    )

    assert validate_workflow(path) == []
    graph = compile_workflow(path, registry=registry)
    assert graph.invoke({"items": [], "results": []})["results"] == [2, 4, 6]


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: counter
spec:
  state:
    fields:
      count: {type: integer, required: true}
  nodes:
    increment: {use: registry:increment}
  edges:
    - {from: $start, to: increment}
    - from: increment
      route:
        use: registry:route
        targets: [increment, $end]
"""

COMMAND_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: command_branch
spec:
  state:
    fields:
      approved: {type: boolean, required: true}
      result: {type: string}
  nodes:
    decide:
      use: registry:decide
      destinations: [accept, reject]
    accept: {use: registry:accept, writes: [result]}
    reject: {use: registry:reject, writes: [result]}
  edges:
    - {from: $start, to: decide}
    - {from: accept, to: $end}
    - {from: reject, to: $end}
"""

FAN_OUT_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: fan_out
spec:
  state:
    fields:
      items: {type: array}
      results: {type: array, reducer: add}
  nodes:
    seed: {use: registry:seed, writes: [items]}
    worker: {use: registry:worker, writes: [results]}
  edges:
    - {from: $start, to: seed}
    - from: seed
      route:
        use: registry:fan_out
        mode: fan-out
        targets: [worker]
    - {from: worker, to: $end}
"""
