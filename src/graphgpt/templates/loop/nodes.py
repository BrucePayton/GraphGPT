from typing import Any


def increment(state: dict[str, Any]) -> dict[str, Any]:
    return {"count": state["count"] + 1}


def route(state: dict[str, Any]) -> str:
    return "$end" if state["count"] >= 3 else "increment"
