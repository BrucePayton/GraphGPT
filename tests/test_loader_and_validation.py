from pathlib import Path

import pytest

from graphgpt import inspect_workflow, validate_workflow
from graphgpt.domain.diagnostics import GraphGPTError, Severity


def test_loads_normalized_ir(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(WORKFLOW, encoding="utf-8")
    graph = inspect_workflow(path)
    assert graph.name == "test_graph"
    assert [node.id for node in graph.nodes] == ["step"]
    assert graph.ir_version == "0.1"
    assert validate_workflow(path) == []


def test_reports_unknown_edge_before_importing_code(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(WORKFLOW.replace("to: step", "to: missing"), encoding="utf-8")
    diagnostics = validate_workflow(path)
    assert any(item.code == "GRAPHGPT-GRAPH-004" for item in diagnostics)
    assert any(item.severity == Severity.WARNING for item in diagnostics)


def test_rejects_unknown_schema_fields_with_location(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(WORKFLOW.replace("nodes:", "unexpected: true\n  nodes:"), encoding="utf-8")
    with pytest.raises(GraphGPTError) as raised:
        inspect_workflow(path)
    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "GRAPHGPT-SCHEMA-001"
    assert diagnostic.location is not None


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: test_graph
spec:
  state:
    fields:
      result: {type: string}
  nodes:
    step: {use: registry:step}
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""

