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


def test_reports_missing_workflow_as_structured_diagnostic(tmp_path: Path) -> None:
    with pytest.raises(GraphGPTError) as raised:
        inspect_workflow(tmp_path / "missing.yaml")

    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "GRAPHGPT-IO-001"
    assert "missing.yaml" in diagnostic.message


def test_reports_unsupported_state_semantics_before_compilation(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        WORKFLOW.replace(
            "result: {type: string}",
            "result: {type: sting, reducer: concatenate}",
        ),
        encoding="utf-8",
    )

    diagnostics = validate_workflow(path)

    assert {item.code for item in diagnostics} >= {
        "GRAPHGPT-STATE-001",
        "GRAPHGPT-STATE-002",
    }


def test_reports_reserved_node_names_and_duplicate_route_targets(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        WORKFLOW.replace(
            "step: {use: registry:step}",
            "$end: {use: registry:step}\n    step: {use: registry:step}",
        ).replace(
            "- {from: step, to: $end}",
            "- from: step\n"
            "      route:\n"
            "        use: registry:route\n"
            "        targets: [$end, $end]",
        ),
        encoding="utf-8",
    )

    diagnostics = validate_workflow(path)

    assert {item.code for item in diagnostics} >= {
        "GRAPHGPT-GRAPH-010",
        "GRAPHGPT-GRAPH-011",
    }


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
