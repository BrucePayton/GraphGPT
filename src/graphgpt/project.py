from __future__ import annotations

import json
import shutil
from pathlib import Path

from graphgpt.domain.ir import GraphIR

TEMPLATES = ("branch", "chat", "loop", "rag", "tool-use")


def initialize_project(template: str, destination: Path) -> list[Path]:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template '{template}'; choose from {', '.join(TEMPLATES)}")
    source = Path(__file__).parent / "templates" / template
    destination.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for item in source.iterdir():
        target = destination / item.name
        if target.exists():
            raise FileExistsError(f"refusing to overwrite {target}")
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
                "$schema": "https://langgra.ph/schema.json",
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
        'dependencies = ["graphgpt-builder>=0.1,<0.2", "langgraph>=1.0,<2.0"]\n',
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
