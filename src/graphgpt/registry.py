from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, NoReturn, cast

from graphgpt.domain.diagnostics import Diagnostic, GraphGPTError, Severity


class BindingRegistry:
    """Explicit project bindings plus safe plugin and Python-reference resolution."""

    def __init__(
        self,
        bindings: dict[str, Any] | None = None,
        *,
        allowed_modules: tuple[str, ...] = (),
        search_path: Path | None = None,
        discover_plugins: bool = True,
    ) -> None:
        self._bindings = dict(bindings or {})
        self._allowed_modules = allowed_modules
        self._search_path = search_path.resolve() if search_path else None
        self._plugins: dict[str, Any] = {}
        if discover_plugins:
            for point in entry_points(group="graphgpt.nodes"):
                self._plugins.setdefault(point.name, point)

    def resolve_node(self, reference: str, config: dict[str, Any]) -> Any:
        if reference == "langchain:model":
            return _make_model_node(config)
        if reference == "langchain:agent":
            return _make_agent_node(config, self)
        if reference == "langgraph:tool-node":
            return _make_tool_node(config, self)
        value = self._resolve(reference)
        if hasattr(value, "invoke") or callable(value):
            return value
        self._fail("BIND-007", reference, "node binding is neither callable nor Runnable")

    def resolve_route(self, reference: str) -> Callable[..., Any]:
        value = self._resolve(reference)
        if callable(value):
            return cast(Callable[..., Any], value)
        self._fail("BIND-007", reference, "route binding is not callable")

    def resolve_runtime(self, reference: str) -> Any:
        if reference in {"memory", "in-memory"}:
            return _memory_runtime(reference)
        return self._resolve(reference)

    def _resolve(self, reference: str) -> Any:
        if reference.startswith("registry:"):
            name = reference.removeprefix("registry:")
            if name in self._bindings:
                return self._bindings[name]
            if name in self._plugins:
                value = self._plugins[name].load()
                self._bindings[name] = value
                return value
            self._fail("PLUGIN-003", reference, f"binding '{name}' is not registered")
        if reference.startswith("python:"):
            return self._import_python(reference.removeprefix("python:"))
        self._fail(
            "BIND-001",
            reference,
            "unsupported binding scheme; use python:, registry:, or a built-in adapter",
        )

    def _import_python(self, target: str) -> Any:
        if "(" in target or ")" in target or ":" in target:
            self._fail("SEC-001", target, "Python references must use module.symbol syntax")
        module_name, separator, symbol = target.rpartition(".")
        if not separator or not module_name or not symbol:
            self._fail("BIND-002", target, "expected python:module.symbol")
        allowed = any(
            module_name == prefix or module_name.startswith(prefix + ".")
            for prefix in self._allowed_modules
        )
        if not allowed:
            self._fail(
                "SEC-001",
                target,
                f"module '{module_name}' is outside security.allowedModules",
            )
        try:
            with self._module_search_path():
                return getattr(import_module(module_name), symbol)
        except (ImportError, AttributeError) as exc:
            self._fail("BIND-003", target, f"could not import symbol: {exc}")

    @contextmanager
    def _module_search_path(self) -> Iterator[None]:
        value = str(self._search_path) if self._search_path else None
        if value and value not in sys.path:
            sys.path.insert(0, value)
            try:
                yield
            finally:
                sys.path.remove(value)
        else:
            yield

    @staticmethod
    def _fail(code: str, path: str, message: str) -> NoReturn:
        raise GraphGPTError(
            [
                Diagnostic(
                    code=f"GRAPHGPT-{code}",
                    severity=Severity.ERROR,
                    path=path,
                    message=message,
                )
            ]
        )


def _make_model_node(config: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError("Install GraphGPT with the 'langchain' extra") from exc
    model_name = config.get("model")
    if not isinstance(model_name, str):
        raise ValueError("langchain:model requires with.model")
    kwargs = dict(config.get("config", {}))
    model = init_chat_model(model_name, **kwargs)
    input_key = str(config.get("inputKey", "messages"))
    output_key = str(config.get("outputKey", "messages"))

    def invoke(state: dict[str, Any]) -> dict[str, Any]:
        return {output_key: [model.invoke(state[input_key])]}

    return invoke


def _make_agent_node(config: dict[str, Any], registry: BindingRegistry) -> Any:
    try:
        from langchain.agents import create_agent
    except ImportError as exc:
        raise RuntimeError("Install GraphGPT with the 'langchain' extra") from exc
    model = config.get("model")
    if not isinstance(model, str):
        raise ValueError("langchain:agent requires with.model")
    tools = [registry._resolve(str(item)) for item in config.get("tools", [])]
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=config.get("systemPrompt"),
    )


def _make_tool_node(config: dict[str, Any], registry: BindingRegistry) -> Any:
    from langgraph.prebuilt import ToolNode

    tools = [registry._resolve(str(item)) for item in config.get("tools", [])]
    return ToolNode(tools)


def _memory_runtime(reference: str) -> Any:
    if reference == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()
