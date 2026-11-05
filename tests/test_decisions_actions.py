from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from graphgpt import ActionDefinition, BindingRegistry, DecisionRefusal, compile_workflow
from graphgpt.application.transform import to_ir
from graphgpt.application.validate import validate_ir
from graphgpt.decisions import make_decision_node, validate_answer
from graphgpt.domain.diagnostics import GraphGPTError
from graphgpt.domain.ir import DecisionIR
from graphgpt.dsl.models import WorkflowDocument


def document(node: dict, fields: dict | None = None) -> dict:
    return {
        "apiVersion": "graphgpt.dev/v1alpha1",
        "kind": "Workflow",
        "metadata": {"name": "decision_test"},
        "spec": {
            "state": {"fields": fields or {"answer": {"type": "string"}}},
            "nodes": {"decide": node},
            "runtime": {"checkpointer": "memory"},
            "edges": [{"from": "$start", "to": "decide"}, {"from": "decide", "to": "$end"}],
        },
    }


def compile_doc(tmp_path: Path, doc: dict, registry: BindingRegistry):
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(doc))
    return compile_workflow(path, registry=registry).with_config(
        {"configurable": {"thread_id": "test"}}
    )


def decision_node(policy: str = "error") -> dict:
    return {
        "decision": {
            "provider": "registry:provider",
            "question": {"type": "choice", "prompt": "Choose a route", "options": ["yes", "no"]},
            "outputKey": "answer",
            "refusalPolicy": policy,
            **({"fallback": "no"} if policy == "fallback" else {}),
        }
    }


def test_same_ir_switches_provider_and_routes(tmp_path: Path) -> None:
    doc = document(decision_node())
    doc["spec"]["nodes"].update(
        {"yes": {"use": "registry:identity"}, "no": {"use": "registry:identity"}}
    )
    doc["spec"]["edges"] = [
        {"from": "$start", "to": "decide"},
        {"from": "decide", "route": {"use": "registry:route", "targets": ["yes", "no"]}},
        {"from": "yes", "to": "$end"},
        {"from": "no", "to": "$end"},
    ]
    for answer in ("yes", "no"):
        registry = BindingRegistry(
            {
                "provider": lambda _, a=answer: a,
                "route": lambda state: state["answer"],
                "identity": lambda state: state,
            },
            discover_plugins=False,
        )
        graph = compile_doc(tmp_path, doc, registry)
        assert graph.invoke({})["answer"] == answer
        assert asyncio.run(graph.ainvoke({}))["answer"] == answer


@pytest.mark.parametrize("policy", ["error", "fallback", "interrupt"])
def test_refusal_paths(tmp_path: Path, policy: str) -> None:
    registry = BindingRegistry({"provider": lambda _: DecisionRefusal("no evidence")})
    graph = compile_doc(tmp_path, document(decision_node(policy)), registry)
    config = {"configurable": {"thread_id": "refusal"}}
    if policy == "error":
        with pytest.raises(ValueError, match="provider refused"):
            graph.invoke({}, config)
    elif policy == "fallback":
        assert graph.invoke({}, config)["answer"] == "no"
    else:
        assert graph.invoke({}, config)["__interrupt__"]
        assert graph.invoke(Command(resume="yes"), config)["answer"] == "yes"


@pytest.mark.parametrize(
    "question,value",
    [
        ({"type": "predicate"}, "true"),
        ({"type": "predicate"}, 1),
        ({"type": "choice", "options": ["yes"]}, "other"),
        ({"type": "score", "min": 0, "max": 1}, True),
        ({"type": "score", "min": 0, "max": 1}, float("nan")),
        ({"type": "score", "min": 0, "max": 1}, 2),
    ],
)
def test_invalid_answers_never_become_control_flow(question: dict, value: object) -> None:
    with pytest.raises(ValueError, match="invalid"):
        validate_answer(DecisionIR("registry:p", question, "answer"), value)


def test_valid_answers_and_failure_does_not_fallback() -> None:
    assert validate_answer(DecisionIR("p", {"type": "predicate"}, "a"), False) is False
    assert validate_answer(DecisionIR("p", {"type": "score", "min": 0, "max": 1}, "a"), 0.5) == 0.5
    decision = DecisionIR("p", {"type": "predicate"}, "a", "fallback", False)

    def fail(_):
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="offline"):
        make_decision_node(decision, fail).invoke({})
    with pytest.raises(ValueError, match="invalid"):
        make_decision_node(decision, lambda _: "true").invoke({})


