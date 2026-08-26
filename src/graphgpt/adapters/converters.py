from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml  # type: ignore[import-untyped]

from graphgpt.adapters.ecosystems import DifyRenderer, N8nRenderer
from graphgpt.adapters.yaml_loader import SafeYamlWorkflowLoader
from graphgpt.application.ecosystem import InvocationContract
from graphgpt.application.transform import to_ir
from graphgpt.application.validate import locate_diagnostics, validate_ir
from graphgpt.domain.conversion import (
    UNIVERSAL_IR_VERSION,
    ConversionArtifact,
    ConversionNotice,
    Fidelity,
    UniversalAsset,
    UniversalEdge,
    UniversalNode,
)
from graphgpt.domain.diagnostics import GraphGPTError, Severity
from graphgpt.domain.ir import StateFieldIR

CONVERSION_FORMATS = (
    "universal",
    "graphgpt",
    "mcp",
    "skill",
    "langgraph",
    "dify",
    "n8n",
)


class BuiltinConverter:
    def __init__(self, format_name: str) -> None:
        if format_name not in CONVERSION_FORMATS:
            raise ValueError(f"unsupported conversion format: {format_name}")
        self.format = format_name

    def load(
        self, path: Path, options: dict[str, Any]
    ) -> tuple[UniversalAsset, tuple[ConversionNotice, ...]]:
        del options
        return load_asset(path, self.format)

    def render(
        self, asset: UniversalAsset, options: dict[str, Any]
    ) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
        return render_asset(asset, self.format, options)


def builtin_converter(format_name: str) -> BuiltinConverter:
    return BuiltinConverter(format_name)


def detect_format(path: Path) -> str:
    candidate = path / "SKILL.md" if path.is_dir() else path
    if candidate.name == "SKILL.md" and candidate.is_file():
        return "skill"
    if path.is_dir():
        raise ValueError(f"directory does not contain SKILL.md: {path}")
    text = candidate.read_text(encoding="utf-8")
    if candidate.suffix.lower() == ".json":
        document = _json_object(text)
        if document.get("api_version") == UNIVERSAL_IR_VERSION:
            return "universal"
        if any(key in document for key in ("tools", "prompts", "resources")):
            return "mcp"
        if isinstance(document.get("result"), dict) and any(
            key in document["result"] for key in ("tools", "prompts", "resources")
        ):
            return "mcp"
        if isinstance(document.get("nodes"), list) and isinstance(
            document.get("connections"), dict
        ):
            return "n8n"
        if isinstance(document.get("nodes"), list) and isinstance(document.get("edges"), list):
            return "langgraph"
    document = yaml.safe_load(text)
    if isinstance(document, dict):
        if str(document.get("apiVersion", "")).startswith("graphgpt.dev/"):
            return "graphgpt"
        if document.get("kind") == "app" and isinstance(document.get("workflow"), dict):
            return "dify"
    raise ValueError(f"unable to detect conversion format for {path}")


def load_asset(
    path: Path, source_format: str
) -> tuple[UniversalAsset, tuple[ConversionNotice, ...]]:
    if source_format == "graphgpt":
        return _load_graphgpt(path), ()
    if source_format == "universal":
        return _load_universal(path), ()
    if source_format == "mcp":
        return _load_mcp(path), ()
    if source_format == "skill":
        asset = _load_skill(path)
        skipped = _mapping(asset.extensions.get("skill")).get("skipped_files", [])
        notices = (
            (
                _notice(
                    "CONVERT-103",
                    Fidelity.LOSSY,
                    f"Skipped {len(skipped)} binary, symlinked, or oversized Skill files.",
                    hint="Copy skipped files manually; paths remain in extensions.skill.",
                ),
            )
            if skipped
            else ()
        )
        return asset, notices
    if source_format == "langgraph":
        return _load_langgraph(path), (
            _notice(
                "CONVERT-101",
                Fidelity.LOSSY,
                "LangGraph graph JSON describes topology but not executable node callables "
                "or state reducers.",
                hint="Provide bindings when exporting to an executable target.",
            ),
        )
    if source_format == "dify":
        return _load_dify(path), (
            _notice(
                "CONVERT-102",
                Fidelity.ADAPTED,
                "Dify-specific node payloads are preserved under extensions.dify.",
            ),
        )
    if source_format == "n8n":
        return _load_n8n(path), (
            _notice(
                "CONVERT-104",
                Fidelity.ADAPTED,
                "n8n node parameters and connections are preserved under extensions.n8n.",
            ),
        )
    raise ValueError(f"unsupported source format: {source_format}")


