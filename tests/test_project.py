import json
from pathlib import Path

from graphgpt.project import _template_files, initialize_project


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
    package_config = (output / "pyproject.toml").read_text(encoding="utf-8")
    assert 'graphgpt-builder>=0.5,<0.6' in package_config


def test_template_files_ignore_runtime_artifacts(tmp_path: Path) -> None:
    (tmp_path / "workflow.yaml").write_text("kind: Workflow\n", encoding="utf-8")
    (tmp_path / "nodes.py").write_text("", encoding="utf-8")
    (tmp_path / "nodes.pyc").write_bytes(b"bytecode")
    (tmp_path / ".DS_Store").write_bytes(b"metadata")
    (tmp_path / "__pycache__").mkdir()

    assert [path.name for path in _template_files(tmp_path)] == ["nodes.py", "workflow.yaml"]


def test_init_preflights_all_outputs_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "agent"
    output.mkdir()
    graph_module = output / "graph.py"
    graph_module.write_text("# keep me\n", encoding="utf-8")

    try:
        initialize_project("branch", output)
    except FileExistsError as exc:
        assert str(graph_module) in str(exc)
    else:
        raise AssertionError("expected an existing generated file to block initialization")

    assert graph_module.read_text(encoding="utf-8") == "# keep me\n"
    assert sorted(path.name for path in output.iterdir()) == ["graph.py"]
