from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

UNIVERSAL_IR_VERSION = "graphgpt.dev/universal/v1alpha1"


class Fidelity(StrEnum):
    EXACT = "exact"
    ADAPTED = "adapted"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ConversionNotice:
    code: str
    fidelity: Fidelity
    message: str
    path: str = "asset"
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UniversalNode:
    id: str
    kind: Literal["start", "end", "action", "tool", "prompt", "resource", "instruction"]
    name: str
    binding: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UniversalEdge:
    source: str
    target: str
    condition: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UniversalAsset:
    name: str
    description: str
    kind: Literal["workflow", "skill", "toolset"]
    source_format: str
    inputs: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    outputs: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    instructions: str | None = None
    nodes: tuple[UniversalNode, ...] = ()
    edges: tuple[UniversalEdge, ...] = ()
    capabilities: frozenset[str] = frozenset()
    extensions: dict[str, Any] = field(default_factory=dict)
    api_version: str = UNIVERSAL_IR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "source_format": self.source_format,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "instructions": self.instructions,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "capabilities": sorted(self.capabilities),
            "extensions": self.extensions,
        }


@dataclass(frozen=True, slots=True)
class ConversionArtifact:
    path: str
    content: str
    media_type: str = "text/plain"


@dataclass(frozen=True, slots=True)
class ConversionResult:
    source_format: str
    target_format: str
    fidelity: Fidelity
    artifacts: tuple[ConversionArtifact, ...]
    notices: tuple[ConversionNotice, ...] = ()

    def report(self) -> dict[str, Any]:
        return {
            "source_format": self.source_format,
            "target_format": self.target_format,
            "fidelity": self.fidelity.value,
            "artifacts": [
                {"path": item.path, "media_type": item.media_type} for item in self.artifacts
            ],
            "notices": [item.to_dict() for item in self.notices],
        }
