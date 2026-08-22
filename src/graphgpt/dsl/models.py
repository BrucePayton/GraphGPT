from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from graphgpt.domain.diagnostics import SourceLocation

API_VERSION = "graphgpt.dev/v1alpha1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MetadataModel(StrictModel):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    labels: dict[str, str] = Field(default_factory=dict)


class StateFieldModel(StrictModel):
    type: str = "any"
    required: bool = False
    reducer: str | None = None
    default: Any = None


class StateModel(StrictModel):
    type: Literal["dict", "messages"] = "dict"
    fields: dict[str, StateFieldModel] = Field(default_factory=dict)


class RetryPolicyModel(StrictModel):
    initial_interval: float = Field(default=0.5, gt=0, alias="initialInterval")
    backoff_factor: float = Field(default=2.0, ge=1, alias="backoffFactor")
    max_interval: float = Field(default=128.0, gt=0, alias="maxInterval")
    max_attempts: int = Field(default=3, ge=1, alias="maxAttempts")
    jitter: bool = True


class CachePolicyModel(StrictModel):
    ttl: int | None = Field(default=None, gt=0)


class SubgraphModel(StrictModel):
    path: str = Field(min_length=1)
    input_map: dict[str, str] = Field(default_factory=dict, alias="input")
    output_map: dict[str, str] = Field(default_factory=dict, alias="output")
    persistence: Literal["per-invocation", "per-thread", "stateless"] = "per-invocation"


class NodeModel(StrictModel):
    use: str | None = Field(default=None, min_length=1)
    subgraph: SubgraphModel | None = None
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    metadata: dict[str, Any] = Field(default_factory=dict)
    destinations: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    retry: RetryPolicyModel | None = None
    cache: CachePolicyModel | None = None

    @model_validator(mode="after")
    def exactly_one_action(self) -> NodeModel:
        if (self.use is None) == (self.subgraph is None):
            raise ValueError("a node must define exactly one of 'use' or 'subgraph'")
        return self


class RouteModel(StrictModel):
    use: str = Field(min_length=1)
    targets: list[str] = Field(min_length=1)
    path_map: dict[str, str] = Field(default_factory=dict, alias="pathMap")
    mode: Literal["conditional", "fan-out"] = "conditional"


class EdgeModel(StrictModel):
    source: str = Field(alias="from")
    target: str | None = Field(default=None, alias="to")
    route: RouteModel | None = None

    @model_validator(mode="after")
    def exactly_one_destination(self) -> EdgeModel:
        if (self.target is None) == (self.route is None):
            raise ValueError("an edge must define exactly one of 'to' or 'route'")
        return self


class RuntimeModel(StrictModel):
    interrupt_before: list[str] = Field(default_factory=list, alias="interruptBefore")
    interrupt_after: list[str] = Field(default_factory=list, alias="interruptAfter")
    checkpointer: str | None = None
    store: str | None = None
    cache: str | None = None


class SecurityModel(StrictModel):
    allowed_modules: list[str] = Field(default_factory=list, alias="allowedModules")


class SpecModel(StrictModel):
    state: StateModel = Field(default_factory=StateModel)
    nodes: dict[str, NodeModel] = Field(min_length=1)
    edges: list[EdgeModel] = Field(min_length=1)
    runtime: RuntimeModel = Field(default_factory=RuntimeModel)
    security: SecurityModel = Field(default_factory=SecurityModel)


class WorkflowDocument(StrictModel):
    _source_map: dict[str, SourceLocation] = PrivateAttr(default_factory=dict)

    api_version: Literal["graphgpt.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Workflow"]
    metadata: MetadataModel
    spec: SpecModel

    @property
    def source_map(self) -> dict[str, SourceLocation]:
        return self._source_map
