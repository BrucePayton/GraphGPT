"""Run from the repository: uv run python examples/typed-decision/run.py."""

import asyncio
from pathlib import Path

from pydantic import BaseModel

from graphgpt import (
    ActionDefinition,
    AsyncTaskIR,
    AsyncTaskRunner,
    BindingRegistry,
    DecisionRefusal,
    compile_workflow,
    evaluation_manifest,
    inspect_workflow,
)


class ReviewInput(BaseModel):
    approved: bool


class ReviewOutput(BaseModel):
    result: str


async def main() -> None:
    workflow = Path(__file__).with_name("workflow.yaml")
    registry = BindingRegistry(
        {
            "decision_provider": lambda _: DecisionRefusal("Human approval required"),
            "audit": lambda state: print("Audit:", state),
        },
        discover_plugins=False,
    )
    registry.register_action(
        "approval.report",
        "1.0",
        ActionDefinition(
            lambda state: {"result": "approved" if state["approved"] else "rejected"},
            ReviewInput,
            ReviewOutput,
        ),
    )
    graph = compile_workflow(workflow, registry=registry)
    tasks = AsyncTaskRunner()
    tasks.start(AsyncTaskIR("review", "parent", "review-thread"), graph, {"request": "release"})
    assert (await tasks.result("parent", "review")).status == "interrupted"
    tasks.resume("parent", "review", True)
    result = await tasks.result("parent", "review")
    assert result.status == "completed" and result.output["result"] == "approved"
    print(result.output)
    print(evaluation_manifest(inspect_workflow(workflow)))


if __name__ == "__main__":
    asyncio.run(main())
