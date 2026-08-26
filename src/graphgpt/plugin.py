from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Literal, Protocol, runtime_checkable

from graphgpt.domain.diagnostics import Diagnostic, Severity

PLUGIN_API_VERSION = "graphgpt.dev/plugin/v1alpha1"
PLUGIN_ENTRY_POINT_GROUP = "graphgpt.plugins"
LEGACY_NODE_ENTRY_POINT_GROUP = "graphgpt.nodes"

PluginCapability = Literal[
    "node",
    "route",
    "tool",
    "checkpointer",
    "store",
    "cache",
    "ecosystem",
]
PLUGIN_CAPABILITIES = frozenset(
    {"node", "route", "tool", "checkpointer", "store", "cache", "ecosystem"}
)


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    capabilities: frozenset[PluginCapability]
    api_version: str = PLUGIN_API_VERSION


@dataclass(frozen=True, slots=True)
class PluginInspection:
    """A safe, serializable view of one installed plugin entry point."""

    name: str
    entry_point: str
    distribution: str | None
    manifest: PluginManifest | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def healthy(self) -> bool:
        return not self.diagnostics

    def to_dict(self) -> dict[str, Any]:
        manifest = self.manifest
        return {
            "name": self.name,
            "entry_point": self.entry_point,
            "distribution": self.distribution,
            "healthy": self.healthy,
            "manifest": (
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "api_version": manifest.api_version,
                    "capabilities": sorted(manifest.capabilities),
                }
                if manifest
                else None
            ),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


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


def inspect_installed_plugins() -> tuple[PluginInspection, ...]:
    """Discover and validate installed GraphGPT plugins without resolving resources."""
    grouped: dict[str, list[Any]] = {}
    for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP):
        grouped.setdefault(point.name, []).append(point)

    inspections: list[PluginInspection] = []
    for name, points in sorted(grouped.items()):
        rendered_points = tuple(sorted(_entry_point_value(point) for point in points))
        if len(points) > 1:
            inspections.append(
                PluginInspection(
                    name=name,
                    entry_point=", ".join(rendered_points),
                    distribution=None,
                    manifest=None,
                    diagnostics=(
                        _error(
                            "PLUGIN-005",
                            f"multiple entry points register plugin '{name}': "
                            f"{list(rendered_points)}",
                        ),
                    ),
                )
            )
            continue

        point = points[0]
        try:
            candidate = point.load()
        except Exception as exc:
            inspections.append(
                PluginInspection(
                    name=name,
                    entry_point=rendered_points[0],
                    distribution=_distribution_name(point),
                    manifest=None,
                    diagnostics=(
                        _error(
                            "PLUGIN-006",
                            f"plugin '{name}' failed to load ({type(exc).__name__})",
                        ),
                    ),
                )
            )
            continue

        manifest = getattr(candidate, "manifest", None)
        diagnostics = tuple(validate_plugin(candidate, expected_name=name))
        inspections.append(
            PluginInspection(
                name=name,
                entry_point=rendered_points[0],
                distribution=_distribution_name(point),
                manifest=manifest if isinstance(manifest, PluginManifest) else None,
                diagnostics=diagnostics,
            )
        )
    return tuple(inspections)


def _entry_point_value(point: Any) -> str:
    return str(getattr(point, "value", "unknown"))


def _distribution_name(point: Any) -> str | None:
    distribution = getattr(point, "dist", None)
    if distribution is None:
        return None
    name = getattr(distribution, "name", None)
    return str(name) if name else None


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
