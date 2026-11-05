"""Deterministic evaluation plans and read-only Langfuse observation evaluation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime
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


class LangfuseEvaluationAdapter:
    """Accept a Langfuse 4.7+ client scoped to a project by its API keys.

    Uses Observations v2 (Cloud or self-hosted v4+); never writes scores.
    """

    def __init__(self, client: Any):
        self.client = client

    def evaluate(
        self,
        graph: GraphIR,
        *,
        from_start_time: datetime,
        to_start_time: datetime,
        node_id: str | None = None,
        limit: int = 100,
        max_pages: int = 100,
        evaluators: dict[str, Callable[[Any], bool]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        if limit < 1 or max_pages < 1:
            raise ValueError("limit and max_pages must be positive")
        if (
            from_start_time.utcoffset() is None
            or to_start_time.utcoffset() is None
            or from_start_time >= to_start_time
        ):
            raise ValueError("provide an ordered, timezone-aware time range")
        if node_id is not None and node_id not in {node.id for node in graph.nodes}:
            raise ValueError("unknown evaluation node")
        identity = trace_metadata(graph, node_id=node_id)
        filters = [
            {
                "type": "stringObject",
                "column": "metadata",
                "key": key,
                "operator": "=",
                "value": value,
            }
            for key, value in identity.items()
        ]
        # Advanced filters take precedence over fixed parameters, so include time here.
        filters.extend(
            [
                {
                    "type": "datetime",
                    "column": "startTime",
                    "operator": ">=",
                    "value": from_start_time.isoformat(),
                },
                {
                    "type": "datetime",
                    "column": "startTime",
                    "operator": "<",
                    "value": to_start_time.isoformat(),
                },
            ]
        )
        if node_id is not None:
            filters.append({"type": "string", "column": "name", "operator": "=", "value": node_id})
        manifest = evaluation_manifest(graph)
        for run in self._observations(
            filters,
            from_start_time,
            to_start_time,
            limit,
            max_pages,
        ):
            metadata = _json_object(run.metadata)
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
                            if run.level == "ERROR"
                            else "passed"
                            if run.end_time is not None
                            else "pending"
                        )
                    elif name == "typed_decision" and run.end_time is not None:
                        from graphgpt.decisions import validate_answer

                        decision = next(n.decision for n in graph.nodes if n.id == check["node_id"])
                        assert decision is not None
                        validate_answer(decision, _json_object(run.output).get(decision.output_key))
                        status = "failed" if run.level == "ERROR" else "passed"
                except (ValueError, TypeError, KeyError):
                    status = "failed"
                yield {
                    **identity,
                    "node_id": check["node_id"],
                    "run_id": str(run.id),
                    "trace_id": run.trace_id,
                    "observation_id": str(run.id),
                    "check": name,
                    "status": status,
                }

    def _observations(
        self,
        filters: list[dict[str, str]],
        start: datetime,
        end: datetime,
        limit: int,
        max_pages: int,
    ) -> Iterator[Any]:
        cursor = None
        seen: set[str] = set()
        remaining = limit
        for _ in range(max_pages):
            page = self.client.api.observations.get_many(
                fields="core,basic,io,metadata",
                filter=json.dumps(filters),
                from_start_time=start,
                to_start_time=end,
                limit=min(remaining, 1000),
                cursor=cursor,
            )
            for observation in page.data:
                yield observation
                remaining -= 1
                if remaining == 0:
                    return
            cursor = page.meta.cursor
            if not cursor:
                return
            if cursor in seen:
                raise RuntimeError("Langfuse returned a repeated pagination cursor")
            seen.add(cursor)
        raise RuntimeError("Langfuse pagination exceeded max_pages; narrow the time range")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}
