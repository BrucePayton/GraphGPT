import json
from pathlib import Path

from graphgpt.project import initialize_project


def test_init_generates_langgraph_cli_project(tmp_path: Path) -> None:
    output = tmp_path / "agent"
    created = initialize_project("branch", output)
    assert len(created) == 6
    config = json.loads((output / "langgraph.json").read_text(encoding="utf-8"))
    assert config == {
        "dependencies": ["."],
        "graphs": {"branch": "./graph.py:graph"},
        "env": ".env",
    }
    assert "compile_workflow" in (output / "graph.py").read_text(encoding="utf-8")
    assert "graphgpt-builder" in (output / "pyproject.toml").read_text(encoding="utf-8")
