"""GraphGPT public API."""

from graphgpt.api import (
    compile_workflow,
    inspect_workflow,
    load_workflow,
    render_ecosystem_bundle,
    validate_workflow,
    write_ecosystem_bundle,
)
from graphgpt.application.ecosystem import EcosystemArtifact, InvocationContract
from graphgpt.application.ports import EcosystemRenderer
from graphgpt.plugin import (
    PLUGIN_API_VERSION,
    PLUGIN_ENTRY_POINT_GROUP,
    GraphGPTPlugin,
    PluginCapability,
    PluginInspection,
    PluginManifest,
    inspect_installed_plugins,
    validate_plugin,
)
from graphgpt.registry import BindingRegistry

__all__ = [
    "PLUGIN_API_VERSION",
    "PLUGIN_ENTRY_POINT_GROUP",
    "BindingRegistry",
    "EcosystemArtifact",
    "EcosystemRenderer",
    "GraphGPTPlugin",
    "InvocationContract",
    "PluginCapability",
    "PluginInspection",
    "PluginManifest",
    "compile_workflow",
    "inspect_installed_plugins",
    "inspect_workflow",
    "load_workflow",
    "render_ecosystem_bundle",
    "validate_plugin",
    "validate_workflow",
    "write_ecosystem_bundle",
]
__version__ = "0.8.0"
