from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from typer.testing import CliRunner

from graphgpt import (
    Fidelity,
    convert_asset,
    detect_asset_format,
    validate_workflow,
    write_conversion_result,
)
from graphgpt.cli import app

runner = CliRunner()


def test_detects_all_builtin_conversion_formats(tmp_path: Path) -> None:
    graphgpt = _write(tmp_path / "workflow.yaml", GRAPHGPT_WORKFLOW)
    mcp = _write(tmp_path / "mcp.json", json.dumps(MCP_SNAPSHOT))
    langgraph = _write(tmp_path / "langgraph.json", json.dumps(LANGGRAPH_GRAPH))
    n8n = _write(tmp_path / "n8n.json", json.dumps(N8N_WORKFLOW))
    dify = _write(tmp_path / "dify.yaml", yaml.safe_dump(DIFY_DSL))
    skill = tmp_path / "skill"
    skill.mkdir()
    _write(skill / "SKILL.md", SKILL)
    universal_result = convert_asset(graphgpt, target="universal")
    universal_dir = tmp_path / "universal"
    write_conversion_result(universal_result, universal_dir)

    assert detect_asset_format(graphgpt) == "graphgpt"
    assert detect_asset_format(mcp) == "mcp"
    assert detect_asset_format(langgraph) == "langgraph"
    assert detect_asset_format(n8n) == "n8n"
    assert detect_asset_format(dify) == "dify"
    assert detect_asset_format(skill) == "skill"
    assert detect_asset_format(universal_dir / "portable.universal.json") == "universal"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match=r"does not contain SKILL\.md"):
        detect_asset_format(empty)


def test_graphgpt_round_trip_is_exact_and_valid(tmp_path: Path) -> None:
    source = _write(tmp_path / "workflow.yaml", GRAPHGPT_WORKFLOW)

    universal = convert_asset(source, target="universal")
    universal_dir = tmp_path / "universal"
    write_conversion_result(universal, universal_dir)
    restored = convert_asset(
        universal_dir / "portable.universal.json",
        target="graphgpt",
    )
    restored_dir = tmp_path / "restored"
    write_conversion_result(restored, restored_dir)

    assert universal.fidelity == Fidelity.EXACT
    assert restored.fidelity == Fidelity.EXACT
    assert validate_workflow(restored_dir / "portable.workflow.yaml") == []
    report = json.loads((restored_dir / "conversion-report.json").read_text())
    assert report["fidelity"] == "exact"


def test_graphgpt_converts_to_mcp_skill_langgraph_and_dify(tmp_path: Path) -> None:
    source = _write(tmp_path / "workflow.yaml", GRAPHGPT_WORKFLOW)

    mcp = convert_asset(
        source,
        target="mcp",
        options={"base_url": "https://agents.example.com"},
    )
    skill = convert_asset(source, target="skill")
    langgraph = convert_asset(source, target="langgraph")
    dify = convert_asset(
        source,
        target="dify",
        options={"base_url": "https://agents.example.com"},
    )
    n8n = convert_asset(
        source,
        target="n8n",
        options={"base_url": "https://agents.example.com"},
    )

    assert mcp.fidelity == Fidelity.ADAPTED
    mcp_document = json.loads(mcp.artifacts[0].content)
    assert mcp_document["tools"][0]["inputSchema"]["required"] == ["input"]
    assert mcp_document["tools"][0]["annotations"]["graphgpt"]["endpoint"] == (
        "https://agents.example.com/workflows/portable/invoke"
    )
    assert skill.fidelity == Fidelity.LOSSY
    assert "## Transitions" in skill.artifacts[0].content
    assert langgraph.fidelity == Fidelity.ADAPTED
    langgraph_document = json.loads(langgraph.artifacts[0].content)
    assert {node["id"] for node in langgraph_document["nodes"]} >= {
        "__start__",
        "step",
        "__end__",
    }
    assert dify.fidelity == Fidelity.ADAPTED
    dify_openapi = next(item for item in dify.artifacts if item.path == "openapi.json")
    assert json.loads(dify_openapi.content)["openapi"] == "3.0.3"
    assert n8n.fidelity == Fidelity.ADAPTED
    n8n_workflow = next(item for item in n8n.artifacts if item.path.endswith(".workflow.json"))
    assert json.loads(n8n_workflow.content)["active"] is False


def test_imports_mcp_skill_langgraph_and_dify_with_honest_fidelity(
    tmp_path: Path,
) -> None:
    mcp = _write(tmp_path / "mcp.json", json.dumps(MCP_SNAPSHOT))
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    _write(skill_dir / "SKILL.md", SKILL)
    langgraph = _write(tmp_path / "langgraph.json", json.dumps(LANGGRAPH_GRAPH))
    dify = _write(tmp_path / "dify.yaml", yaml.safe_dump(DIFY_DSL))
    n8n = _write(tmp_path / "n8n.json", json.dumps(N8N_WORKFLOW))

    mcp_to_graph = convert_asset(mcp, target="graphgpt")
    skill_to_mcp = convert_asset(skill_dir, target="mcp")
    langgraph_to_universal = convert_asset(langgraph, target="universal")
    dify_to_universal = convert_asset(dify, target="universal")
    dify_round_trip = convert_asset(dify, target="dify")
    n8n_to_universal = convert_asset(n8n, target="universal")
    n8n_round_trip = convert_asset(n8n, target="n8n")

    assert mcp_to_graph.fidelity == Fidelity.LOSSY
    assert "registry:get_weather" in mcp_to_graph.artifacts[0].content
    mcp_graph_dir = tmp_path / "mcp-graph"
    write_conversion_result(mcp_to_graph, mcp_graph_dir)
    assert validate_workflow(mcp_graph_dir / "weather-tools.workflow.yaml") == []
    assert skill_to_mcp.fidelity == Fidelity.ADAPTED
    assert langgraph_to_universal.fidelity == Fidelity.LOSSY
    assert langgraph_to_universal.notices[0].code == "CONVERT-101"
    assert dify_to_universal.fidelity == Fidelity.ADAPTED
    universal = json.loads(dify_to_universal.artifacts[0].content)
    assert universal["extensions"]["dify"]["kind"] == "app"
    assert dify_round_trip.fidelity == Fidelity.ADAPTED
    assert yaml.safe_load(dify_round_trip.artifacts[0].content)["kind"] == "app"
    assert n8n_to_universal.fidelity == Fidelity.ADAPTED
    assert n8n_to_universal.notices[0].code == "CONVERT-104"
    assert n8n_round_trip.fidelity == Fidelity.ADAPTED
    assert json.loads(n8n_round_trip.artifacts[0].content)["name"] == "n8n Portable"
    dify_graph = convert_asset(dify, target="graphgpt")
    dify_graph_dir = tmp_path / "dify-graph"
    write_conversion_result(dify_graph, dify_graph_dir)
    assert validate_workflow(dify_graph_dir / "Dify Portable.workflow.yaml") == []


