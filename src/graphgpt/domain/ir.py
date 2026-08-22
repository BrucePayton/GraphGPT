from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from graphgpt.domain.diagnostics import SourceLocation

IR_VERSION = "0.4"
BUILTIN_STATE_TYPES = frozenset(
    {
        "any",
        "string",
        "str",
        "integer",
        "int",
        "number",
        "float",
        "boolean",
        "bool",
        "object",
        "array",
        "messages",
    }
)
BUILTIN_REDUCERS = frozenset({"add", "messages"})


@dataclass(frozen=True, slots=True)
class StateFieldIR:
    name: str
    type: str = "any"
    required: bool = False
    reducer: str | None = None
    default: Any = None


@dataclass(frozen=True, slots=True)
class RetryPolicyIR:
    initial_interval: float = 0.5
    backoff_factor: float = 2.0
    max_interval: float = 128.0
    max_attempts: int = 3
    jitter: bool = True


@dataclass(frozen=True, slots=True)
class CachePolicyIR:
    ttl: int | None = None


@dataclass(frozen=True, slots=True)
class SubgraphIR:
    path: str
    input_map: dict[str, str] = field(default_factory=dict)
    output_map: dict[str, str] = field(default_factory=dict)
    persistence: Literal["per-invocation", "per-thread", "stateless"] = "per-invocation"


@dataclass(frozen=True, slots=True)
class NodeIR:
    id: str
    use: str | None = None
    subgraph: SubgraphIR | None = None
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    destinations: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    retry: RetryPolicyIR | None = None
    cache: CachePolicyIR | None = None


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
    kind: Literal["direct", "conditional", "fan-out"] = "direct"


@dataclass(frozen=True, slots=True)
class RuntimeIR:
    interrupt_before: tuple[str, ...] = ()
    interrupt_after: tuple[str, ...] = ()
    checkpointer: str | None = None
    store: str | None = None
    cache: str | None = None


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
    source_map: dict[str, SourceLocation] = field(default_factory=dict, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document.pop("source_map")
        return document
