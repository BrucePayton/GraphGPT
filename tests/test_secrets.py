from pathlib import Path

import pytest
from typer.testing import CliRunner

from graphgpt import validate_workflow
from graphgpt.application.secrets import REDACTED, redact_secrets
from graphgpt.cli import app
from graphgpt.domain.diagnostics import GraphGPTError
from graphgpt.registry import BindingRegistry

runner = CliRunner()


def test_rejects_plaintext_secrets_and_url_credentials_without_leaking_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(PLAINTEXT_WORKFLOW, encoding="utf-8")

    diagnostics = validate_workflow(path)
    rendered = "\n".join(item.render() for item in diagnostics)

    assert [item.code for item in diagnostics].count("GRAPHGPT-SEC-003") == 2
    assert "sk-live-sensitive" not in rendered
    assert "user:password" not in rendered
    assert "maxTokens" not in rendered


def test_inspect_redacts_plaintext_secrets_even_for_invalid_workflow(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(PLAINTEXT_WORKFLOW, encoding="utf-8")

    inspected = runner.invoke(app, ["inspect", str(path)])

    assert inspected.exit_code == 0
    assert "sk-live-sensitive" not in inspected.stdout
    assert "user:password" not in inspected.stdout
    assert inspected.stdout.count(REDACTED) == 2


def test_environment_reference_stays_unresolved_during_validation_and_inspection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(REFERENCE_WORKFLOW, encoding="utf-8")

    assert validate_workflow(path) == []
    inspected = runner.invoke(app, ["inspect", str(path)])
    assert inspected.exit_code == 0
    assert "${GRAPHGPT_TEST_API_KEY}" in inspected.stdout


def test_resolves_environment_reference_only_when_binding_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Model:
        def invoke(self, messages: object) -> object:
            return messages

    def init_model(name: str, **kwargs: object) -> Model:
        calls.append({"name": name, **kwargs})
        return Model()

    monkeypatch.setenv("GRAPHGPT_TEST_API_KEY", "resolved-secret")
    monkeypatch.setattr("langchain.chat_models.init_chat_model", init_model)
    BindingRegistry(discover_plugins=False).resolve_node(
        "langchain:model",
        {
            "model": "provider:model",
            "config": {"api_key": "${GRAPHGPT_TEST_API_KEY}", "max_tokens": 50},
        },
    )

    assert calls == [
        {"name": "provider:model", "api_key": "resolved-secret", "max_tokens": 50}
    ]


def test_direct_registry_usage_cannot_bypass_plaintext_secret_policy() -> None:
    with pytest.raises(GraphGPTError, match="GRAPHGPT-SEC-003") as raised:
        BindingRegistry(discover_plugins=False).resolve_node(
            "langchain:model",
            {"model": "provider:model", "config": {"api_key": "private-value"}},
        )

    assert "private-value" not in str(raised.value)


def test_missing_and_invalid_environment_references_have_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRAPHGPT_MISSING_SECRET", raising=False)
    with pytest.raises(GraphGPTError, match="GRAPHGPT_MISSING_SECRET") as raised:
        BindingRegistry(discover_plugins=False).resolve_node(
            "langchain:model",
            {
                "model": "provider:model",
                "config": {"api_key": "${GRAPHGPT_MISSING_SECRET}"},
            },
        )
    assert "${GRAPHGPT_MISSING_SECRET}" not in str(raised.value)

    path = tmp_path / "workflow.yaml"
    path.write_text(
        REFERENCE_WORKFLOW.replace("${GRAPHGPT_TEST_API_KEY}", "${INVALID-NAME}"),
        encoding="utf-8",
    )
    assert {item.code for item in validate_workflow(path)} == {
        "GRAPHGPT-SEC-003",
        "GRAPHGPT-SEC-004",
    }


def test_recursive_redaction_covers_headers_and_credential_urls() -> None:
    value = {
        "headers": {"Authorization": "Bearer private", "Accept": "application/json"},
        "endpoint": "https://user:password@example.com/path",
        "apiKey": "${SAFE_REFERENCE}",
    }

    assert redact_secrets(value) == {
        "headers": {"Authorization": REDACTED, "Accept": "application/json"},
        "endpoint": REDACTED,
        "apiKey": "${SAFE_REFERENCE}",
    }


PLAINTEXT_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: plaintext_secret}
spec:
  nodes:
    model:
      use: langchain:model
      with:
        model: provider:model
        config:
          apiKey: sk-live-sensitive
          maxTokens: 100
          endpoint: https://user:password@example.com/v1
  edges:
    - {from: $start, to: model}
    - {from: model, to: $end}
"""

REFERENCE_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: referenced_secret}
spec:
  nodes:
    model:
      use: langchain:model
      with:
        model: provider:model
        config:
          apiKey: ${GRAPHGPT_TEST_API_KEY}
  edges:
    - {from: $start, to: model}
    - {from: model, to: $end}
"""
