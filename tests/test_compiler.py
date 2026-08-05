from pathlib import Path

from graphgpt import BindingRegistry, compile_workflow


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

