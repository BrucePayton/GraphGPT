from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from graphgpt import (
    PLUGIN_API_VERSION,
    EcosystemArtifact,
    PluginManifest,
    compile_workflow,
    inspect_installed_plugins,
    validate_plugin,
)
from graphgpt.domain.diagnostics import GraphGPTError
from graphgpt.plugin import PluginCapability
from graphgpt.registry import BindingRegistry


class ExamplePlugin:
    manifest = PluginManifest(
        name="example",
        version="1.2.3",
        capabilities=frozenset({"node", "route", "tool", "cache"}),
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def resolve(
        self,
        capability: PluginCapability,
        name: str,
        config: Mapping[str, Any],
    ) -> Any:
        self.calls.append((capability, name, dict(config)))
        if capability == "node":
            amount = int(config.get("amount", 1))
            return lambda state: {"value": state["value"] + amount}
        if capability == "route":
            return lambda state: name if state else "$end"
        if capability == "tool":
            return lambda value: f"{name}:{value}"
        return {"runtime": name}


class EntryPoint:
    def __init__(self, name: str, value: object, loads: list[str]) -> None:
        self.name = name
        self.value = f"example_plugins:{name}"
        self.dist = None
        self._value = value
        self._loads = loads

    def load(self) -> object:
        self._loads.append(self.name)
        return self._value


def _discovery(monkeypatch: pytest.MonkeyPatch, *points: EntryPoint) -> None:
    def discover(*, group: str) -> list[EntryPoint]:
        return list(points) if group == "graphgpt.plugins" else []

    monkeypatch.setattr("graphgpt.registry.entry_points", discover)


def test_resolves_versioned_plugin_capabilities_and_caches_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ExamplePlugin()
    loads: list[str] = []
    _discovery(monkeypatch, EntryPoint("example", plugin, loads))
    registry = BindingRegistry()

    node = registry.resolve_node("plugin:example/increment", {"amount": 2})
    route = registry.resolve_route("plugin:example/finish")
    tool = registry._resolve("plugin:example/echo")
    cache = registry.resolve_runtime("plugin:example/local", "cache")

    assert node({"value": 1}) == {"value": 3}
    assert route({}) == "$end"
    assert tool("hello") == "echo:hello"
    assert cache == {"runtime": "local"}
    assert loads == ["example"]
    assert plugin.calls == [
        ("node", "increment", {"amount": 2}),
        ("route", "finish", {}),
        ("tool", "echo", {}),
        ("cache", "local", {}),
    ]


def test_resolves_ecosystem_renderer_from_versioned_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Renderer:
        target = "portable"

        def render(self, contract: object, options: object) -> tuple[EcosystemArtifact, ...]:
            return (EcosystemArtifact("portable.txt", "ok\n"),)

    class EcosystemPlugin:
        manifest = PluginManifest(
            name="portable",
            version="1.0.0",
            capabilities=frozenset({"ecosystem"}),
        )

        def resolve(
            self,
            capability: PluginCapability,
            name: str,
            config: Mapping[str, Any],
        ) -> Any:
            assert (capability, name, dict(config)) == (
                "ecosystem",
                "renderer",
                {"dialect": "v1"},
            )
            return Renderer()

    _discovery(monkeypatch, EntryPoint("portable", EcosystemPlugin(), []))

    renderer = BindingRegistry().resolve_ecosystem(
        "plugin:portable/renderer", {"dialect": "v1"}
    )

    assert renderer.target == "portable"


def test_compiles_plugin_node_from_workflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin = ExamplePlugin()
    _discovery(monkeypatch, EntryPoint("example", plugin, []))
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: plugin_workflow}
spec:
  state:
    fields:
      value: {type: integer, required: true}
  nodes:
    increment:
      use: plugin:example/increment
      with: {amount: 4}
  edges:
    - {from: $start, to: increment}
    - {from: increment, to: $end}
