import sys
from pathlib import Path
from types import ModuleType

import pytest

from graphgpt import BindingRegistry, compile_workflow
from graphgpt.domain.diagnostics import GraphGPTError
from graphgpt.observability import callback_for
from graphgpt.project import to_mermaid


def test_yaml_syntax_error_has_stable_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("spec: [unterminated", encoding="utf-8")
    with pytest.raises(GraphGPTError) as raised:
        compile_workflow(path)
    assert raised.value.diagnostics[0].code == "GRAPHGPT-YAML-001"


def test_compile_rejects_semantic_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(WORKFLOW.replace("to: step", "to: absent"), encoding="utf-8")
    with pytest.raises(GraphGPTError, match="no reachable path"):
        compile_workflow(path, registry=BindingRegistry({"step": lambda state: state}))


def test_observability_none_and_langsmith_are_zero_dependency() -> None:
    assert callback_for("none") is None
    assert callback_for("langsmith") is None


def test_observability_langfuse_callback_and_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    langfuse = ModuleType("langfuse")
    integration = ModuleType("langfuse.langchain")

    class CallbackHandler:
        pass

    integration.CallbackHandler = CallbackHandler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", integration)
    assert isinstance(callback_for("langfuse"), CallbackHandler)

    monkeypatch.setitem(sys.modules, "langfuse.langchain", None)
    with pytest.raises(RuntimeError, match=r"langfuse.*extra"):
        callback_for("langfuse")


def test_registry_reports_missing_binding_and_bad_reference() -> None:
    registry = BindingRegistry(discover_plugins=False)
    with pytest.raises(GraphGPTError, match="not registered"):
        registry.resolve_node("registry:missing", {})
    with pytest.raises(GraphGPTError, match="unsupported binding scheme"):
        registry.resolve_node("missing", {})
    with pytest.raises(GraphGPTError, match=r"module\.symbol"):
        registry.resolve_node("python:bad", {})


def test_mermaid_renders_conditional_targets(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(CONDITIONAL, encoding="utf-8")
    from graphgpt import inspect_workflow

    rendered = to_mermaid(inspect_workflow(path))
    assert "route" in rendered
    assert "END([END])" in rendered


WORKFLOW = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: test}
spec:
  nodes:
    step: {use: registry:step}
  edges:
    - {from: $start, to: step}
    - {from: step, to: $end}
"""

CONDITIONAL = """\
apiVersion: graphgpt.dev/v1alpha1
kind: Workflow
metadata: {name: condition}
spec:
  nodes:
    step: {use: registry:step}
  edges:
    - {from: $start, to: step}
    - from: step
      route:
        use: registry:route
        targets: [step, $end]
"""
