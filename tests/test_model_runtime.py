import asyncio

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from graphgpt.registry import BindingRegistry


def test_flush_tracing_only_touches_selected_provider(monkeypatch):
    from types import SimpleNamespace

    from graphgpt.observability import flush_tracing

    flushed = []
    monkeypatch.setattr(
        "graphgpt.observability.import_module",
        lambda name: SimpleNamespace(
            get_client=lambda: SimpleNamespace(flush=lambda: flushed.append(name))
        ),
    )
    flush_tracing("none")
    flush_tracing("langsmith")
    assert flushed == []
    flush_tracing("langfuse")
    assert flushed == ["langfuse"]


def test_model_node_preserves_config_and_native_async_events(monkeypatch):
    model = FakeListChatModel(responses=["hello"])
    monkeypatch.setattr("langchain.chat_models.init_chat_model", lambda *a, **k: model)
    node = BindingRegistry(discover_plugins=False).resolve_node(
        "langchain:model", {"model": "fake", "inputKey": "prompt", "outputKey": "reply"}
    )
    starts = []

    class Callback(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            starts.append(kwargs)

    config = {"callbacks": [Callback()], "tags": ["audit"], "metadata": {"node_id": "model"}}
    assert node.invoke({"prompt": "test"}, config)["reply"][0].content == "hello"

    async def verify():
        # Prove the async path never falls back to the model's synchronous invoke.
        def forbidden(*args, **kwargs):
            raise AssertionError("sync model invoke used by async node")

        monkeypatch.setattr(FakeListChatModel, "invoke", forbidden)
        assert (await node.ainvoke({"prompt": "test"}, config))["reply"][0].content == "hello"
        events = [e async for e in node.astream_events({"prompt": "test"}, config, version="v2")]
        chunks = [
            e["data"]["chunk"].content for e in events if e["event"] == "on_chat_model_stream"
        ]
        assert "".join(chunks) == "hello"
        assert all(e["metadata"]["node_id"] == "model" for e in events)

    asyncio.run(verify())
    assert len(starts) == 3
    assert all(
        "audit" in start["tags"] and start["metadata"]["node_id"] == "model" for start in starts
    )


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_cli_flushes_langfuse_on_success_and_failure(tmp_path, monkeypatch, fail, stream):
    from test_cli import PYTHON_WORKFLOW
    from typer.testing import CliRunner

    from graphgpt.cli import app

    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(PYTHON_WORKFLOW)
    (tmp_path / "nodes.py").write_text("def step(state): return {'result': 'ok'}\n")
    flushed = []
    monkeypatch.setattr("graphgpt.cli.callback_for", lambda _: None)
    monkeypatch.setattr("graphgpt.cli.flush_tracing", flushed.append)
    if fail:

        class BrokenGraph:
            def invoke(self, *args, **kwargs):
                raise RuntimeError("synthetic failure")

            stream = invoke

        monkeypatch.setattr("graphgpt.cli.compile_workflow", lambda _: BrokenGraph())
    args = ["run", str(workflow), "--trace", "langfuse"] + (["--stream"] if stream else [])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == (1 if fail else 0), result.output
    assert flushed == ["langfuse"]
