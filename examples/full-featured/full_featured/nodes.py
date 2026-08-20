from __future__ import annotations

from collections import defaultdict
from typing import Any

from langgraph.types import Command, interrupt

_attempts: dict[tuple[int, ...], int] = defaultdict(int)
_summary_calls = 0


def worker(state: dict[str, int]) -> dict[str, list[int]]:
    return {"results": [state["item"] ** 2]}


def normalize(state: dict[str, list[int]]) -> dict[str, list[int]]:
    key = tuple(sorted(state["numbers"]))
    _attempts[key] += 1
    if _attempts[key] == 1:
        raise ConnectionError("demonstrate RetryPolicy")
    return {"normalized": list(key)}


def summarize(state: dict[str, list[int]]) -> dict[str, str]:
    global _summary_calls
    _summary_calls += 1
    numbers = state["normalized"]
    return {"summary": f"count={len(numbers)} sum={sum(numbers)}"}


def decide(state: dict[str, str]) -> Command[Any]:
    total = int(state["summary"].rsplit("=", 1)[1])
    return Command(goto="approved" if total >= 20 else "rejected")


def approved(_: dict[str, Any]) -> dict[str, Any]:
    return {"decision": "approved", "audit": ["policy:approved"]}


def rejected(_: dict[str, Any]) -> dict[str, Any]:
    return {"decision": "rejected", "audit": ["policy:rejected"]}


def review(state: dict[str, Any]) -> dict[str, Any]:
    response = interrupt(
        {
            "kind": "human-review",
            "summary": state["summary"],
            "decision": state["decision"],
        }
    )
    return {"audit": [f"human:{response['reviewer']}={response['approved']}"]}


def reset_counters() -> None:
    global _summary_calls
    _attempts.clear()
    _summary_calls = 0


def counters() -> dict[str, Any]:
    return {"attempts": dict(_attempts), "summary_calls": _summary_calls}
