from typing import Any


def decide(state: dict[str, Any]) -> dict[str, Any]:
    return {}


def route(state: dict[str, Any]) -> str:
    return "accept" if state.get("approved") else "reject"


def accept(state: dict[str, Any]) -> dict[str, Any]:
    return {"result": "accepted"}


def reject(state: dict[str, Any]) -> dict[str, Any]:
    return {"result": "rejected"}
