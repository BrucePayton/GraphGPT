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
    assert graph.ir_version == "0.4"
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


@pytest.mark.parametrize(
    "node",
    [
        "step: {}",
        "step: {use: registry:step, subgraph: {path: child.yaml}}",
    ],
)
def test_node_requires_exactly_one_action(tmp_path: Path, node: str) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(WORKFLOW.replace("step: {use: registry:step}", node), encoding="utf-8")

    with pytest.raises(GraphGPTError, match="exactly one of 'use' or 'subgraph'"):
        inspect_workflow(path)


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


def test_reports_invalid_command_and_fan_out_contracts(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(INVALID_CONTROL_WORKFLOW, encoding="utf-8")

    diagnostics = validate_workflow(path)

    assert {item.code for item in diagnostics} >= {
        "GRAPHGPT-GRAPH-004",
        "GRAPHGPT-GRAPH-013",
        "GRAPHGPT-FANOUT-002",
    }


def test_reports_retry_and_cache_policy_contracts(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        WORKFLOW.replace(
            "step: {use: registry:step}",
            "step:\n"
            "      use: registry:step\n"
            "      retry: {initialInterval: 2, maxInterval: 1}\n"
            "      cache: {ttl: 60}",
        ),
        encoding="utf-8",
    )

    diagnostics = validate_workflow(path)

    assert {item.code for item in diagnostics} >= {
        "GRAPHGPT-RETRY-001",
        "GRAPHGPT-CACHE-001",
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

INVALID_CONTROL_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: invalid_control
spec:
  state:
    fields:
      results: {type: array}
  nodes:
    command:
      use: registry:command
      destinations: [missing]
    seed: {use: registry:seed}
    worker: {use: registry:worker, writes: [results]}
  edges:
    - {from: $start, to: command}
    - {from: command, to: seed}
    - from: seed
      route:
        use: registry:fan_out
        mode: fan-out
        targets: [worker]
    - {from: worker, to: $end}
"""
