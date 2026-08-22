from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from graphgpt.domain.ir import GraphIR

TEMPLATES = ("branch", "chat", "loop", "rag", "tool-use")
PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def initialize_project(template: str, destination: Path) -> list[Path]:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template '{template}'; choose from {', '.join(TEMPLATES)}")
    source = Path(__file__).parent / "templates" / template
    template_files = _template_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    generated_names = ("graph.py", "langgraph.json", "pyproject.toml", ".env")
    targets = [*(destination / item.name for item in template_files)]
    targets.extend(destination / name for name in generated_names)
    existing = [target for target in targets if target.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite {existing[0]}")

    created: list[Path] = []
    for item in template_files:
        target = destination / item.name
        shutil.copy2(item, target)
        created.append(target)
    graph_module = destination / "graph.py"
    graph_module.write_text(
        "from pathlib import Path\n\n"
        "from graphgpt import compile_workflow\n\n"
        "graph = compile_workflow(Path(__file__).with_name('workflow.yaml'))\n",
        encoding="utf-8",
    )
    created.append(graph_module)
    config = destination / "langgraph.json"
    config.write_text(
        json.dumps(
            {
                "dependencies": ["."],
                "graphs": {template: "./graph.py:graph"},
                "env": ".env",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    created.append(config)
    package_config = destination / "pyproject.toml"
    package_config.write_text(
        "[project]\n"
        f'name = "graphgpt-{template}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["graphgpt-builder>=0.8,<0.9", "langgraph>=1.0,<2.0"]\n',
        encoding="utf-8",
    )
    created.append(package_config)
    env_file = destination / ".env"
    env_file.write_text(
        "# LANGSMITH_TRACING=true\n# LANGSMITH_API_KEY=\n"
        "# LANGFUSE_PUBLIC_KEY=\n# LANGFUSE_SECRET_KEY=\n",
        encoding="utf-8",
    )
    created.append(env_file)
    return created


def initialize_plugin(name: str, destination: Path) -> list[Path]:
    """Create an independently installable GraphGPT plugin package."""
    if not PLUGIN_NAME_PATTERN.fullmatch(name):
        raise ValueError("plugin name must use lowercase letters, numbers, '_' or '-'")
    package = f"graphgpt_{name.replace('-', '_')}"
    files = {
        "README.md": _plugin_readme(name, package),
        ".gitignore": ".venv/\ndist/\n__pycache__/\n*.egg-info/\n",
        "pyproject.toml": _plugin_pyproject(name, package),
        f"src/{package}/__init__.py": (
            f'from {package}.plugin import plugin\n\n__all__ = ["plugin"]\n'
        ),
        f"src/{package}/plugin.py": _plugin_module(name),
        "tests/test_plugin.py": _plugin_test(package),
        ".github/workflows/ci.yml": _plugin_ci(),
        "LICENSE": _plugin_license(name),
    }
    targets = [destination / relative for relative in files]
    existing = [target for target in targets if target.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite {existing[0]}")

    created: list[Path] = []
    for relative, content in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(target)
    return created


def _template_files(source: Path) -> list[Path]:
    """Return deterministic, distributable template files only."""
    return sorted(
        (
            item
            for item in source.iterdir()
            if item.is_file()
            and not item.name.startswith(".")
            and item.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda item: item.name,
    )


def _plugin_pyproject(name: str, package: str) -> str:
    return f'''[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "graphgpt-{name}"
version = "0.1.0"
description = "A community plugin for GraphGPT"
readme = "README.md"
requires-python = ">=3.11"
license = {{ text = "Apache-2.0" }}
dependencies = ["graphgpt-builder>=0.8,<0.9"]

[project.optional-dependencies]
dev = ["mypy>=1.15", "pytest>=8.3", "ruff>=0.11"]

[project.entry-points."graphgpt.plugins"]
{name} = "{package}.plugin:plugin"

[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
'''


def _plugin_module(name: str) -> str:
    class_name = "".join(part.capitalize() for part in re.split(r"[-_]", name)) + "Plugin"
    return f'''from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from graphgpt import PluginCapability, PluginManifest


class {class_name}:
    manifest = PluginManifest(
        name="{name}",
        version="0.1.0",
        capabilities=frozenset({{"node"}}),
    )

    def resolve(
        self,
        capability: PluginCapability,
        name: str,
        config: Mapping[str, Any],
    ) -> Any:
        if capability != "node" or name != "echo":
            raise KeyError(f"unsupported resource: {{capability}}/{{name}}")
        prefix = str(config.get("prefix", ""))

        def echo(state: dict[str, Any]) -> dict[str, str]:
            return {{"result": prefix + str(state.get("input", ""))}}

        return echo


plugin = {class_name}()
'''


def _plugin_test(package: str) -> str:
    return f'''from graphgpt import validate_plugin

from {package}.plugin import plugin


def test_plugin_contract_and_echo_node() -> None:
    assert validate_plugin(plugin, expected_name=plugin.manifest.name) == []
    node = plugin.resolve("node", "echo", {{"prefix": "hello "}})
    assert node({{"input": "GraphGPT"}}) == {{"result": "hello GraphGPT"}}
'''


def _plugin_readme(name: str, package: str) -> str:
    return f'''# graphgpt-{name}

Community plugin for [GraphGPT](https://github.com/BrucePayton/GraphGPT).

## Develop

```bash
uv sync --extra dev
uv run pytest
uv build
```

After installation, verify discovery with:

```bash
graphgpt plugin list
```

Use the included node from a workflow:

```yaml
nodes:
  echo:
    use: plugin:{name}/echo
    with: {{prefix: "hello "}}
```

The entry point resolves `{package}.plugin:plugin` through the versioned
`graphgpt.dev/plugin/v1alpha1` protocol.
'''


def _plugin_license(name: str) -> str:
    return f'''Apache License
Version 2.0, January 2004
https://www.apache.org/licenses/

Copyright 2026 graphgpt-{name} contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''


def _plugin_ci() -> str:
    return '''name: ci

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync --extra dev
      - run: uv run ruff check src tests
      - run: uv run mypy src
      - run: uv run pytest
      - run: uv build
'''


def to_mermaid(graph: GraphIR) -> str:
    lines = ["flowchart TD"]
    names = {"$start": "START([START])", "$end": "END([END])"}
    lines.extend(f"    {node.id}[{node.id}]" for node in graph.nodes)
    for edge in graph.edges:
        source = names.get(edge.source, edge.source)
        if edge.target:
            target = names.get(edge.target, edge.target)
            lines.append(f"    {source} --> {target}")
        elif edge.route:
            for target in edge.route.targets:
                rendered = names.get(target, target)
                lines.append(f"    {source} -. route .-> {rendered}")
    return "\n".join(lines) + "\n"
