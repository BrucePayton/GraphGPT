from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from typer.testing import CliRunner

from graphgpt.adapters.ecosystems import DifyRenderer, N8nRenderer
from graphgpt.api import render_ecosystem_bundle, write_ecosystem_bundle
from graphgpt.application.ecosystem import (
    ECOSYSTEM_API_VERSION,
    EcosystemArtifact,
    build_invocation_contract,
)
from graphgpt.cli import app
from graphgpt.domain.ir import GraphIR, StateFieldIR

runner = CliRunner()


def test_builds_framework_neutral_contract_from_graph_state() -> None:
    graph = GraphIR(
        name="research_agent",
        api_version="graphgpt.dev/v1alpha1",
        state_type="dict",
        state_fields=(
            StateFieldIR(name="query", type="string", required=True),
            StateFieldIR(name="limit", type="integer", default=5),
            StateFieldIR(name="messages", type="messages"),
        ),
        nodes=(),
        edges=(),
    )

    contract = build_invocation_contract(graph, base_url="https://agents.example.com/")

    assert contract.api_version == ECOSYSTEM_API_VERSION
    assert contract.operation_id == "invoke_graphgpt_research_agent"
    assert contract.endpoint == "https://agents.example.com/workflows/research_agent/invoke"
    assert contract.input_schema["required"] == ["query"]
    assert contract.input_schema["properties"]["limit"] == {
        "type": "integer",
        "default": 5,
    }
    assert contract.input_schema["properties"]["messages"]["items"]["type"] == "object"

    with pytest.raises(ValueError, match="absolute HTTP"):
        build_invocation_contract(graph, base_url="http://")


def test_dify_renderer_produces_openapi_custom_tool() -> None:
    contract = build_invocation_contract(_graph(), base_url="https://api.example.com")

    artifacts = DifyRenderer().render(contract, _empty_options())
    rendered = {artifact.path: artifact.content for artifact in artifacts}
    openapi = json.loads(rendered["openapi.json"])

    operation = openapi["paths"]["/workflows/portable/invoke"]["post"]
    assert operation["operationId"] == "invoke_graphgpt_portable"
    assert operation["security"] == [{"bearerAuth": []}]
    assert openapi["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert json.loads(rendered["graphgpt.contract.json"])["auth"] == "bearer"


def test_n8n_renderer_produces_inactive_callable_subworkflow() -> None:
    contract = build_invocation_contract(_graph(), base_url="https://api.example.com")

    artifacts = N8nRenderer().render(contract, _empty_options())
    rendered = {artifact.path: artifact.content for artifact in artifacts}
    workflow = json.loads(rendered["portable.workflow.json"])

    assert workflow["active"] is False
    assert workflow["nodes"][0]["type"] == "n8n-nodes-base.executeWorkflowTrigger"
    assert workflow["nodes"][1]["type"] == "n8n-nodes-base.httpRequest"
    assert workflow["nodes"][1]["parameters"]["url"].endswith("/workflows/portable/invoke")
    assert workflow["nodes"][1]["parameters"]["genericAuthType"] == "httpHeaderAuth"


def test_render_and_write_bundle_refuses_unknown_targets_and_overwrites(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(WORKFLOW, encoding="utf-8")
    output = tmp_path / "dify"

    artifacts = render_ecosystem_bundle(
        workflow,
        target="dify",
        base_url="https://api.example.com",
    )
    created = write_ecosystem_bundle(artifacts, output)

    assert {path.name for path in created} == {
        "README.md",
        "graphgpt.contract.json",
        "openapi.json",
    }
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_ecosystem_bundle(artifacts, output)
    with pytest.raises(ValueError, match="duplicate artifact paths"):
        write_ecosystem_bundle(
            (EcosystemArtifact("same.txt", "one"), EcosystemArtifact("same.txt", "two")),
            tmp_path / "duplicate",
        )
    with pytest.raises(ValueError, match="unknown ecosystem target"):
        render_ecosystem_bundle(
            workflow,
            target="unknown",
            base_url="https://api.example.com",
        )


@pytest.mark.parametrize("path", ["../secret", "/tmp/secret", "folder/../secret"])
def test_artifacts_reject_path_traversal(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe ecosystem artifact path"):
        EcosystemArtifact(path, "secret")


def test_cli_lists_and_exports_dify_and_n8n(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(WORKFLOW, encoding="utf-8")

    listed = runner.invoke(app, ["ecosystem", "list"])
    dify = runner.invoke(
        app,
        [
            "ecosystem",
            "export",
            str(workflow),
            "--target",
            "dify",
            "--base-url",
            "https://api.example.com",
            "--output",
            str(tmp_path / "dify"),
        ],
    )
    n8n = runner.invoke(
        app,
        [
            "ecosystem",
            "export",
            str(workflow),
            "--target",
            "n8n",
            "--base-url",
            "https://api.example.com",
            "--output",
            str(tmp_path / "n8n"),
            "--auth",
            "none",
        ],
    )

    assert listed.exit_code == 0
    assert listed.stdout.splitlines() == ["dify", "n8n"]
    assert dify.exit_code == 0
    assert (tmp_path / "dify/openapi.json").is_file()
    assert n8n.exit_code == 0
    n8n_workflow = json.loads((tmp_path / "n8n/portable.workflow.json").read_text())
    assert "authentication" not in n8n_workflow["nodes"][1]["parameters"]


def _graph() -> GraphIR:
    return GraphIR(
        name="portable",
        api_version="graphgpt.dev/v1alpha1",
        state_type="dict",
        state_fields=(StateFieldIR(name="input", type="string", required=True),),
        nodes=(),
        edges=(),
    )


def _empty_options() -> MappingProxyType[str, Any]:
    return MappingProxyType({})


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata:
  name: portable
spec:
  state:
    fields:
      input: {type: string, required: true}
      output: {type: string}
  security:
    allowedModules: [nodes]
  nodes:
    step:
      use: python:nodes.step
      writes: [output]
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""
