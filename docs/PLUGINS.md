# Plugin author guide

GraphGPT plugins are normal Python distributions registered through the `graphgpt.plugins` entry
point group. They extend bindings without adding provider dependencies to the compiler core.

## Generate a package

```bash
pip install graphgpt-builder
graphgpt plugin init ./graphgpt-acme --name acme
cd graphgpt-acme
uv sync --extra dev
uv run pytest
uv build
```

The generated wheel includes an example `plugin:acme/echo` node, contract test, Apache-2.0 license,
and package metadata.

## Protocol

An entry point resolves to one object with a `PluginManifest` and `resolve` method:

```python
from collections.abc import Mapping
from typing import Any

from graphgpt import PluginCapability, PluginManifest


class AcmePlugin:
    manifest = PluginManifest(
        name="acme",
        version="1.0.0",
        capabilities=frozenset({"node", "tool"}),
    )

    def resolve(
        self,
        capability: PluginCapability,
        name: str,
        config: Mapping[str, Any],
    ) -> Any:
        ...


plugin = AcmePlugin()
```

Register it in `pyproject.toml`:

```toml
[project.entry-points."graphgpt.plugins"]
acme = "graphgpt_acme.plugin:plugin"
```

The current API is `graphgpt.dev/plugin/v1alpha1`. Supported capabilities are `node`, `route`,
`tool`, `checkpointer`, `store`, and `cache`. Plugins should reject unknown resource names and must
not mutate the read-only configuration mapping passed to `resolve`.

## References

| Capability | Workflow reference |
|---|---|
| node | `plugin:acme/my-node` in `nodes.<id>.use` |
| route | `plugin:acme/my-route` in `edges[].route.use` |
| tool | `plugin:acme/my-tool` in agent/tool configuration |
| checkpointer/store/cache | `plugin:acme/backend` in runtime configuration |

## Diagnostics and compatibility

Run `graphgpt plugin list` after installation. The command validates manifest names, API versions,
declared capabilities, duplicate entry points, and load failures. JSON output is suitable for CI:

```bash
graphgpt plugin list --output json
```

Pin a tested GraphGPT minor range in plugin metadata. A plugin API change will use a new independent
API version and include migration guidance; package version equality alone does not imply protocol
compatibility.

## Security

Plugin discovery imports the registered object, and compilation invokes plugin code. Never install
untrusted plugin packages. Do not place plaintext API keys in workflow configuration; accept
GraphGPT environment references and resolve secrets only at binding creation time.
