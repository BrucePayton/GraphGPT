from typing import Any


def double(value: int) -> int:
    return value * 2


def call_tool(state: dict[str, Any]) -> dict[str, Any]:
    return {"result": double(state["value"])}
