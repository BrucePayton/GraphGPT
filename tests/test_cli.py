from pathlib import Path

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
    assert "GraphGPT 0.1.0" in doctor.stdout


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