def test_skill_text_resources_round_trip_and_binary_loss_is_reported(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skill"
    references = skill_dir / "references"
    references.mkdir(parents=True)
    _write(skill_dir / "SKILL.md", SKILL)
    _write(references / "GUIDE.md", "# Guide\n")

    universal = convert_asset(skill_dir, target="universal")
    universal_dir = tmp_path / "universal"
    write_conversion_result(universal, universal_dir)
    restored = convert_asset(
        universal_dir / "weather-research.universal.json",
        target="skill",
    )
    restored_dir = tmp_path / "restored"
    write_conversion_result(restored, restored_dir)

    assert restored.fidelity == Fidelity.EXACT
    assert (restored_dir / "references/GUIDE.md").read_text() == "# Guide\n"

    (skill_dir / "assets").mkdir()
    (skill_dir / "assets/image.bin").write_bytes(b"\xff\x00")
    with_binary = convert_asset(skill_dir, target="universal")
    assert with_binary.fidelity == Fidelity.LOSSY
    assert with_binary.notices[0].code == "CONVERT-103"


def test_cli_convert_reports_and_can_reject_lossy_conversion(tmp_path: Path) -> None:
    source = _write(tmp_path / "workflow.yaml", GRAPHGPT_WORKFLOW)

    detected = runner.invoke(app, ["detect", str(source)])
    formats = runner.invoke(app, ["formats"])
    converted = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--to",
            "mcp",
            "--base-url",
            "https://agents.example.com",
            "--output",
            str(tmp_path / "mcp"),
        ],
    )
    rejected = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--to",
            "skill",
            "--fail-on-lossy",
            "--output",
            str(tmp_path / "rejected"),
        ],
    )

    assert detected.stdout.strip() == "graphgpt"
    assert "mcp" in formats.stdout.splitlines()
    assert converted.exit_code == 0
    assert "graphgpt -> mcp, adapted" in converted.stdout
    assert (tmp_path / "mcp/conversion-report.json").is_file()
    assert rejected.exit_code == 2
    assert not (tmp_path / "rejected").exists()
    assert '"fidelity": "lossy"' in rejected.output


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


GRAPHGPT_WORKFLOW = """\
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

MCP_SNAPSHOT = {
    "name": "weather-tools",
    "tools": [
        {
            "name": "get_weather",
            "description": "Get weather",
            "inputSchema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ],
    "prompts": [{"name": "weather-report", "description": "Create report"}],
    "resources": [{"uri": "weather://cities", "name": "Cities"}],
}

LANGGRAPH_GRAPH = {
    "name": "simple-graph",
    "nodes": [
        {"id": "__start__", "type": "runnable", "data": {"name": "__start__"}},
        {"id": "step", "type": "runnable", "data": {"name": "step"}},
        {"id": "__end__"},
    ],
    "edges": [
        {"source": "__start__", "target": "step"},
        {"source": "step", "target": "__end__"},
    ],
}

SKILL = """\
---
name: weather-research
description: Research weather and create a concise report.
---

# Instructions

Call the weather tool, verify the result, and summarize it.
"""

DIFY_DSL = {
    "app": {"name": "Dify Portable", "description": "Simple Dify flow", "mode": "workflow"},
    "kind": "app",
    "version": "0.3.0",
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [],
        "features": {},
        "graph": {
            "nodes": [
                {"id": "start", "data": {"type": "start", "title": "Start"}},
                {"id": "llm", "data": {"type": "llm", "title": "Generate"}},
                {"id": "end", "data": {"type": "end", "title": "End"}},
            ],
            "edges": [
                {"id": "start-llm", "source": "start", "target": "llm"},
                {"id": "llm-end", "source": "llm", "target": "end"},
            ],
        },
    },
}

N8N_WORKFLOW = {
    "name": "n8n Portable",
    "nodes": [
        {
            "id": "input",
            "name": "When Executed by Another Workflow",
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.1,
            "parameters": {"inputSource": "passthrough"},
        },
        {
            "id": "invoke",
            "name": "Invoke",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.3,
            "parameters": {"method": "POST", "url": "https://example.com"},
        },
    ],
    "connections": {
        "When Executed by Another Workflow": {
            "main": [[{"node": "Invoke", "type": "main", "index": 0}]]
        }
    },
    "settings": {"executionOrder": "v1"},
    "active": False,
}
