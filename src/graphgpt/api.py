from __future__ import annotations

from pathlib import Path
from typing import Any

from graphgpt.adapters.langgraph_compiler import LangGraphCompiler
from graphgpt.adapters.yaml_loader import SafeYamlWorkflowLoader
from graphgpt.application.transform import to_ir
from graphgpt.application.validate import validate_ir
from graphgpt.domain.diagnostics import GraphGPTError, Severity
from graphgpt.domain.ir import GraphIR
from graphgpt.dsl.models import WorkflowDocument
from graphgpt.registry import BindingRegistry


def load_workflow(path: str | Path) -> WorkflowDocument:
    return SafeYamlWorkflowLoader().load(Path(path))


def inspect_workflow(path: str | Path) -> GraphIR:
    return to_ir(load_workflow(path))


def validate_workflow(path: str | Path) -> list[Any]:
    return validate_ir(inspect_workflow(path))


def compile_workflow(
    path: str | Path,
    *,
    registry: BindingRegistry | None = None,
    bindings: dict[str, Any] | None = None,
) -> Any:
    workflow_path = Path(path)
    graph = inspect_workflow(workflow_path)
    diagnostics = validate_ir(graph)
    errors = [item for item in diagnostics if item.severity == Severity.ERROR]
    if errors:
        raise GraphGPTError(errors)
    resolver = registry or BindingRegistry(
        bindings,
        allowed_modules=graph.allowed_modules,
        search_path=workflow_path.resolve().parent,
    )
    return LangGraphCompiler(resolver).compile(graph)
