from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from graphgpt.application.ecosystem import EcosystemArtifact, InvocationContract
from graphgpt.domain.conversion import (
    ConversionArtifact,
    ConversionNotice,
    Fidelity,
    UniversalAsset,
)
from graphgpt.domain.ir import GraphIR
from graphgpt.dsl.models import WorkflowDocument


class WorkflowLoader(Protocol):
    def load(self, path: Path) -> WorkflowDocument: ...


class GraphCompiler(Protocol):
    def compile(self, graph: GraphIR) -> Any: ...


class BindingResolver(Protocol):
    def resolve_node(self, reference: str, config: dict[str, Any]) -> Any: ...

    def resolve_route(self, reference: str) -> Any: ...

    def resolve_runtime(
        self,
        reference: str,
        kind: Literal["checkpointer", "store", "cache"] = "checkpointer",
    ) -> Any: ...


class EcosystemRenderer(Protocol):
    @property
    def target(self) -> str: ...

    def render(
        self,
        contract: InvocationContract,
        options: MappingProxyType[str, Any],
    ) -> tuple[EcosystemArtifact, ...]: ...


class ConversionAdapter(Protocol):
    @property
    def format(self) -> str: ...

    def load(
        self, path: Path, options: dict[str, Any]
    ) -> tuple[UniversalAsset, tuple[ConversionNotice, ...]]: ...

    def render(
        self, asset: UniversalAsset, options: dict[str, Any]
    ) -> tuple[
        tuple[ConversionArtifact, ...],
        Fidelity,
        tuple[ConversionNotice, ...],
    ]: ...
