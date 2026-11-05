"""Process-local asynchronous graph tasks; no claim of durable remote scheduling."""

from __future__ import annotations

import asyncio
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.types import Command


@dataclass(frozen=True)
class AsyncTaskIR:
    task_id: str
    parent_thread_id: str
    thread_id: str
    timeout_seconds: float = 60
    resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.task_id, self.parent_thread_id, self.thread_id)):
            raise ValueError("task and thread identities are required")
        if self.parent_thread_id == self.thread_id:
            raise ValueError("child thread must differ from parent thread")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive and finite")
        if any(not r for r in self.resources) or len(set(self.resources)) != len(self.resources):
            raise ValueError("resource names must be non-empty and unique")


TaskStatus = Literal["running", "interrupted", "completed", "cancelled", "failed"]


@dataclass(frozen=True)
class TaskResult:
    spec: AsyncTaskIR
    status: TaskStatus
    output: Any = None
    error: str | None = None


class AsyncTaskRunner:
    """One event loop owns this runner. Results remain available until it is discarded.

    Idempotency is scoped by (parent thread, task id). Named resources and child
    threads are exclusively owned while running. Cancellation is cooperative.
    Interrupted graphs require a checkpointer and can resume within this process.
    """

    def __init__(self) -> None:
        self._results: dict[tuple[str, str], TaskResult] = {}
        self._jobs: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._requests: dict[tuple[str, str], tuple[Any, Any]] = {}
        self._owners: dict[str, tuple[str, str]] = {}

    def start(self, spec: AsyncTaskIR, graph: Any, payload: Any) -> TaskResult:
        key = (spec.parent_thread_id, spec.task_id)
        if key in self._results:
            previous_graph, previous_payload = self._requests[key]
            if (
                self._results[key].spec != spec
                or previous_graph is not graph
                or previous_payload != payload
            ):
                raise ValueError("idempotency key was reused for a different task")
            return self.status(*key)
        self._launch(spec, graph, deepcopy(payload))
        self._requests[key] = (graph, deepcopy(payload))
        return self.status(*key)

    def status(self, parent_thread_id: str, task_id: str) -> TaskResult:
        return deepcopy(self._results[parent_thread_id, task_id])

    async def result(self, parent_thread_id: str, task_id: str) -> TaskResult:
        await asyncio.shield(self._jobs[parent_thread_id, task_id])
        return self.status(parent_thread_id, task_id)

    async def cancel(self, parent_thread_id: str, task_id: str) -> TaskResult:
        key = (parent_thread_id, task_id)
        job = self._jobs[key]
        if not job.done():
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                # Cancellation before the coroutine's first step skips its finally block.
                spec = self._results[key].spec
                self._results[key] = TaskResult(spec, "cancelled")
                self._release(key)
        return self.status(*key)

    def resume(self, parent_thread_id: str, task_id: str, answer: Any) -> TaskResult:
        key = (parent_thread_id, task_id)
        result = self._results[key]
        if result.status != "interrupted":
            raise ValueError("only interrupted tasks may resume")
        self._launch(result.spec, self._requests[key][0], Command(resume=deepcopy(answer)))
        return self.status(*key)

    def _release(self, key: tuple[str, str]) -> None:
        for resource in [r for r, owner in self._owners.items() if owner == key]:
            del self._owners[resource]

    def _launch(self, spec: AsyncTaskIR, graph: Any, payload: Any) -> None:
        loop = asyncio.get_running_loop()
        key = (spec.parent_thread_id, spec.task_id)
        resources = ["thread:" + spec.thread_id, *("resource:" + r for r in spec.resources)]
        if any(resource in self._owners for resource in resources):
            raise ValueError("task thread or resource is already owned by a running task")
        if any(r.spec.thread_id == spec.thread_id and k != key for k, r in self._results.items()):
            raise ValueError("child thread is already associated with another task")
        for resource in resources:
            self._owners[resource] = key
        self._results[key] = TaskResult(spec, "running")

        async def execute() -> None:
            try:
                async with asyncio.timeout(spec.timeout_seconds):
                    output = await graph.ainvoke(
                        payload,
                        config={
                            "configurable": {"thread_id": spec.thread_id},
                            "metadata": {
                                "parent_thread_id": spec.parent_thread_id,
                                "task_id": spec.task_id,
                            },
                        },
                    )
                status: TaskStatus = (
                    "interrupted"
                    if isinstance(output, dict) and output.get("__interrupt__")
                    else "completed"
                )
                self._results[key] = TaskResult(spec, status, deepcopy(output))
            except asyncio.CancelledError:
                self._results[key] = TaskResult(spec, "cancelled")
            except Exception as exc:
                self._results[key] = TaskResult(spec, "failed", error=type(exc).__name__)
            finally:
                self._release(key)

        self._jobs[key] = loop.create_task(execute(), name=spec.task_id)
