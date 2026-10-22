from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from graphgpt import (
    BindingRegistry,
    RuntimeCommand,
    StateInput,
    inspect_workflow,
    invoke_workflow,
    prepare_runtime_input,
    validate_workflow,
)
from graphgpt.domain.ir import ApprovalPolicyIR, ApprovalToolPolicyIR


def test_state_input_rejects_forged_control_and_undeclared_fields(tmp_path: Path) -> None:
    path = _write(tmp_path, BASIC_WORKFLOW)

    with pytest.raises(ValueError, match=r"undeclared fields.*resume"):
        prepare_runtime_input(path, StateInput({"count": 0, "resume": True}))
    with pytest.raises(ValueError, match=r"undeclared fields.*__interrupt__"):
        prepare_runtime_input(path, StateInput({"count": 0, "__interrupt__": []}))
    with pytest.raises(TypeError, match="StateInput or RuntimeCommand"):
        prepare_runtime_input(path, {"count": 0})  # type: ignore[arg-type]


def test_state_input_enforces_required_fields_and_types(tmp_path: Path) -> None:
    path = _write(tmp_path, BASIC_WORKFLOW)

    with pytest.raises(ValueError, match=r"missing required fields.*count"):
        prepare_runtime_input(path, StateInput({}))
    with pytest.raises(ValueError, match="field 'count' must be integer"):
        prepare_runtime_input(path, StateInput({"count": "zero"}))


def test_runtime_command_is_the_only_control_input(tmp_path: Path) -> None:
    path = _write(tmp_path, BASIC_WORKFLOW)

    command = prepare_runtime_input(path, RuntimeCommand.resume({"approved": True}))
    assert isinstance(command, Command)
    assert command.resume == {"approved": True}
    assert prepare_runtime_input(path, RuntimeCommand.continue_thread()) is None
    with pytest.raises(ValueError, match="cannot carry"):
        prepare_runtime_input(path, RuntimeCommand("continue", True))


def test_invoke_workflow_uses_strict_contract(tmp_path: Path) -> None:
    path = _write(tmp_path, BASIC_WORKFLOW)
    result = invoke_workflow(
        path,
        StateInput({"count": 1}),
        registry=BindingRegistry(
            {"increment": lambda state: {"count": state["count"] + 1}},
            discover_plugins=False,
        ),
    )
    assert result["count"] == 2


def test_approval_requires_agent_and_checkpointer(tmp_path: Path) -> None:
    wrong_node = _write(tmp_path, APPROVAL_WORKFLOW.replace("langchain:agent", "registry:step"))
    diagnostics = validate_workflow(wrong_node)
    codes = {item.code for item in diagnostics}
    assert "GRAPHGPT-HITL-001" in codes

    without_checkpoint = _write(
        tmp_path,
        APPROVAL_WORKFLOW.replace("  runtime:\n    checkpointer: memory\n", "  runtime: {}\n"),
        name="without-checkpoint.yaml",
    )
    diagnostics = validate_workflow(without_checkpoint)
    assert "GRAPHGPT-HITL-002" in {item.code for item in diagnostics}


def test_per_call_approval_maps_to_official_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)
    policy = ApprovalPolicyIR(
        mode="per_call",
        tools={
            "write_file": ApprovalToolPolicyIR(
                allowed_decisions=("approve", "reject"),
                description="Review workspace write",
            )
        },
    )
    def write_file() -> str:
        return "written"

    BindingRegistry({"write_file": write_file}, discover_plugins=False).resolve_node(
        "langchain:agent",
        {"model": "test-model", "tools": ["registry:write_file"]},
        policy,
    )

    middleware = captured["middleware"][0]
    assert middleware.interrupt_mode == "per_call"
    assert middleware.interrupt_on["write_file"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]


def test_approval_rejects_unknown_tool_policy() -> None:
    policy = ApprovalPolicyIR(
        tools={"delete_file": ApprovalToolPolicyIR(allowed_decisions=("approve",))}
    )
    with pytest.raises(ValueError, match=r"tools not registered.*delete_file"):
        BindingRegistry(discover_plugins=False).resolve_node(
            "langchain:agent",
            {"model": "test-model", "tools": []},
            policy,
        )


def test_per_call_approvals_are_independent_and_schema_validated() -> None:
    class FakeApprovalModel(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> FakeApprovalModel:
            return self

    calls: list[str] = []

    @tool
    def alpha(value: int) -> str:
        """Run alpha."""
        calls.append(f"alpha:{value}")
        return "alpha complete"

    @tool
    def beta(value: int) -> str:
        """Run beta."""
        calls.append(f"beta:{value}")
        return "beta complete"

    model = FakeApprovalModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "alpha", "args": {"value": 1}, "id": "alpha-1"},
                    {"name": "beta", "args": {"value": 2}, "id": "beta-1"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    agent = create_agent(
        model,
        tools=[alpha, beta],
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "alpha": {"allowed_decisions": ["approve", "reject"]},
                    "beta": {"allowed_decisions": ["approve", "reject"]},
                },
                interrupt_mode="per_call",
            )
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "independent-approvals"}}
    paused = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, config)
    interrupts = paused["__interrupt__"]
    assert {item.value["name"] for item in interrupts} == {"alpha", "beta"}
    assert calls == []

    alpha_interrupt = next(item for item in interrupts if item.value["name"] == "alpha")
    with pytest.raises(ValidationError):
        agent.invoke(Command(resume={alpha_interrupt.id: {"type": "edit"}}), config)
    assert calls == []

    still_paused = agent.invoke(
        Command(resume={alpha_interrupt.id: {"type": "approve"}}),
        config,
    )
    assert calls == ["alpha:1"]
    beta_interrupt = still_paused["__interrupt__"][0]
    completed = agent.invoke(
        Command(
            resume={beta_interrupt.id: {"type": "reject", "message": "not authorized"}}
        ),
        config,
    )
    assert calls == ["alpha:1"]
    assert completed["messages"][-1].content == "done"


def test_approval_ir_is_normalized_without_runtime_objects(tmp_path: Path) -> None:
    path = _write(tmp_path, APPROVAL_WORKFLOW)
    graph = inspect_workflow(path)
    policy = graph.nodes[0].approval
    assert policy is not None
    assert policy.mode == "per_call"
    assert policy.tools["write_file"].allowed_decisions == ("approve", "reject")


def _write(tmp_path: Path, content: str, name: str = "workflow.yaml") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


BASIC_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: strict_input}
spec:
  state:
    fields:
      count: {type: integer, required: true}
  nodes:
    increment: {use: registry:increment, writes: [count]}
  edges:
    - {from: $start, to: increment}
    - {from: increment, to: $end}
"""

APPROVAL_WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: approval}
spec:
  state: {type: messages}
  nodes:
    agent:
      use: langchain:agent
      with:
        model: test-model
        tools: []
      approval:
        mode: per_call
        tools:
          write_file:
            allowedDecisions: [approve, reject]
            description: Review workspace write
  edges:
    - {from: $start, to: agent}
    - {from: agent, to: $end}
  runtime:
    checkpointer: memory
"""
