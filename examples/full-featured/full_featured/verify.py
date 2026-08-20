from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from langgraph.types import Command

from graphgpt import inspect_workflow, validate_workflow
from graphgpt.application.secrets import redact_secrets


def main() -> None:
    os.environ.setdefault("GRAPHGPT_DEMO_API_KEY", "local-demo-secret")

    from full_featured.graph import graph
    from full_featured.nodes import counters, reset_counters

    workflow = Path(__file__).with_name("workflow.yaml")
    server_workflow = Path(__file__).with_name("server.yaml")
    diagnostics = validate_workflow(workflow)
    assert diagnostics == [], [item.render() for item in diagnostics]
    server_diagnostics = validate_workflow(server_workflow)
    assert server_diagnostics == [], [item.render() for item in server_diagnostics]

    local_ir = redact_secrets(inspect_workflow(workflow).to_dict())
    server_ir = redact_secrets(inspect_workflow(server_workflow).to_dict())
    local_ir["runtime"]["checkpointer"] = "server-managed"
    assert local_ir == server_ir, "local and server workflows must only differ by checkpointer"
    safe_ir = json.dumps(local_ir, sort_keys=True)
    assert "local-demo-secret" not in safe_ir
    assert "${GRAPHGPT_DEMO_API_KEY}" in safe_ir

    reset_counters()
    first_config = _config("example-1", "acme")
    interrupted = graph.invoke({"request": "2,3,4"}, config=first_config)
    _assert_interrupted(interrupted, expected="approved")
    assert interrupted["summary"] == "count=3 sum=29"
    assert interrupted["secret_status"] == "configured"
    assert "example:tenant=acme" in interrupted["audit"]
    assert counters()["attempts"] == {(4, 9, 16): 2}
    assert counters()["summary_calls"] == 1

    completed = graph.invoke(
        Command(resume={"reviewer": "demo", "approved": True}),
        config=first_config,
    )
    assert "human:demo=True" in completed["audit"]

    second = graph.invoke({"request": "2,3,4"}, config=_config("example-2", "beta"))
    _assert_interrupted(second, expected="approved")
    assert counters()["summary_calls"] == 1, "CachePolicy should reuse the summary"

    streamed = list(
        graph.stream({"request": "1,2"}, config=_config("example-stream", "stream"))
    )
    assert any("__interrupt__" in event for event in streamed)

    async_result = asyncio.run(
        graph.ainvoke({"request": "1,1"}, config=_config("example-async", "async"))
    )
    _assert_interrupted(async_result, expected="rejected")

    print(
        json.dumps(
            {
                "status": "ok",
                "features": [
                    "plugin",
                    "secret-reference",
                    "send-fanout",
                    "reducer",
                    "subgraph-mapping",
                    "retry",
                    "cache",
                    "command",
                    "interrupt-resume",
                    "sync-async-stream",
                    "runnable-config",
                ],
                "counters": _json_counters(counters()),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _config(thread_id: str, tenant: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "tags": ["full-featured-example"],
        "metadata": {"tenant": tenant},
    }


def _assert_interrupted(state: dict[str, Any], *, expected: str) -> None:
    assert state["decision"] == expected
    assert state["__interrupt__"][0].value["kind"] == "human-review"


def _json_counters(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempts": {str(key): count for key, count in value["attempts"].items()},
        "summary_calls": value["summary_calls"],
    }


if __name__ == "__main__":
    main()
