from pathlib import Path

from langgraph.types import Command, Send, interrupt

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


def test_dynamic_interrupt_resumes_once_with_same_thread(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(INTERRUPT_WORKFLOW, encoding="utf-8")
    decisions: list[bool] = []

    def review(state: dict[str, object]) -> Command:
        decision = bool(interrupt({"request": state["request"]}))
        decisions.append(decision)
        return Command(goto="accept" if decision else "reject")

    registry = BindingRegistry(
        {
            "review": review,
            "accept": lambda _: {"result": "accepted"},
            "reject": lambda _: {"result": "rejected"},
        },
        discover_plugins=False,
    )
    graph = compile_workflow(path, registry=registry)
    config = {"configurable": {"thread_id": "approval-1"}}

    interrupted = graph.invoke({"request": "deploy"}, config=config)
    assert interrupted["__interrupt__"][0].value == {"request": "deploy"}
    assert decisions == []

    resumed = graph.invoke(Command(resume=True), config=config)
    assert resumed["result"] == "accepted"
    assert decisions == [True]


def test_static_interrupt_before_resumes_with_none_input(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(STATIC_INTERRUPT_WORKFLOW, encoding="utf-8")
    calls: list[str] = []

    def step(_: dict[str, object]) -> dict[str, str]:
        calls.append("step")
        return {"result": "done"}

    graph = compile_workflow(
        path,
        registry=BindingRegistry({"step": step}, discover_plugins=False),
    )
    config = {"configurable": {"thread_id": "static-1"}}

    graph.invoke({}, config=config)
    assert calls == []

    resumed = graph.invoke(None, config=config)
    assert resumed["result"] == "done"
    assert calls == ["step"]


def test_node_retry_policy_retries_transient_failure(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(RETRY_WORKFLOW, encoding="utf-8")
    calls: list[int] = []

    def unstable(state: dict[str, int]) -> dict[str, int]:
        calls.append(state["value"])
        if len(calls) < 3:
            raise ConnectionError("temporary")
        return {"value": state["value"] + 1}

    graph = compile_workflow(
        path,
        registry=BindingRegistry({"unstable": unstable}, discover_plugins=False),
    )

    assert graph.invoke({"value": 1})["value"] == 2
    assert calls == [1, 1, 1]


def test_node_cache_policy_reuses_result_for_same_input(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(CACHE_WORKFLOW, encoding="utf-8")
    calls: list[int] = []

    def expensive(state: dict[str, int]) -> dict[str, int]:
        calls.append(state["value"])
        return {"result": state["value"] * 2}

    graph = compile_workflow(
        path,
        registry=BindingRegistry({"expensive": expensive}, discover_plugins=False),
    )

    assert graph.invoke({"value": 3})["result"] == 6
    assert graph.invoke({"value": 3})["result"] == 6
    assert calls == [3]


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

INTERRUPT_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: interrupt_review
spec:
  state:
    fields:
      request: {type: string, required: true}
      result: {type: string}
  nodes:
    review:
      use: registry:review
      destinations: [accept, reject]
    accept: {use: registry:accept, writes: [result]}
    reject: {use: registry:reject, writes: [result]}
  edges:
    - {from: $start, to: review}
    - {from: accept, to: $end}
    - {from: reject, to: $end}
  runtime:
    checkpointer: memory
"""

STATIC_INTERRUPT_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: static_interrupt
spec:
  state:
    fields:
      result: {type: string}
  nodes:
    step: {use: registry:step, writes: [result]}
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
  runtime:
    interruptBefore: [step]
    checkpointer: memory
"""

RETRY_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: retry_policy
spec:
  state:
    fields:
      value: {type: integer, required: true}
  nodes:
    unstable:
      use: registry:unstable
      retry:
        initialInterval: 0.001
        backoffFactor: 1
        maxInterval: 0.001
        maxAttempts: 3
        jitter: false
  edges:
    - {from: $start, to: unstable}
    - {from: unstable, to: $end}
"""

CACHE_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: cache_policy
spec:
  state:
    fields:
      value: {type: integer, required: true}
      result: {type: integer}
  nodes:
    expensive:
      use: registry:expensive
      cache: {ttl: 60}
  edges:
    - {from: $start, to: expensive}
    - {from: expensive, to: $end}
  runtime:
    cache: memory
"""