""",
        encoding="utf-8",
    )

    graph = compile_workflow(workflow)

    assert graph.invoke({"value": 2})["value"] == 6


def test_rejects_incompatible_manifest_and_missing_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incompatible = ExamplePlugin()
    incompatible.manifest = PluginManifest(
        name="example",
        version="1.0.0",
        capabilities=frozenset({"node"}),
        api_version="graphgpt.dev/plugin/v2",
    )
    _discovery(monkeypatch, EntryPoint("example", incompatible, []))

    with pytest.raises(GraphGPTError) as raised:
        BindingRegistry().resolve_node("plugin:example/step", {})
    assert raised.value.diagnostics[0].code == "GRAPHGPT-PLUGIN-003"

    node_only = ExamplePlugin()
    node_only.manifest = PluginManifest(
        name="example",
        version="1.0.0",
        capabilities=frozenset({"node"}),
    )
    _discovery(monkeypatch, EntryPoint("example", node_only, []))
    with pytest.raises(GraphGPTError, match="does not declare the 'route' capability"):
        BindingRegistry().resolve_route("plugin:example/route")


def test_rejects_duplicate_missing_and_malformed_plugin_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ExamplePlugin()
    _discovery(
        monkeypatch,
        EntryPoint("example", plugin, []),
        EntryPoint("example", plugin, []),
    )
    registry = BindingRegistry()

    with pytest.raises(GraphGPTError, match="multiple entry points"):
        registry.resolve_node("plugin:example/step", {})
    with pytest.raises(GraphGPTError, match="is not installed"):
        registry.resolve_node("plugin:missing/step", {})
    with pytest.raises(GraphGPTError, match="expected plugin:<plugin-name>/<resource-name>"):
        registry.resolve_node("plugin:example", {})


def test_public_plugin_validator_reports_structural_errors() -> None:
    class InvalidPlugin:
        manifest = PluginManifest(
            name="Invalid Name",
            version="",
            capabilities=frozenset(),
            api_version="invalid",
        )

    diagnostics = validate_plugin(InvalidPlugin(), expected_name="expected")

    assert PLUGIN_API_VERSION == "graphgpt.dev/plugin/v1alpha1"
    assert {item.code for item in diagnostics} == {
        "GRAPHGPT-PLUGIN-001",
        "GRAPHGPT-PLUGIN-002",
        "GRAPHGPT-PLUGIN-003",
    }


def test_isolates_plugin_load_and_resolution_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEntryPoint(EntryPoint):
        def load(self) -> object:
            raise ImportError("private import details")

    _discovery(monkeypatch, BrokenEntryPoint("example", object(), []))
    with pytest.raises(GraphGPTError, match=r"failed to load \(ImportError\)"):
        BindingRegistry().resolve_node("plugin:example/step", {})

    class BrokenPlugin(ExamplePlugin):
        def resolve(
            self,
            capability: PluginCapability,
            name: str,
            config: Mapping[str, Any],
        ) -> Any:
            raise ValueError("private resolution details")

    _discovery(monkeypatch, EntryPoint("example", BrokenPlugin(), []))
    with pytest.raises(GraphGPTError, match=r"failed while resolving 'step' \(ValueError\)"):
        BindingRegistry().resolve_node("plugin:example/step", {})


def test_inspects_installed_plugins_as_stable_serializable_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = EntryPoint("example", ExamplePlugin(), [])
    monkeypatch.setattr("graphgpt.plugin.entry_points", lambda *, group: [point])

    inspections = inspect_installed_plugins()

    assert len(inspections) == 1
    assert inspections[0].healthy
    assert inspections[0].to_dict() == {
        "name": "example",
        "entry_point": "example_plugins:example",
        "distribution": None,
        "healthy": True,
        "manifest": {
            "name": "example",
            "version": "1.2.3",
            "api_version": PLUGIN_API_VERSION,
            "capabilities": ["cache", "node", "route", "tool"],
        },
        "diagnostics": [],
    }


def test_inspection_isolates_duplicate_and_broken_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenEntryPoint(EntryPoint):
        def load(self) -> object:
            raise ImportError("private details")

    points = [
        EntryPoint("duplicate", ExamplePlugin(), []),
        EntryPoint("duplicate", ExamplePlugin(), []),
        BrokenEntryPoint("broken", object(), []),
    ]
    monkeypatch.setattr("graphgpt.plugin.entry_points", lambda *, group: points)

    inspections = inspect_installed_plugins()

    assert [item.name for item in inspections] == ["broken", "duplicate"]
    assert [item.diagnostics[0].code for item in inspections] == [
        "GRAPHGPT-PLUGIN-006",
        "GRAPHGPT-PLUGIN-005",
    ]
    assert "private details" not in str([item.to_dict() for item in inspections])
