"""Write synthetic traces to the isolated local stack and evaluate real observations."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel

from graphgpt import ActionDefinition, BindingRegistry, compile_workflow, inspect_workflow
from graphgpt.evaluation import LangfuseEvaluationAdapter
from graphgpt.tracing import merge_trace_config

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local" / "langfuse"


class Input(BaseModel):
    approved: bool


class Output(BaseModel):
    result: str


async def main() -> None:
    values = dict(line.split("=", 1) for line in (LOCAL / ".env").read_text().splitlines())
    client = Langfuse(
        public_key=values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"],
        secret_key=values["LANGFUSE_INIT_PROJECT_SECRET_KEY"],
        base_url="http://localhost:3300",
    )
    try:
        assert client.auth_check(), "Local Langfuse authentication failed"
        path = ROOT / "examples" / "typed-decision" / "workflow.yaml"
        ir = inspect_workflow(path)
        registry = BindingRegistry(
            {"decision_provider": lambda _: True, "audit": lambda _: None},
            discover_plugins=False,
        )
        registry.register_action(
            "approval.report",
            "1.0",
            ActionDefinition(lambda _: {"result": "approved"}, Input, Output),
        )
        graph = compile_workflow(path, registry=registry)
        start = datetime.now(UTC) - timedelta(seconds=1)
        callback = CallbackHandler(public_key=values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"])
        config = merge_trace_config(
            ir,
            {
                "callbacks": [callback],
                "configurable": {"thread_id": str(uuid4())},
                "metadata": {"deployment_environment": "local", "synthetic": True},
            },
        )
        result = await graph.ainvoke({"request": "synthetic local verification"}, config)
        assert result["result"] == "approved"
        trace_id = callback.last_trace_id
        assert trace_id, "Callback did not produce a trace ID"
        client.flush()
        deadline = time.monotonic() + 120
        records = []
        while time.monotonic() < deadline:
            records = list(
                LangfuseEvaluationAdapter(client).evaluate(
                    ir,
                    from_start_time=start,
                    to_start_time=datetime.now(UTC),
                )
            )
            records = [record for record in records if record["trace_id"] == trace_id]
            passed = {(r["node_id"], r["check"]) for r in records if r["status"] == "passed"}
            if {
                ("decide", "execution_succeeded"),
                ("decide", "typed_decision"),
                ("report", "execution_succeeded"),
            } <= passed:
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError(
                f"Real observations not available/valid within 120 seconds: {records}"
            )
        evidence = {
            "verified_at": datetime.now(UTC).isoformat(),
            "base_url": "http://localhost:3300",
            "result": result,
            "evaluations": records,
            "trace_url": f"http://localhost:3300/project/graphgpt-local/traces/{records[0]['trace_id']}",
        }
        (LOCAL / "verification.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
    finally:
        client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
