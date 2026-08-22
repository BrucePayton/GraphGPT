from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace

from graphgpt.application.secrets import validate_secret_config
from graphgpt.domain.diagnostics import Diagnostic, Severity, SourceLocation
from graphgpt.domain.ir import BUILTIN_REDUCERS, BUILTIN_STATE_TYPES, GraphIR

START = "$start"
END = "$end"


def validate_ir(graph: GraphIR) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    nodes = {node.id for node in graph.nodes}
    node_by_id = {node.id: node for node in graph.nodes}
    valid = nodes | {START, END}
    adjacency: dict[str, set[str]] = defaultdict(set)
    state_reducers = {field.name: field.reducer for field in graph.state_fields}
    if graph.state_type == "messages":
        state_reducers.setdefault("messages", "messages")
    command_nodes: set[str] = set()

    for node_ir in graph.nodes:
        node_path = f"spec.nodes.{node_ir.id}"
        diagnostics.extend(validate_secret_config(node_ir.config, node_path + ".with"))
        if node_ir.retry and node_ir.retry.max_interval < node_ir.retry.initial_interval:
            diagnostics.append(
                _error(
                    "RETRY-001",
                    node_path + ".retry.maxInterval",
                    "maxInterval must be greater than or equal to initialInterval",
                )
            )
        if node_ir.id in {START, END}:
            diagnostics.append(
                _error(
                    "GRAPH-010",
                    node_path,
                    f"'{node_ir.id}' is reserved for graph control flow",
                )
            )
        if len(node_ir.destinations) != len(set(node_ir.destinations)):
            diagnostics.append(
                _error(
                    "GRAPH-012",
                    node_path + ".destinations",
                    "Command destinations must be unique",
                )
            )
        for target in node_ir.destinations:
            if target not in valid or target == START:
                diagnostics.append(
                    _error(
                        "GRAPH-004",
                        node_path + ".destinations",
                        f"unknown Command destination '{target}'",
                    )
                )
            else:
                adjacency[node_ir.id].add(target)
        if node_ir.destinations:
            command_nodes.add(node_ir.id)
        if len(node_ir.writes) != len(set(node_ir.writes)):
            diagnostics.append(
                _error("STATE-003", node_path + ".writes", "declared writes must be unique")
            )
        for field_name in node_ir.writes:
            if field_name not in state_reducers:
                diagnostics.append(
                    _error(
                        "STATE-003",
                        node_path + ".writes",
                        f"write references unknown state field '{field_name}'",
                    )
                )

    for state_field in graph.state_fields:
        path = f"spec.state.fields.{state_field.name}"
        if state_field.type not in BUILTIN_STATE_TYPES:
            diagnostics.append(
                _error(
                    "STATE-001",
                    path + ".type",
                    f"unsupported state type '{state_field.type}'",
                )
            )
        if state_field.reducer and state_field.reducer not in BUILTIN_REDUCERS:
            diagnostics.append(
                _error(
                    "STATE-002",
                    path + ".reducer",
                    f"unsupported reducer '{state_field.reducer}'",
                )
            )

    for index, edge in enumerate(graph.edges):
        path = f"spec.edges[{index}]"
        if edge.source in command_nodes:
            diagnostics.append(
                _error(
                    "GRAPH-013",
                    path + ".from",
                    f"Command node '{edge.source}' cannot also declare static outgoing edges",
                )
            )
        if edge.source not in valid or edge.source == END:
            diagnostics.append(
                _error("GRAPH-004", path + ".from", f"unknown source '{edge.source}'")
            )
        targets = [edge.target] if edge.target else list(edge.route.targets if edge.route else ())
        for target in targets:
            if target not in valid or target == START:
                diagnostics.append(_error("GRAPH-004", path, f"unknown target '{target}'"))
            elif edge.source in valid:
                adjacency[edge.source].add(target)
        if edge.route:
            if len(edge.route.targets) != len(set(edge.route.targets)):
                diagnostics.append(
                    _error(
                        "GRAPH-011",
                        path + ".route.targets",
                        "conditional route targets must be unique",
                    )
                )
            invalid_mappings = set(edge.route.path_map.values()) - set(edge.route.targets)
            if invalid_mappings:
                diagnostics.append(
                    _error(
                        "GRAPH-007",
                        path + ".route.pathMap",
                        f"path map targets were not declared: {sorted(invalid_mappings)}",
                    )
                )
            if edge.kind == "fan-out":
                if edge.route.path_map:
                    diagnostics.append(
                        _error(
                            "FANOUT-003",
                            path + ".route.pathMap",
                            "fan-out routes use Send targets directly and cannot define pathMap",
                        )
                    )
                for target in edge.route.targets:
                    target_node = node_by_id.get(target)
                    if target_node is None:
                        diagnostics.append(
                            _error(
                                "FANOUT-001",
                                path + ".route.targets",
                                f"fan-out target '{target}' must be a node",
                            )
                        )
                        continue
                    if not target_node.writes:
                        diagnostics.append(
                            _error(
                                "FANOUT-001",
                                f"spec.nodes.{target}.writes",
                                "fan-out targets must declare their state writes",
                            )
                        )
                    for field_name in target_node.writes:
                        if field_name in state_reducers and not state_reducers[field_name]:
                            diagnostics.append(
                                _error(
                                    "FANOUT-002",
                                    f"spec.state.fields.{field_name}.reducer",
                                    f"fan-out write '{field_name}' requires a reducer",
                                )
                            )

    referenced_policies = set(graph.runtime.interrupt_before) | set(graph.runtime.interrupt_after)
    for node_id in sorted(referenced_policies - nodes):
        diagnostics.append(
            _error("GRAPH-009", "spec.runtime", f"runtime references unknown node '{node_id}'")
        )

    cached_nodes = [node.id for node in graph.nodes if node.cache]
    if cached_nodes and not graph.runtime.cache:
        diagnostics.append(
            _error(
                "CACHE-001",
                "spec.runtime.cache",
                f"cached nodes require a runtime cache backend: {cached_nodes}",
            )
        )

    reachable = _reachable(adjacency, START)
    for node_id in sorted(nodes - reachable):
        diagnostics.append(
            Diagnostic(
                code="GRAPH-005",
                severity=Severity.WARNING,
                path=f"spec.nodes.{node_id}",
                message=f"node '{node_id}' is unreachable from $start",
                hint="Add an incoming edge or remove the node.",
            )
        )
    if END not in reachable:
        diagnostics.append(
            _error("GRAPH-006", "spec.edges", "no reachable path terminates at $end")
        )
    return locate_diagnostics(graph, diagnostics)


def locate_diagnostics(graph: GraphIR, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Attach the nearest YAML source location without changing explicit locations."""
    return [
        item
        if item.location is not None
        else replace(item, location=_nearest_source_location(graph, item.path))
        for item in diagnostics
    ]


def _nearest_source_location(graph: GraphIR, path: str) -> SourceLocation | None:
    lookup = path if path.startswith("$") else f"$.{path}"
    current = lookup
    while current:
        if location := graph.source_map.get(current):
            return location
        current = current.rsplit(".", 1)[0] if "." in current else ""
    return graph.source_map.get("$")


def _reachable(adjacency: dict[str, set[str]], source: str) -> set[str]:
    seen: set[str] = set()
    queue = deque([source])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(adjacency[current] - seen)
    return seen


def _error(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=f"GRAPHGPT-{code}",
        severity=Severity.ERROR,
        path=path,
        message=message,
        hint="Run `graphgpt inspect` to review the normalized graph.",
    )
