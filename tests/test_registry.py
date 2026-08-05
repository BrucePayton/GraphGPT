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
