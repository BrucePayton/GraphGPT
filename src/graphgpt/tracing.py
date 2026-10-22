from __future__ import annotations

import hashlib
import json
from typing import Any

from graphgpt.domain.ir import GraphIR
from graphgpt.version import __version__


def graph_version(graph: GraphIR) -> str:
    """Return a deterministic content version for normalized graph semantics."""
    canonical = json.dumps(
        graph.to_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()[:16]


def trace_metadata(graph: GraphIR, *, node_id: str | None = None) -> dict[str, str]:
    """Build stable metadata understood by LangGraph/LangSmith callbacks."""
    metadata = {
        "graph_id": graph.name,
        "graph_version": graph_version(graph),
        "generator_version": __version__,
    }
    if node_id is not None:
        metadata["node_id"] = node_id
    return metadata


def merge_trace_config(graph: GraphIR, config: dict[str, Any] | None) -> dict[str, Any]:
    """Add reserved trace identity fields without mutating caller configuration."""
    merged = dict(config or {})
    user_metadata = merged.get("metadata", {})
    if not isinstance(user_metadata, dict):
        raise ValueError("config.metadata must be a JSON object")
    merged["metadata"] = {**user_metadata, **trace_metadata(graph)}
    return merged