def test_provider_cannot_rewrite_the_question_contract() -> None:
    decision = DecisionIR("p", {"type": "choice", "options": ["safe"]}, "a")

    def provider(payload):
        payload["question"]["options"].append("injected")
        return "injected"

    node = make_decision_node(decision, provider)
    with pytest.raises(ValueError, match="invalid"):
        node.invoke({})
    with pytest.raises(ValueError, match="invalid"):
        asyncio.run(node.ainvoke({}))
    assert decision.question["options"] == ["safe"]


def test_compile_time_decision_validation(tmp_path: Path) -> None:
    doc = document(decision_node())
    graph = to_ir(WorkflowDocument.model_validate(doc))
    with pytest.raises(GraphGPTError):
        compile_doc(tmp_path, doc, BindingRegistry())
    wrong_type = replace(graph, state_fields=())
    assert any(d.code.endswith("DECISION-001") for d in validate_ir(wrong_type))
    doc["spec"]["nodes"]["decide"] = decision_node("interrupt")
    doc["spec"]["runtime"] = {}
    assert any(
        d.code.endswith("DECISION-002")
        for d in validate_ir(to_ir(WorkflowDocument.model_validate(doc)))
    )
    doc["spec"]["nodes"]["decide"] = decision_node("fallback")
    doc["spec"]["nodes"]["decide"]["decision"]["fallback"] = "invalid"
    assert any(
        d.code.endswith("DECISION-003")
        for d in validate_ir(to_ir(WorkflowDocument.model_validate(doc)))
    )


@pytest.mark.parametrize(
    "question",
    [
        {"type": "choice", "prompt": "p", "options": ["x", "x"]},
        {"type": "score", "prompt": "p", "min": 2, "max": 1},
        {"type": "score", "prompt": "p", "min": 0, "max": float("inf")},
    ],
)
def test_invalid_question_schema(question: dict) -> None:
    node = decision_node()
    node["decision"]["question"] = question
    with pytest.raises(ValidationError):
        WorkflowDocument.model_validate(document(node))


class Input(BaseModel):
    value: int


class Output(BaseModel):
    answer: str


def test_action_contract_hooks_and_versions(tmp_path: Path) -> None:
    events = []

    def before(state):
        events.append("before")
        state["value"] = 999

    def action(state):
        events.append("action")
        return {"answer": str(state["value"])}

    registry = BindingRegistry({"before": before, "after": lambda _: events.append("after")})
    definition = ActionDefinition(action, Input, Output)
    registry.register_action("format", "1.0", definition)
    node = {
        "action": {
            "ref": "format",
            "version": "1.0",
            "before": ["registry:before"],
            "after": ["registry:after"],
        }
    }
    fields = {"value": {"type": "integer"}, "answer": {"type": "string"}}
    graph = compile_doc(tmp_path, document(node, fields), registry)
    assert graph.invoke({"value": 7})["answer"] == "7"
    assert asyncio.run(graph.ainvoke({"value": 8}))["answer"] == "8"
    assert events == ["before", "action", "after"] * 2
    with pytest.raises(ValidationError):
        graph.invoke({"value": "7"})
    with pytest.raises(ValueError, match="unique"):
        registry.register_action("format", "1.0", definition)
    node["action"]["version"] = "2.0"
    with pytest.raises(GraphGPTError, match="unknown action/version"):
        compile_doc(tmp_path, document(node, fields), registry)
    node["action"]["version"] = "1.0"
    with pytest.raises(GraphGPTError, match="incompatible state"):
        compile_doc(tmp_path, document(node), registry)


def test_action_output_and_hook_fail_closed(tmp_path: Path) -> None:
    fields = {"value": {"type": "integer"}, "answer": {"type": "string"}}
    registry = BindingRegistry()
    registry.register_action("bad", "1", ActionDefinition(lambda _: {"secret": 1}, Input, Output))
    node = {"action": {"ref": "bad", "version": "1"}}
    graph = compile_doc(tmp_path, document(node, fields), registry)
    with pytest.raises(ValueError, match="undeclared output"):
        graph.invoke({"value": 1})
    node["action"]["before"] = ["registry:missing"]
    with pytest.raises(GraphGPTError):
        compile_doc(tmp_path, document(node, fields), registry)
