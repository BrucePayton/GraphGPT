from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig

from graphgpt import (
    BindingRegistry,
    StateInput,
    compile_workflow,
    graph_version,
    inspect_workflow,
    invoke_workflow,
    trace_metadata,
)


def test_graph_version_is_stable_for_semantics_and_changes_with_content(tmp_path: Path) -> None:
    first = _write(tmp_path / "first.yaml", WORKFLOW)
    second = _write(tmp_path / "nested/second.yaml", WORKFLOW)
    changed = _write(tmp_path / "changed.yaml", WORKFLOW.replace("trace_test", "trace_changed"))

    assert graph_version(inspect_workflow(first)) == graph_version(inspect_workflow(second))
    assert graph_version(inspect_workflow(first)) != graph_version(inspect_workflow(changed))


def test_compiler_attaches_reserved_identity_to_every_node(tmp_path: Path) -> None:
    path = _write(tmp_path / "workflow.yaml", WORKFLOW)
    graph_ir = inspect_workflow(path)
    graph = compile_workflow(
        path,
        registry=BindingRegistry({"step": lambda state: state}, discover_plugins=False),
    )
    metadata = graph.get_graph().nodes["step"].metadata

    assert metadata == {
        **trace_metadata(graph_ir),
        "node_id": "step",
    }


def test_invoke_workflow_injects_trace_metadata_and_preserves_user_metadata(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "workflow.yaml", WORKFLOW)

    def step(_: dict[str, object], config: RunnableConfig) -> dict[str, object]:
        return {"result": config["metadata"]}

    result = invoke_workflow(
        path,
        StateInput({}),
        registry=BindingRegistry({"step": step}, discover_plugins=False),
        config={"metadata": {"tenant": "acme", "graph_id": "forged"}},
    )
    metadata = result["result"]
    assert metadata["tenant"] == "acme"
    assert metadata["graph_id"] == "trace_test"
    assert metadata["node_id"] == "step"
    assert metadata["generator_version"] == "0.10.0"
    assert metadata["graph_version"].startswith("sha256:")


def test_invoke_workflow_rejects_non_object_metadata(tmp_path: Path) -> None:
    path = _write(tmp_path / "workflow.yaml", WORKFLOW)
    with pytest.raises(ValueError, match=r"config.metadata must be a JSON object"):
        invoke_workflow(
            path,
            StateInput({}),
            registry=BindingRegistry({"step": lambda state: state}, discover_plugins=False),
            config={"metadata": "bad"},  # type: ignore[dict-item]
        )


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: trace_test}
spec:
  state:
    fields:
      result: {type: object}
  nodes:
    step:
      use: registry:step
      writes: [result]
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""
