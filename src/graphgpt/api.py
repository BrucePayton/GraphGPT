from __future__ import annotations

from pathlib import Path
from typing import Any

from graphgpt.adapters.subgraph_compiler import compile_graph_tree
from graphgpt.adapters.yaml_loader import SafeYamlWorkflowLoader
from graphgpt.application.subgraphs import load_graph_tree
from graphgpt.application.transform import to_ir
from graphgpt.domain.diagnostics import Diagnostic, GraphGPTError, Severity
from graphgpt.domain.ir import GraphIR
from graphgpt.dsl.models import WorkflowDocument
from graphgpt.registry import BindingRegistry


def load_workflow(path: str | Path) -> WorkflowDocument:
    return SafeYamlWorkflowLoader().load(Path(path))


def inspect_workflow(path: str | Path) -> GraphIR:
    return to_ir(load_workflow(path))


def validate_workflow(path: str | Path) -> list[Diagnostic]:
    _, diagnostics = load_graph_tree(Path(path).resolve(), inspect_workflow)
    return diagnostics


def compile_workflow(
    path: str | Path,
    *,
    registry: BindingRegistry | None = None,
    bindings: dict[str, Any] | None = None,
) -> Any:
    workflow_path = Path(path).resolve()
    tree, diagnostics = load_graph_tree(workflow_path, inspect_workflow)
    errors = [item for item in diagnostics if item.severity == Severity.ERROR]
    if errors:
        raise GraphGPTError(errors)
    return compile_graph_tree(tree, registry=registry, bindings=bindings)