def render_asset(
    asset: UniversalAsset,
    target_format: str,
    options: dict[str, Any],
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if target_format == "universal":
        artifact = ConversionArtifact(
            f"{asset.name}.universal.json",
            json.dumps(asset.to_dict(), indent=2, sort_keys=True) + "\n",
            "application/json",
        )
        return (artifact,), Fidelity.EXACT, ()
    if target_format == "graphgpt":
        return _render_graphgpt(asset)
    if target_format == "mcp":
        return _render_mcp(asset, options)
    if target_format == "skill":
        return _render_skill(asset)
    if target_format == "langgraph":
        return _render_langgraph(asset)
    if target_format == "dify":
        return _render_dify(asset, options)
    if target_format == "n8n":
        return _render_n8n(asset, options)
    raise ValueError(f"unsupported target format: {target_format}")


def _load_graphgpt(path: Path) -> UniversalAsset:
    graph = to_ir(SafeYamlWorkflowLoader().load(path))
    diagnostics = locate_diagnostics(graph, validate_ir(graph))
    errors = [item for item in diagnostics if item.severity == Severity.ERROR]
    if errors:
        raise GraphGPTError(errors)
    schema = _graph_state_schema(graph.state_fields)
    nodes = tuple(
        UniversalNode(
            id=node.id,
            kind="action",
            name=node.id,
            binding=node.use or (f"subgraph:{node.subgraph.path}" if node.subgraph else None),
            config=node.config,
            metadata={
                **node.metadata,
                "writes": list(node.writes),
                "destinations": list(node.destinations),
            },
        )
        for node in graph.nodes
    )
    edges: list[UniversalEdge] = []
    for edge in graph.edges:
        if edge.target:
            edges.append(UniversalEdge(edge.source, edge.target, metadata={"kind": edge.kind}))
        elif edge.route:
            for target in edge.route.targets:
                edges.append(
                    UniversalEdge(
                        edge.source,
                        target,
                        condition=edge.route.use,
                        metadata={"path_map": edge.route.path_map, "kind": edge.kind},
                    )
                )
    return UniversalAsset(
        name=graph.name,
        description=f"GraphGPT workflow {graph.name}",
        kind="workflow",
        source_format="graphgpt",
        inputs=schema,
        outputs=schema,
        nodes=nodes,
        edges=tuple(edges),
        capabilities=frozenset({"state", "control-flow", "execution"}),
        extensions={"graphgpt": graph.to_dict()},
    )


def _load_universal(path: Path) -> UniversalAsset:
    data = _json_object(path.read_text(encoding="utf-8"))
    if data.get("api_version") != UNIVERSAL_IR_VERSION:
        raise ValueError("unsupported universal IR version")
    return UniversalAsset(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        kind=data.get("kind", "workflow"),
        source_format=str(data.get("source_format", "universal")),
        inputs=_mapping(data.get("inputs")),
        outputs=_mapping(data.get("outputs")),
        instructions=data.get("instructions"),
        nodes=tuple(
            UniversalNode(
                id=str(item["id"]),
                kind=item.get("kind", "action"),
                name=str(item.get("name", item["id"])),
                binding=item.get("binding"),
                config=_mapping(item.get("config")),
                metadata=_mapping(item.get("metadata")),
            )
            for item in _list_of_mappings(data.get("nodes"))
        ),
        edges=tuple(
            UniversalEdge(
                source=str(item["source"]),
                target=str(item["target"]),
                condition=item.get("condition"),
                metadata=_mapping(item.get("metadata")),
            )
            for item in _list_of_mappings(data.get("edges"))
        ),
        capabilities=frozenset(map(str, data.get("capabilities", []))),
        extensions=_mapping(data.get("extensions")),
    )


def _load_mcp(path: Path) -> UniversalAsset:
    document = _json_object(path.read_text(encoding="utf-8"))
    payload = document.get("result", document)
    if not isinstance(payload, dict):
        raise ValueError("MCP snapshot result must be an object")
    tools = _list_of_mappings(payload.get("tools"))
    prompts = _list_of_mappings(payload.get("prompts"))
    resources = _list_of_mappings(payload.get("resources"))
    nodes = [
        UniversalNode(
            id=_safe_id(str(item.get("name", "tool"))),
            kind="tool",
            name=str(item.get("name", "tool")),
            binding=f"mcp:tool/{item.get('name', 'tool')}",
            config={"inputSchema": _mapping(item.get("inputSchema"))},
            metadata={
                key: value for key, value in item.items() if key not in {"name", "inputSchema"}
            },
        )
        for item in tools
    ]
    nodes.extend(
        UniversalNode(
            id=_safe_id(f"prompt-{item.get('name', 'prompt')}"),
            kind="prompt",
            name=str(item.get("name", "prompt")),
            metadata=dict(item),
        )
        for item in prompts
    )
    nodes.extend(
        UniversalNode(
            id=_safe_id(f"resource-{item.get('uri', 'resource')}"),
            kind="resource",
            name=str(item.get("name", item.get("uri", "resource"))),
            metadata=dict(item),
        )
        for item in resources
    )
    return UniversalAsset(
        name=str(document.get("name", "mcp-capabilities")),
        description=str(document.get("description", "Imported MCP capability snapshot")),
        kind="toolset",
        source_format="mcp",
        nodes=tuple(nodes),
        capabilities=frozenset(
            key
            for key, values in (("tools", tools), ("prompts", prompts), ("resources", resources))
            if values
        ),
        extensions={"mcp": document},
    )


def _load_skill(path: Path) -> UniversalAsset:
    skill_path = path / "SKILL.md" if path.is_dir() else path
    text = skill_path.read_text(encoding="utf-8")
    frontmatter, body = _skill_parts(text)
    name = str(frontmatter.get("name", skill_path.parent.name))
    files: dict[str, str] = {}
    skipped_files: list[str] = []
    if path.is_dir():
        total_size = 0
        for bundled in sorted(item for item in path.rglob("*") if item.name != "SKILL.md"):
            relative = bundled.relative_to(path).as_posix()
            if bundled.is_symlink() or not bundled.is_file():
                if bundled.is_symlink():
                    skipped_files.append(relative)
                continue
            size = bundled.stat().st_size
            if size > 1_000_000 or total_size + size > 5_000_000:
                skipped_files.append(relative)
                continue
            try:
                files[relative] = bundled.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                skipped_files.append(relative)
            else:
                total_size += size
    return UniversalAsset(
        name=name,
        description=str(frontmatter.get("description", "")),
        kind="skill",
        source_format="skill",
        instructions=body,
        nodes=(UniversalNode("instructions", "instruction", "Instructions"),),
        capabilities=frozenset({"instructions"}),
        extensions={
            "skill": {
                "frontmatter": frontmatter,
                "files": files,
                "skipped_files": skipped_files,
            }
        },
    )


def _load_langgraph(path: Path) -> UniversalAsset:
    document = _json_object(path.read_text(encoding="utf-8"))
    raw_nodes = _list_of_mappings(document.get("nodes"))
    raw_edges = _list_of_mappings(document.get("edges"))
    nodes = tuple(
        UniversalNode(
            id=str(item["id"]),
            kind=_boundary_kind(str(item["id"])),
            name=str(_mapping(item.get("data")).get("name", item["id"])),
            metadata=dict(item),
        )
        for item in raw_nodes
    )
    return UniversalAsset(
        name=str(document.get("name", path.stem)),
        description="Imported LangGraph topology",
        kind="workflow",
        source_format="langgraph",
        nodes=nodes,
        edges=tuple(
            UniversalEdge(
                str(item["source"]),
                str(item["target"]),
                condition=str(item["conditional"]) if item.get("conditional") else None,
                metadata=dict(item),
            )
            for item in raw_edges
        ),
        capabilities=frozenset({"control-flow"}),
        extensions={"langgraph": document},
    )


def _load_dify(path: Path) -> UniversalAsset:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Dify DSL must be a mapping")
    app = _mapping(document.get("app"))
    workflow = _mapping(document.get("workflow"))
    graph = _mapping(workflow.get("graph"))
    nodes = tuple(
        UniversalNode(
            id=str(item["id"]),
            kind=_dify_kind(str(_mapping(item.get("data")).get("type", "action"))),
            name=str(_mapping(item.get("data")).get("title", item["id"])),
            binding=f"dify:{_mapping(item.get('data')).get('type', 'unknown')}",
            config=_mapping(item.get("data")),
            metadata={key: value for key, value in item.items() if key != "data"},
        )
        for item in _list_of_mappings(graph.get("nodes"))
    )
    return UniversalAsset(
        name=str(app.get("name", path.stem)),
        description=str(app.get("description", "")),
        kind="workflow",
        source_format="dify",
        nodes=nodes,
        edges=tuple(
            UniversalEdge(str(item["source"]), str(item["target"]), metadata=dict(item))
            for item in _list_of_mappings(graph.get("edges"))
        ),
        capabilities=frozenset({"control-flow", "execution"}),
        extensions={"dify": document},
    )


def _load_n8n(path: Path) -> UniversalAsset:
    document = _json_object(path.read_text(encoding="utf-8"))
    raw_nodes = _list_of_mappings(document.get("nodes"))
    name_to_id = {
        str(item.get("name", item.get("id", "node"))): str(
            item.get("id", _safe_id(str(item.get("name", "node"))))
        )
        for item in raw_nodes
    }
    nodes = tuple(
        UniversalNode(
            id=str(item.get("id", _safe_id(str(item.get("name", "node"))))),
            kind=("start" if "trigger" in str(item.get("type", "")).lower() else "action"),
            name=str(item.get("name", item.get("id", "node"))),
            binding=f"n8n:{item.get('type', 'unknown')}",
            config=_mapping(item.get("parameters")),
            metadata={key: value for key, value in item.items() if key != "parameters"},
        )
        for item in raw_nodes
    )
    edges: list[UniversalEdge] = []
    connections = _mapping(document.get("connections"))
    for source, channels in connections.items():
        for output_lists in _mapping(channels).values():
            if not isinstance(output_lists, list):
                continue
            for output_items in output_lists:
                for item in _list_of_mappings(output_items):
                    edges.append(
                        UniversalEdge(
                            name_to_id.get(str(source), str(source)),
                            name_to_id.get(str(item.get("node", "")), str(item.get("node", ""))),
                            metadata=dict(item),
                        )
                    )
    return UniversalAsset(
        name=str(document.get("name", path.stem)),
        description=str(document.get("description", "Imported n8n workflow")),
        kind="workflow",
        source_format="n8n",
        nodes=nodes,
        edges=tuple(edges),
        capabilities=frozenset({"control-flow", "execution"}),
        extensions={"n8n": document},
    )


def _render_graphgpt(
    asset: UniversalAsset,
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    graph = asset.extensions.get("graphgpt") if asset.source_format == "graphgpt" else None
    if isinstance(graph, dict):
        document = _graph_ir_to_dsl(graph)
        fidelity = Fidelity.EXACT
        notices: tuple[ConversionNotice, ...] = ()
    else:
        document = _universal_to_graphgpt(asset)
        fidelity = Fidelity.LOSSY if asset.kind == "toolset" else Fidelity.ADAPTED
        notices = (
            _notice(
                "CONVERT-201",
                fidelity,
                "Non-GraphGPT actions use registry placeholders; unordered toolsets are "
                "serialized into a deterministic sequence.",
                hint="Register each generated registry:<node-id> binding before compilation.",
            ),
        )
    return (
        (
            ConversionArtifact(
                f"{asset.name}.workflow.yaml",
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                "application/yaml",
            ),
        ),
        fidelity,
        notices,
    )


def _render_mcp(
    asset: UniversalAsset, options: dict[str, Any]
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if asset.source_format == "mcp" and isinstance(asset.extensions.get("mcp"), dict):
        document = asset.extensions["mcp"]
        fidelity = Fidelity.EXACT
        notices: tuple[ConversionNotice, ...] = ()
    else:
        endpoint = _endpoint(asset, options)
        document = {
            "name": asset.name,
            "description": asset.description,
            "tools": [
                {
                    "name": asset.name,
                    "description": asset.description or f"Invoke {asset.name}",
                    "inputSchema": asset.inputs,
                    "outputSchema": asset.outputs,
                    "annotations": {
                        "graphgpt": {"endpoint": endpoint, "sourceFormat": asset.source_format}
                    },
                }
            ],
        }
        fidelity = Fidelity.ADAPTED
        notices = (
            _notice(
                "CONVERT-202",
                fidelity,
                "The workflow is exposed as one MCP tool; an MCP server transport must "
                "dispatch it to the endpoint.",
            ),
        )
    return (
        (
            ConversionArtifact(
                f"{asset.name}.mcp.json",
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                "application/json",
            ),
        ),
        fidelity,
        notices,
    )


def _render_skill(
    asset: UniversalAsset,
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if asset.source_format == "skill" and isinstance(asset.extensions.get("skill"), dict):
        skill_extension = _mapping(asset.extensions["skill"])
        frontmatter = _mapping(skill_extension.get("frontmatter"))
        body = asset.instructions or ""
        bundled_files = {
            str(path): str(content)
            for path, content in _mapping(skill_extension.get("files")).items()
        }
        fidelity = Fidelity.EXACT
        notices: tuple[ConversionNotice, ...] = ()
    else:
        skill_name = _skill_name(asset.name)
        frontmatter = {
            "name": skill_name,
            "description": (asset.description or f"Execute the {asset.name} workflow")[:1024],
            "metadata": {"source-format": asset.source_format, "graphgpt-fidelity": "adapted"},
        }
        lines = ["# Workflow", "", "Follow these steps in dependency order:", ""]
        for node in asset.nodes:
            if node.kind not in {"start", "end"}:
                binding = f" using `{node.binding}`" if node.binding else ""
                lines.append(f"- Run **{node.name}**{binding}.")
        if asset.edges:
            lines.extend(["", "## Transitions", ""])
            for edge in asset.edges:
                condition = f" when `{edge.condition}`" if edge.condition else ""
                lines.append(f"- `{edge.source}` → `{edge.target}`{condition}")
        body = "\n".join(lines) + "\n"
        bundled_files = {}
        fidelity = Fidelity.LOSSY if asset.edges else Fidelity.ADAPTED
        notices = (
            _notice(
                "CONVERT-203",
                fidelity,
                "Executable state and routing become human/model-readable instructions "
                "in Agent Skills.",
            ),
        )
    rendered = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body
    )
    artifacts = [ConversionArtifact("SKILL.md", rendered, "text/markdown")]
    artifacts.extend(
        ConversionArtifact(path, content) for path, content in sorted(bundled_files.items())
    )
    return tuple(artifacts), fidelity, notices


def _render_langgraph(
    asset: UniversalAsset,
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if asset.source_format == "langgraph" and isinstance(asset.extensions.get("langgraph"), dict):
        document = asset.extensions["langgraph"]
        fidelity = Fidelity.EXACT
        notices: tuple[ConversionNotice, ...] = ()
    else:
        node_ids = {_langgraph_boundary(node.id) for node in asset.nodes}
        nodes = [
            {
                "id": _langgraph_boundary(node.id),
                **(
                    {}
                    if node.kind == "end"
                    else {
                        "type": "runnable",
                        "data": {"name": node.name, "graphgpt_binding": node.binding},
                    }
                ),
            }
            for node in asset.nodes
        ]
        for boundary in ("__start__", "__end__"):
            if boundary not in node_ids and any(
                boundary
                in {
                    _langgraph_boundary(edge.source),
                    _langgraph_boundary(edge.target),
                }
                for edge in asset.edges
            ):
                nodes.append({"id": boundary})
        document = {
            "name": asset.name,
            "nodes": nodes,
            "edges": [
                {
                    "source": _langgraph_boundary(edge.source),
                    "target": _langgraph_boundary(edge.target),
                    **(
                        {"conditional": True, "condition": edge.condition} if edge.condition else {}
                    ),
                }
                for edge in asset.edges
            ],
        }
        fidelity = Fidelity.ADAPTED
        notices = (
            _notice(
                "CONVERT-204",
                fidelity,
                "LangGraph graph JSON preserves topology; executable callables remain "
                "external bindings.",
            ),
        )
    return (
        (
            ConversionArtifact(
                f"{asset.name}.langgraph.json",
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                "application/json",
            ),
        ),
        fidelity,
        notices,
    )


def _render_dify(
    asset: UniversalAsset, options: dict[str, Any]
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if asset.source_format == "dify" and isinstance(asset.extensions.get("dify"), dict):
        return (
            (
                ConversionArtifact(
                    f"{asset.name}.dify.yaml",
                    yaml.safe_dump(asset.extensions["dify"], sort_keys=False, allow_unicode=True),
                    "application/yaml",
                ),
            ),
            Fidelity.EXACT,
            (),
        )
    artifacts = _ecosystem_artifacts(DifyRenderer(), asset, options)
    return (
        artifacts,
        Fidelity.ADAPTED,
        (
            _notice(
                "CONVERT-205",
                Fidelity.ADAPTED,
                "The asset is exposed as a Dify Custom Tool so its original runtime retains "
                "execution semantics.",
            ),
        ),
    )


def _render_n8n(
    asset: UniversalAsset, options: dict[str, Any]
) -> tuple[tuple[ConversionArtifact, ...], Fidelity, tuple[ConversionNotice, ...]]:
    if asset.source_format == "n8n" and isinstance(asset.extensions.get("n8n"), dict):
        return (
            (
                ConversionArtifact(
                    f"{asset.name}.n8n.json",
                    json.dumps(asset.extensions["n8n"], indent=2, sort_keys=True) + "\n",
                    "application/json",
                ),
            ),
            Fidelity.EXACT,
            (),
        )
    return (
        _ecosystem_artifacts(N8nRenderer(), asset, options),
        Fidelity.ADAPTED,
        (
            _notice(
                "CONVERT-206",
                Fidelity.ADAPTED,
                "The asset is exposed as a callable n8n sub-workflow backed by its "
                "original runtime endpoint.",
            ),
        ),
    )


def _ecosystem_artifacts(
    renderer: DifyRenderer | N8nRenderer,
    asset: UniversalAsset,
    options: dict[str, Any],
) -> tuple[ConversionArtifact, ...]:
    contract = InvocationContract(
        name=asset.name,
        description=asset.description or f"Invoke {asset.name}",
        endpoint=_endpoint(asset, options),
        input_schema=asset.inputs,
        output_schema=asset.outputs,
    )
    return tuple(
        ConversionArtifact(item.path, item.content, item.media_type)
        for item in renderer.render(contract, MappingProxyType(options))
    )


def _universal_to_graphgpt(asset: UniversalAsset) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    properties = _mapping(asset.inputs.get("properties"))
    required = set(asset.inputs.get("required", []))
    for name, schema_value in properties.items():
        schema = _mapping(schema_value)
        fields[str(name)] = {
            "type": str(schema.get("type", "any")),
            **({"required": True} if name in required else {}),
            **({"default": schema["default"]} if "default" in schema else {}),
        }
    node_documents: dict[str, Any] = {}
    for node in asset.nodes:
        if node.kind in {"start", "end"}:
            continue
        node_documents[node.id] = {
            "use": node.binding
            if node.binding and _graphgpt_binding(node.binding)
            else f"registry:{node.id}",
            **({"with": node.config} if node.config else {}),
            **({"metadata": node.metadata} if node.metadata else {}),
        }
    edge_documents = [
        {"from": _graphgpt_boundary(edge.source), "to": _graphgpt_boundary(edge.target)}
        for edge in asset.edges
    ]
    if not edge_documents and node_documents:
        identifiers = list(node_documents)
        edge_documents = [{"from": "$start", "to": identifiers[0]}]
        edge_documents.extend(
            {"from": source, "to": target} for source, target in pairwise(identifiers)
        )
        edge_documents.append({"from": identifiers[-1], "to": "$end"})
    return {
        "apiVersion": "graphgpt.dev/v1alpha1",
        "kind": "Workflow",
        "metadata": {"name": _safe_id(asset.name)},
        "spec": {
            "state": {"fields": fields},
            "nodes": node_documents,
            "edges": edge_documents,
        },
    }


def _graph_ir_to_dsl(graph: dict[str, Any]) -> dict[str, Any]:
    fields = {
        item["name"]: {
            "type": item.get("type", "any"),
            **({"required": True} if item.get("required") else {}),
            **({"reducer": item["reducer"]} if item.get("reducer") else {}),
            **({"default": item["default"]} if item.get("default") is not None else {}),
        }
        for item in graph.get("state_fields", [])
    }
    nodes: dict[str, Any] = {}
    for node in graph.get("nodes", []):
        body: dict[str, Any] = {}
        if node.get("use"):
            body["use"] = node["use"]
        elif node.get("subgraph"):
            body["subgraph"] = node["subgraph"]
        if node.get("config"):
            body["with"] = node["config"]
        if node.get("metadata"):
            body["metadata"] = node["metadata"]
        if node.get("destinations"):
            body["destinations"] = node["destinations"]
        if node.get("writes"):
            body["writes"] = node["writes"]
        if node.get("retry"):
            body["retry"] = node["retry"]
        if node.get("cache"):
            body["cache"] = node["cache"]
        nodes[node["id"]] = body
    edges: list[dict[str, Any]] = []
    for edge in graph.get("edges", []):
        body = {"from": edge["source"]}
        if edge.get("target"):
            body["to"] = edge["target"]
        else:
            route = dict(edge["route"])
            route["mode"] = edge.get("kind", "conditional")
            body["route"] = route
        edges.append(body)
    runtime = graph.get("runtime", {})
    return {
        "apiVersion": graph.get("api_version", "graphgpt.dev/v1alpha1"),
        "kind": "Workflow",
        "metadata": {"name": graph["name"], **graph.get("metadata", {})},
        "spec": {
            "state": {"type": graph.get("state_type", "dict"), "fields": fields},
            "nodes": nodes,
            "edges": edges,
            "runtime": {
                "interruptBefore": runtime.get("interrupt_before", []),
                "interruptAfter": runtime.get("interrupt_after", []),
                **(
                    {"checkpointer": runtime["checkpointer"]} if runtime.get("checkpointer") else {}
                ),
                **({"store": runtime["store"]} if runtime.get("store") else {}),
                **({"cache": runtime["cache"]} if runtime.get("cache") else {}),
            },
            "security": {"allowedModules": graph.get("allowed_modules", [])},
        },
    }


def _graph_state_schema(fields: tuple[StateFieldIR, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        properties[field.name] = {"type": _json_type(field.type)}
        if field.default is not None:
            properties[field.name]["default"] = field.default
        if field.required:
            required.append(field.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_type(value: str) -> str:
    return {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "messages": "array",
        "any": "object",
    }.get(value, value)


def _skill_parts(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    marker = text.find("\n---", 4)
    if marker < 0:
        raise ValueError("SKILL.md frontmatter is not closed")
    frontmatter = yaml.safe_load(text[4:marker])
    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return frontmatter, text[marker + 4 :].strip() + "\n"


def _endpoint(asset: UniversalAsset, options: dict[str, Any]) -> str:
    base_url = str(options.get("base_url", "https://graphgpt.example.com")).rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an absolute HTTP(S) URL without query or fragment")
    return f"{base_url}/workflows/{asset.name}/invoke"


def _json_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON conversion input must be an object")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("_") or "asset"


def _skill_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]", "-", value.lower().replace("_", "-"))
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return (normalized or "graphgpt-workflow")[:64].rstrip("-")


def _boundary_kind(node_id: str) -> Literal["start", "end", "action"]:
    if node_id in {"__start__", "$start", "start"}:
        return "start"
    if node_id in {"__end__", "$end", "end"}:
        return "end"
    return "action"


def _dify_kind(kind: str) -> Literal["start", "end", "action", "tool"]:
    if kind == "start":
        return "start"
    if kind in {"end", "answer"}:
        return "end"
    if kind == "tool":
        return "tool"
    return "action"


def _graphgpt_boundary(node_id: str) -> str:
    if node_id in {"__start__", "start"}:
        return "$start"
    if node_id in {"__end__", "end"}:
        return "$end"
    return node_id


def _langgraph_boundary(node_id: str) -> str:
    if node_id in {"$start", "start"}:
        return "__start__"
    if node_id in {"$end", "end"}:
        return "__end__"
    return node_id


def _graphgpt_binding(binding: str) -> bool:
    return binding.startswith(("python:", "registry:", "plugin:", "langchain:", "langgraph:"))


def _notice(
    code: str,
    fidelity: Fidelity,
    message: str,
    *,
    hint: str | None = None,
) -> ConversionNotice:
    return ConversionNotice(code, fidelity, message, hint=hint)
