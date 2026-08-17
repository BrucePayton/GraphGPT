import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from graphgpt.cli import app

runner = CliRunner()


def test_cli_validate_inspect_schema_export_and_doctor(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(WORKFLOW, encoding="utf-8")

    validated = runner.invoke(app, ["validate", str(workflow)])
    assert validated.exit_code == 0
    assert "OK:" in validated.stdout

    inspected = runner.invoke(app, ["inspect", str(workflow)])
    assert inspected.exit_code == 0
    assert '"ir_version": "0.1"' in inspected.stdout

    schema = runner.invoke(app, ["schema"])
    assert schema.exit_code == 0
    assert "graphgpt.dev/v1alpha1" in schema.stdout

    exported = runner.invoke(app, ["export", str(workflow)])
    assert exported.exit_code == 0
    assert "flowchart TD" in exported.stdout

    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    assert "GraphGPT 0.1.2" in doctor.stdout


def test_cli_init_and_bad_input(tmp_path: Path) -> None:
    target = tmp_path / "agent"
    initialized = runner.invoke(app, ["init", str(target), "--template", "loop"])
    assert initialized.exit_code == 0
    assert (target / "langgraph.json").exists()

    invalid = target / "invalid.yaml"
    invalid.write_text("kind: Workflow\n", encoding="utf-8")
    validated = runner.invoke(app, ["validate", str(invalid), "--output", "json"])
    assert validated.exit_code == 1
    assert "GRAPHGPT-SCHEMA-001" in validated.stdout

    missing = runner.invoke(
        app,
        ["validate", str(tmp_path / "missing.yaml"), "--output", "json"],
    )
    assert missing.exit_code == 1
    assert "GRAPHGPT-IO-001" in missing.stdout
    assert "Traceback" not in missing.output


def test_cli_run_stream_export_files_and_version(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    nodes = tmp_path / "nodes.py"
    workflow.write_text(PYTHON_WORKFLOW, encoding="utf-8")
    nodes.write_text("def step(state): return {'result': 'ok'}\n", encoding="utf-8")

    invoked = runner.invoke(app, ["run", str(workflow), "--input", "{}"])
    assert invoked.exit_code == 0
    assert json.loads(invoked.stdout) == {"result": "ok"}

    streamed = runner.invoke(app, ["run", str(workflow), "--input", "{}", "--stream"])
    assert streamed.exit_code == 0
    assert "result" in streamed.stdout

    schema_path = tmp_path / "schema.json"
    schema = runner.invoke(app, ["schema", "--output", str(schema_path)])
    assert schema.exit_code == 0
    assert "graphgpt.dev/v1alpha1" in schema_path.read_text(encoding="utf-8")

    export_path = tmp_path / "graph.json"
    exported = runner.invoke(
        app,
        ["export", str(workflow), "--format", "json", "--output", str(export_path)],
    )
    assert exported.exit_code == 0
    assert json.loads(export_path.read_text(encoding="utf-8"))["name"] == "python_test"

    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.stdout.strip() == "0.1.2"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["run", "workflow.yaml", "--input", "{"], "Expecting"),
        (["run", "workflow.yaml", "--trace", "invalid"], "trace must be"),
        (["export", "workflow.yaml", "--format", "dot"], "format must be"),
    ],
)
def test_cli_rejects_bad_arguments(tmp_path: Path, args: list[str], message: str) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(WORKFLOW, encoding="utf-8")
    args[1] = str(workflow)
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert message in result.output


def test_cli_init_rejects_unknown_template_and_existing_files(tmp_path: Path) -> None:
    unknown = runner.invoke(app, ["init", str(tmp_path / "unknown"), "--template", "missing"])
    assert unknown.exit_code == 1
    assert "unknown template" in unknown.output

    target = tmp_path / "existing"
    first = runner.invoke(app, ["init", str(target), "--template", "chat"])
    second = runner.invoke(app, ["init", str(target), "--template", "chat"])
    assert first.exit_code == 0
    assert second.exit_code == 1
    assert "refusing to overwrite" in second.output


def test_cli_dev_delegates_with_supported_config_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "langgraph.json"
    config.write_text("{}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(shutil, "which", lambda _: "/tools/langgraph")

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        captured["args"] = args
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.invoke(
        app,
        ["dev", "--config", str(config), "--no-browser", "--port", "9000"],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "/tools/langgraph",
        "dev",
        "--config",
        "langgraph.json",
        "--no-browser",
        "--port",
        "9000",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["check"] is False


def test_cli_dev_reports_missing_executable_or_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    missing_cli = runner.invoke(app, ["dev"])
    assert missing_cli.exit_code == 1
    assert "langgraph CLI not found" in missing_cli.output

    monkeypatch.setattr(shutil, "which", lambda _: "/tools/langgraph")
    missing_config = runner.invoke(app, ["dev", "--config", str(tmp_path / "missing.json")])
    assert missing_config.exit_code == 1
    assert "config not found" in missing_config.output


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: cli_test
spec:
  nodes:
    step: {use: registry:step}
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""

PYTHON_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: python_test
spec:
  state:
    fields:
      result: {type: string}
  security:
    allowedModules: [nodes]
  nodes:
    step: {use: python:nodes.step}
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""
