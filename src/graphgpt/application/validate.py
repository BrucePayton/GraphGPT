from __future__ import annotations

from collections import defaultdict, deque

from graphgpt.domain.diagnostics import Diagnostic, Severity
from graphgpt.domain.ir import GraphIR

START = "$start"
END = "$end"


def validate_ir(graph: GraphIR) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    nodes = {node.id for node in graph.nodes}
    valid = nodes | {START, END}
    adjacency: dict[str, set[str]] = defaultdict(set)

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
    for node in sorted(referenced_policies - nodes):
        diagnostics.append(
            _error("GRAPH-009", "spec.runtime", f"runtime references unknown node '{node}'")
        )

    reachable = _reachable(adjacency, START)
    for node in sorted(nodes - reachable):
        diagnostics.append(
            Diagnostic(
                code="GRAPH-005",
                severity=Severity.WARNING,
                path=f"spec.nodes.{node}",
                message=f"node '{node}' is unreachable from $start",
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
