from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from graphgpt.domain.ir import GraphIR
from graphgpt.dsl.models import WorkflowDocument


class WorkflowLoader(Protocol):
    def load(self, path: Path) -> WorkflowDocument: ...


class GraphCompiler(Protocol):
    def compile(self, graph: GraphIR) -> Any: ...


class BindingResolver(Protocol):
    def resolve_node(self, reference: str, config: dict[str, Any]) -> Any: ...

    def resolve_route(self, reference: str) -> Any: ...

    def resolve_runtime(self, reference: str) -> Any: ...

