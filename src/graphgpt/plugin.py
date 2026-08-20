from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from graphgpt.domain.diagnostics import Diagnostic, Severity

PLUGIN_API_VERSION = "graphgpt.dev/plugin/v1alpha1"
PLUGIN_ENTRY_POINT_GROUP = "graphgpt.plugins"
LEGACY_NODE_ENTRY_POINT_GROUP = "graphgpt.nodes"

PluginCapability = Literal["node", "route", "tool", "checkpointer", "store", "cache"]
PLUGIN_CAPABILITIES = frozenset(
    {"node", "route", "tool", "checkpointer", "store", "cache"}
)


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    capabilities: frozenset[PluginCapability]
    api_version: str = PLUGIN_API_VERSION


@runtime_checkable
class GraphGPTPlugin(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def resolve(
        self,
        capability: PluginCapability,
        name: str,
        config: Mapping[str, Any],
    ) -> Any: ...


def validate_plugin(plugin: object, *, expected_name: str | None = None) -> list[Diagnostic]:
    manifest = getattr(plugin, "manifest", None)
    if not isinstance(manifest, PluginManifest):
        return [_error("PLUGIN-001", "plugin manifest must be a PluginManifest")]
    diagnostics: list[Diagnostic] = []
    if manifest.api_version != PLUGIN_API_VERSION:
        diagnostics.append(
            _error(
                "PLUGIN-003",
                f"plugin API '{manifest.api_version}' is incompatible with '{PLUGIN_API_VERSION}'",
            )
        )
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", manifest.name):
        diagnostics.append(
            _error("PLUGIN-002", "plugin name must use lowercase letters, numbers, '_' or '-'")
        )
    if expected_name is not None and manifest.name != expected_name:
        diagnostics.append(
            _error(
                "PLUGIN-002",
                f"manifest name '{manifest.name}' does not match entry point '{expected_name}'",
            )
        )
    if not manifest.version.strip():
        diagnostics.append(_error("PLUGIN-002", "plugin version must not be empty"))
    unknown = set(manifest.capabilities) - PLUGIN_CAPABILITIES
    if not manifest.capabilities or unknown:
        diagnostics.append(
            _error(
                "PLUGIN-002",
                "plugin capabilities must be a non-empty supported set; "
                f"unknown: {sorted(unknown)}",
            )
        )
    if not callable(getattr(plugin, "resolve", None)):
        diagnostics.append(_error("PLUGIN-001", "plugin must define a callable resolve method"))
    return diagnostics


def _error(code: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=f"GRAPHGPT-{code}",
        severity=Severity.ERROR,
        path="plugin",
        message=message,
        hint=f"Implement the {PLUGIN_API_VERSION} GraphGPTPlugin protocol.",
    )
