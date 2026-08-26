from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from graphgpt.adapters.ecosystems import builtin_ecosystem_renderer
from graphgpt.adapters.subgraph_compiler import compile_graph_tree
from graphgpt.adapters.yaml_loader import SafeYamlWorkflowLoader
from graphgpt.application.ecosystem import (
    EcosystemArtifact,
    build_invocation_contract,
)
from graphgpt.application.ports import EcosystemRenderer
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


def render_ecosystem_bundle(
    path: str | Path,
    *,
    target: str,
    base_url: str,
    auth: str = "bearer",
    options: dict[str, Any] | None = None,
    registry: BindingRegistry | None = None,
) -> tuple[EcosystemArtifact, ...]:
    """Render framework-native assets without adding framework semantics to GraphIR."""
    if auth not in {"bearer", "none"}:
        raise ValueError("auth must be bearer or none")
    diagnostics = validate_workflow(path)
    errors = [item for item in diagnostics if item.severity == Severity.ERROR]
    if errors:
        raise GraphGPTError(errors)
    graph = inspect_workflow(path)
    selected_auth = cast(Literal["bearer", "none"], auth)
    contract = build_invocation_contract(graph, base_url=base_url, auth=selected_auth)
    if target.startswith("plugin:"):
        candidate = (registry or BindingRegistry()).resolve_ecosystem(target, options)
        if not callable(getattr(candidate, "render", None)):
            raise ValueError(f"ecosystem plugin '{target}' did not return a renderer")
        renderer: EcosystemRenderer = candidate
    else:
        try:
            renderer = builtin_ecosystem_renderer(target)
        except KeyError as exc:
            raise ValueError(
                "unknown ecosystem target; use dify, n8n, or plugin:<plugin>/<adapter>"
            ) from exc
    artifacts = renderer.render(contract, MappingProxyType(dict(options or {})))
    if not artifacts:
        raise ValueError(f"ecosystem renderer '{target}' produced no artifacts")
    return artifacts


def write_ecosystem_bundle(
    artifacts: tuple[EcosystemArtifact, ...], destination: str | Path
) -> tuple[Path, ...]:
    """Write a rendered bundle while refusing to overwrite existing files."""
    root = Path(destination)
    targets = tuple(root.joinpath(*Path(artifact.path).parts) for artifact in artifacts)
    if len(set(targets)) != len(targets):
        raise ValueError("ecosystem renderer produced duplicate artifact paths")
    resolved_root = root.resolve()
    if any(not target.resolve().is_relative_to(resolved_root) for target in targets):
        raise ValueError("ecosystem artifact resolves outside the destination")
    existing = [target for target in targets if target.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing ecosystem artifact: {existing[0]}")
    for artifact, target in zip(artifacts, targets, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact.content, encoding="utf-8")
    return targets
