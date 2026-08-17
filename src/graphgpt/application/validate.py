from __future__ import annotations

from collections import defaultdict, deque

from graphgpt.domain.diagnostics import Diagnostic, Severity
from graphgpt.domain.ir import BUILTIN_REDUCERS, BUILTIN_STATE_TYPES, GraphIR

START = "$start"
END = "$end"


def validate_ir(graph: GraphIR) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    nodes = {node.id for node in graph.nodes}
    valid = nodes | {START, END}
    adjacency: dict[str, set[str]] = defaultdict(set)

    for node_ir in graph.nodes:
        if node_ir.id in {START, END}:
            diagnostics.append(
                _error(
                    "GRAPH-010",
                    f"spec.nodes.{node_ir.id}",
                    f"'{node_ir.id}' is reserved for graph control flow",
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

    referenced_policies = set(graph.runtime.interrupt_before) | set(graph.runtime.interrupt_after)
    for node_id in sorted(referenced_policies - nodes):
        diagnostics.append(
            _error("GRAPH-009", "spec.runtime", f"runtime references unknown node '{node_id}'")
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
    return diagnostics


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
