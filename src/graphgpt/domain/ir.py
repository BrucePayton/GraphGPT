from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

IR_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class StateFieldIR:
    name: str
    type: str = "any"
    required: bool = False
    reducer: str | None = None
    default: Any = None


@dataclass(frozen=True, slots=True)
class NodeIR:
    id: str
    use: str
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteIR:
    use: str
    targets: tuple[str, ...]
    path_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EdgeIR:
    source: str
    target: str | None = None
    route: RouteIR | None = None
    kind: Literal["direct", "conditional"] = "direct"


@dataclass(frozen=True, slots=True)
class RuntimeIR:
    interrupt_before: tuple[str, ...] = ()
    interrupt_after: tuple[str, ...] = ()
    checkpointer: str | None = None
    store: str | None = None


@dataclass(frozen=True, slots=True)
class GraphIR:
    name: str
    api_version: str
    state_type: str
    state_fields: tuple[StateFieldIR, ...]
    nodes: tuple[NodeIR, ...]
    edges: tuple[EdgeIR, ...]
    runtime: RuntimeIR = RuntimeIR()
    allowed_modules: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    ir_version: str = IR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

