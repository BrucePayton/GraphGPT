from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from graphgpt.application.validate import locate_diagnostics, validate_ir
from graphgpt.domain.diagnostics import Diagnostic, Severity
from graphgpt.domain.ir import GraphIR


@dataclass(slots=True)
class GraphTree:
    path: Path
    graph: GraphIR
    children: dict[str, GraphTree] = field(default_factory=dict)


def load_graph_tree(
    path: Path,
    load_graph: Callable[[Path], GraphIR],
    *,
    root: Path | None = None,
    ancestors: tuple[Path, ...] = (),
    inherited_checkpointer: bool = False,
) -> tuple[GraphTree, list[Diagnostic]]:
    root = root or path.parent
    graph = load_graph(path)
    tree = GraphTree(path=path, graph=graph)
    diagnostics = validate_ir(graph)
    parent_contract = _state_contract(graph)
    checkpointer_available = inherited_checkpointer or bool(graph.runtime.checkpointer)
    for node in graph.nodes:
        if node.subgraph is None:
            continue
        node_path = f"spec.nodes.{node.id}.subgraph"
        reference = Path(node.subgraph.path)
        if reference.is_absolute():
            diagnostics.append(
                _error(
                    "SUBGRAPH-001",
                    node_path + ".path",
                    "subgraph paths must be relative to the containing workflow",
                )
            )
            continue
        child_path = (path.parent / reference).resolve()
        if not child_path.is_relative_to(root):
            diagnostics.append(
                _error(
                    "SEC-002",
                    node_path + ".path",
                    "subgraph path escapes the root workflow directory",
                )
            )
            continue
        if child_path in (*ancestors, path):
            diagnostics.append(
                _error(
                    "SUBGRAPH-002",
                    node_path + ".path",
                    f"cyclic subgraph reference to '{node.subgraph.path}'",
                )
            )
            continue
        child, child_diagnostics = load_graph_tree(
            child_path,
            load_graph,
            root=root,
            ancestors=(*ancestors, path),
            inherited_checkpointer=checkpointer_available,
        )
        diagnostics.extend(child_diagnostics)
        tree.children[node.id] = child
        diagnostics.extend(
            _validate_mapping(
                node.id,
                node.subgraph.input_map,
                node.subgraph.output_map,
                parent_contract,
                _state_contract(child.graph),
            )
        )
        if node.subgraph.persistence == "per-thread" and not checkpointer_available:
            diagnostics.append(
                _error(
                    "SUBGRAPH-006",
                    node_path + ".persistence",
                    "per-thread subgraphs require a parent runtime checkpointer",
                )
            )
    return tree, locate_diagnostics(graph, diagnostics)


def _state_contract(graph: GraphIR) -> dict[str, tuple[str, bool]]:
    fields = {item.name: (item.type, item.required) for item in graph.state_fields}
    if graph.state_type == "messages":
        fields["messages"] = ("messages", False)
    return fields


def _validate_mapping(
    node_id: str,
    input_map: dict[str, str],
    output_map: dict[str, str],
    parent_contract: dict[str, tuple[str, bool]],
    child_contract: dict[str, tuple[str, bool]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    path = f"spec.nodes.{node_id}.subgraph"
    parent_fields = set(parent_contract)
    child_fields = set(child_contract)
    mapped = bool(input_map or output_map)
    shared_fields = parent_fields.intersection(child_fields)
    if not mapped and not shared_fields:
        diagnostics.append(
            _error(
                "SUBGRAPH-003",
                path,
                "an unmapped subgraph must share at least one state field with its parent",
            )
        )
    if len(input_map.values()) != len(set(input_map.values())):
        diagnostics.append(
            _error(
                "SUBGRAPH-007",
                path + ".input",
                "multiple parent fields cannot map to the same child field",
            )
        )
    if len(output_map.values()) != len(set(output_map.values())):
        diagnostics.append(
            _error(
                "SUBGRAPH-007",
                path + ".output",
                "multiple child fields cannot map to the same parent field",
            )
        )
    for parent, child in input_map.items():
        if parent not in parent_fields:
            diagnostics.append(
                _error(
                    "SUBGRAPH-004",
                    path + ".input",
                    f"input maps unknown parent field '{parent}'",
                )
            )
        if child not in child_fields:
            diagnostics.append(
                _error(
                    "SUBGRAPH-004",
                    path + ".input",
                    f"input maps unknown child field '{child}'",
                )
            )
        if parent in parent_contract and child in child_contract and not _types_compatible(
            parent_contract[parent][0], child_contract[child][0]
        ):
            diagnostics.append(
                _error(
                    "SUBGRAPH-008",
                    path + ".input",
                    f"incompatible input types: parent '{parent}' to child '{child}'",
                )
            )
    for child, parent in output_map.items():
        if child not in child_fields:
            diagnostics.append(
                _error(
                    "SUBGRAPH-005",
                    path + ".output",
                    f"output maps unknown child field '{child}'",
                )
            )
        if parent not in parent_fields:
            diagnostics.append(
                _error(
                    "SUBGRAPH-005",
                    path + ".output",
                    f"output maps unknown parent field '{parent}'",
                )
            )
        if child in child_contract and parent in parent_contract and not _types_compatible(
            child_contract[child][0], parent_contract[parent][0]
        ):
            diagnostics.append(
                _error(
                    "SUBGRAPH-008",
                    path + ".output",
                    f"incompatible output types: child '{child}' to parent '{parent}'",
                )
            )
    available_child_inputs = set(input_map.values()) if mapped else shared_fields
    missing_required = {
        name
        for name, (_, required) in child_contract.items()
        if required and name not in available_child_inputs
    }
    if missing_required:
        diagnostics.append(
            _error(
                "SUBGRAPH-009",
                path + (".input" if mapped else ""),
                f"required child fields are not provided: {sorted(missing_required)}",
            )
        )
    return diagnostics


def _types_compatible(source: str, target: str) -> bool:
    aliases = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
    }
    source = aliases.get(source, source)
    target = aliases.get(target, target)
    return source == "any" or target == "any" or source == target


def _error(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=f"GRAPHGPT-{code}",
        severity=Severity.ERROR,
        path=path,
        message=message,
        hint="Inspect the parent and child workflow state contracts.",
    )
