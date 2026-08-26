from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from graphgpt.adapters.converters import builtin_converter, detect_format
from graphgpt.adapters.ecosystems import builtin_ecosystem_renderer
from graphgpt.adapters.subgraph_compiler import compile_graph_tree
from graphgpt.adapters.yaml_loader import SafeYamlWorkflowLoader
from graphgpt.application.ecosystem import (
    EcosystemArtifact,
    build_invocation_contract,
)
from graphgpt.application.ports import ConversionAdapter, EcosystemRenderer
from graphgpt.application.subgraphs import load_graph_tree
from graphgpt.application.transform import to_ir
from graphgpt.domain.conversion import (
    ConversionArtifact,
    ConversionResult,
    Fidelity,
)
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


def detect_asset_format(path: str | Path) -> str:
    """Detect a supported workflow/capability asset without executing its code."""
    return detect_format(Path(path))


def convert_asset(
    path: str | Path,
    *,
    target: str,
    source: str = "auto",
    options: dict[str, Any] | None = None,
    registry: BindingRegistry | None = None,
) -> ConversionResult:
    """Convert an asset through the universal IR and report semantic fidelity."""
    source_format = detect_asset_format(path) if source == "auto" else source
    adapter_options = dict(options or {})
    source_adapter = _conversion_adapter(source_format, registry, adapter_options)
    target_adapter = _conversion_adapter(target, registry, adapter_options)
    asset, import_notices = source_adapter.load(Path(path), adapter_options)
    artifacts, export_fidelity, export_notices = target_adapter.render(asset, adapter_options)
    notices = (*import_notices, *export_notices)
    fidelity = _worst_fidelity(export_fidelity, *(notice.fidelity for notice in notices))
    preliminary = ConversionResult(source_format, target, fidelity, artifacts, notices)
    report = ConversionArtifact(
        "conversion-report.json",
        json.dumps(preliminary.report(), indent=2, sort_keys=True) + "\n",
        "application/json",
    )
    return ConversionResult(source_format, target, fidelity, (*artifacts, report), notices)


def write_conversion_result(result: ConversionResult, destination: str | Path) -> tuple[Path, ...]:
    """Write converted files using the same safe, no-overwrite policy as ecosystem bundles."""
    ecosystem_artifacts = tuple(
        EcosystemArtifact(item.path, item.content, item.media_type) for item in result.artifacts
    )
    return write_ecosystem_bundle(ecosystem_artifacts, destination)


def _conversion_adapter(
    format_name: str,
    registry: BindingRegistry | None,
    options: dict[str, Any],
) -> ConversionAdapter:
    if format_name.startswith("plugin:"):
        candidate = (registry or BindingRegistry()).resolve_converter(format_name, options)
        if not callable(getattr(candidate, "load", None)) or not callable(
            getattr(candidate, "render", None)
        ):
            raise ValueError(f"converter plugin '{format_name}' did not return an adapter")
        return cast(ConversionAdapter, candidate)
    return builtin_converter(format_name)


def _worst_fidelity(first: Fidelity, *rest: Fidelity) -> Fidelity:
    order = {
        Fidelity.EXACT: 0,
        Fidelity.ADAPTED: 1,
        Fidelity.LOSSY: 2,
        Fidelity.UNSUPPORTED: 3,
    }
    return max((first, *rest), key=order.__getitem__)
