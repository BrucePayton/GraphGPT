"""Deterministic evaluation plans and incremental, read-only LangSmith evaluation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from graphgpt.domain.ir import GraphIR
from graphgpt.tracing import trace_metadata


def evaluation_manifest(graph: GraphIR) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for node in graph.nodes:
        checks.append({"node_id": node.id, "check": "execution_succeeded"})
        if node.decision:
            checks.append(
                {
                    "node_id": node.id,
                    "check": "typed_decision",
                    "question": node.decision.question,
                    "output_key": node.decision.output_key,
                }
            )
        if node.approval or (node.decision and node.decision.refusal_policy == "interrupt"):
            checks.extend(
                {"node_id": node.id, "check": name, "requires_evaluator": True}
                for name in ("interrupt_resumed", "rejection_has_no_side_effects")
            )
    return {"schema_version": "1", **trace_metadata(graph), "checks": checks}


class LangSmithEvaluationAdapter:
    """Accept an authenticated LangSmith Client; never creates feedback implicitly."""

    def __init__(self, client: Any):
        self.client = client

    def evaluate(
        self,
        graph: GraphIR,
        *,
        project_name: str,
        node_id: str | None = None,
        limit: int = 100,
        evaluators: dict[str, Callable[[Any], bool]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if node_id is not None and node_id not in {node.id for node in graph.nodes}:
            raise ValueError("unknown evaluation node")
        identity = trace_metadata(graph, node_id=node_id)
        filters = [
            f"and(eq(metadata_key,{json.dumps(key)}),eq(metadata_value,{json.dumps(value)}))"
            for key, value in identity.items()
        ]
        if node_id is not None:
            filters.append(f"eq(name,{json.dumps(node_id)})")
        manifest = evaluation_manifest(graph)
        for run in self.client.list_runs(
            project_name=project_name,
            filter="and(" + ",".join(filters) + ")",
            limit=limit,
        ):
            metadata = (getattr(run, "extra", None) or {}).get("metadata", {})
            if any(metadata.get(key) != value for key, value in identity.items()):
                continue
            # Nested provider/hook spans inherit node metadata but have different outputs.
            if getattr(run, "name", None) != metadata.get("node_id"):
                continue
            for check in manifest["checks"]:
                if check["node_id"] != metadata.get("node_id"):
                    continue
                name = check["check"]
                status = "not_evaluated"
                try:
                    if name in (evaluators or {}):
                        outcome = (evaluators or {})[name](run)
                        if type(outcome) is not bool:
                            raise ValueError("evaluator must return bool")
                        status = "passed" if outcome else "failed"
                    elif name == "execution_succeeded":
                        status = (
                            "failed"
                            if run.error
                            else "passed"
                            if run.end_time is not None
                            else "pending"
                        )
                    elif name == "typed_decision" and run.end_time is not None:
                        from graphgpt.decisions import validate_answer

                        decision = next(n.decision for n in graph.nodes if n.id == check["node_id"])
                        assert decision is not None
                        validate_answer(decision, (run.outputs or {}).get(decision.output_key))
                        status = "failed" if run.error else "passed"
                except (ValueError, TypeError, KeyError):
                    status = "failed"
                yield {
                    **identity,
                    "node_id": check["node_id"],
                    "run_id": str(run.id),
                    "check": name,
                    "status": status,
                }
