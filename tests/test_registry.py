from types import SimpleNamespace

import pytest

from graphgpt.domain.diagnostics import GraphGPTError
from graphgpt.registry import BindingRegistry


def test_blocks_python_import_outside_allowlist() -> None:
    registry = BindingRegistry(allowed_modules=("my_project",), discover_plugins=False)
    with pytest.raises(GraphGPTError, match=r"outside security\.allowedModules"):
        registry.resolve_node("python:os.system", {})


def test_resolves_explicit_binding_without_import() -> None:
    def function(state: dict) -> dict:
        return state

    registry = BindingRegistry({"function": function}, discover_plugins=False)
    assert registry.resolve_node("registry:function", {}) is function


def test_imports_allowed_module_from_explicit_search_root(tmp_path) -> None:
    (tmp_path / "project_nodes.py").write_text(
        "def step(state): return {'ok': True}\n", encoding="utf-8"
    )
    registry = BindingRegistry(
        allowed_modules=("project_nodes",),
        search_path=tmp_path,
        discover_plugins=False,
    )
    node = registry.resolve_node("python:project_nodes.step", {})
    assert node({}) == {"ok": True}


def test_rejects_unsafe_missing_and_non_callable_bindings(tmp_path) -> None:
    registry = BindingRegistry(
        {"value": object()},
        allowed_modules=("project_nodes",),
        search_path=tmp_path,
        discover_plugins=False,
    )
    with pytest.raises(GraphGPTError, match=r"module\.symbol syntax"):
        registry.resolve_node("python:project_nodes.step()", {})
    with pytest.raises(GraphGPTError, match="could not import symbol"):
        registry.resolve_node("python:project_nodes.missing", {})
    with pytest.raises(GraphGPTError, match="neither callable nor Runnable"):
        registry.resolve_node("registry:value", {})
    with pytest.raises(GraphGPTError, match="route binding is not callable"):
        registry.resolve_route("registry:value")


def test_discovers_and_caches_node_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    class EntryPoint:
        name = "plugin"

        def load(self) -> object:
            loaded.append(self.name)
            return lambda state: {"plugin": True}

    monkeypatch.setattr("graphgpt.registry.entry_points", lambda **_: [EntryPoint()])
    registry = BindingRegistry()
    node = registry.resolve_node("registry:plugin", {})
    assert node({}) == {"plugin": True}
    assert registry.resolve_node("registry:plugin", {}) is node
    assert loaded == ["plugin"]


def test_builds_model_agent_tool_node_and_memory_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Model:
        def invoke(self, messages: object) -> str:
            return f"reply:{messages}"

    model_calls: list[tuple[str, dict[str, object]]] = []

    def init_model(name: str, **kwargs: object) -> Model:
        model_calls.append((name, kwargs))
        return Model()

    agent = object()
    agent_calls: list[dict[str, object]] = []

    def create_agent(**kwargs: object) -> object:
        agent_calls.append(kwargs)
        return agent

    tool_node_calls: list[list[object]] = []

    def tool_node(tools: list[object]) -> SimpleNamespace:
        tool_node_calls.append(tools)
        return SimpleNamespace(tools=tools, invoke=lambda state: state)

    monkeypatch.setattr("langchain.chat_models.init_chat_model", init_model)
    monkeypatch.setattr("langchain.agents.create_agent", create_agent)
    monkeypatch.setattr("langgraph.prebuilt.ToolNode", tool_node)

    tool = lambda value: value  # noqa: E731
    registry = BindingRegistry({"tool": tool}, discover_plugins=False)
    model_node = registry.resolve_node(
        "langchain:model",
        {
            "model": "provider:model",
            "config": {"temperature": 0},
            "inputKey": "input",
            "outputKey": "output",
        },
    )
    assert model_node({"input": "hello"}) == {"output": ["reply:hello"]}
    assert model_calls == [("provider:model", {"temperature": 0})]

    resolved_agent = registry.resolve_node(
        "langchain:agent",
        {"model": "provider:model", "tools": ["registry:tool"], "systemPrompt": "help"},
    )
    assert resolved_agent is agent
    assert agent_calls == [
        {"model": "provider:model", "tools": [tool], "system_prompt": "help"}
    ]

    resolved_tool_node = registry.resolve_node(
        "langgraph:tool-node", {"tools": ["registry:tool"]}
    )
    assert resolved_tool_node.tools == [tool]
    assert tool_node_calls == [[tool]]
    assert registry.resolve_runtime("memory", "checkpointer").__class__.__name__ == (
        "InMemorySaver"
    )
    assert registry.resolve_runtime("memory", "store").__class__.__name__ == "InMemoryStore"
    assert registry.resolve_runtime("in-memory", "cache").__class__.__name__ == (
        "InMemoryCache"
    )


@pytest.mark.parametrize("reference", ["langchain:model", "langchain:agent"])
def test_model_and_agent_require_model(reference: str) -> None:
    registry = BindingRegistry(discover_plugins=False)
    with pytest.raises(ValueError, match=r"requires with\.model"):
        registry.resolve_node(reference, {})
