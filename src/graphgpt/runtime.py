from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from graphgpt.domain.ir import GraphIR, StateFieldIR


@dataclass(frozen=True, slots=True)
class StateInput:
    """Untrusted state data supplied to a workflow's first invocation."""

    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """Explicit control input; never inferred from ordinary JSON state."""

    kind: Literal["resume", "continue"]
    value: Any = None

    @classmethod
    def resume(cls, value: Any) -> RuntimeCommand:
        if value is None:
            raise ValueError("resume value cannot be null")
        return cls("resume", value)

    @classmethod
    def continue_thread(cls) -> RuntimeCommand:
        return cls("continue")


def adapt_runtime_input(graph: GraphIR, value: StateInput | RuntimeCommand) -> Any:
    """Validate a public runtime input and produce the native LangGraph payload."""
    if isinstance(value, RuntimeCommand):
        if value.kind == "continue":
            if value.value is not None:
                raise ValueError("continue commands cannot carry a value")
            return None
        if value.kind == "resume":
            if value.value is None:
                raise ValueError("resume value cannot be null")
            from langgraph.types import Command

            return Command(resume=value.value)
        raise ValueError(f"unsupported runtime command: {value.kind}")
    if not isinstance(value, StateInput):
        raise TypeError("runtime input must be StateInput or RuntimeCommand")
    _validate_state(graph, value.values)
    return dict(value.values)


def _validate_state(graph: GraphIR, values: dict[str, Any]) -> None:
    fields = {item.name: item for item in graph.state_fields}
    if graph.state_type == "messages":
        fields.setdefault("messages", StateFieldIR("messages", "messages"))
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise ValueError(f"state contains undeclared fields: {unknown}")
    missing = sorted(
        item.name for item in fields.values() if item.required and item.name not in values
    )
    if missing:
        raise ValueError(f"state is missing required fields: {missing}")
    for name, item in fields.items():
        if name in values and not _matches_type(values[name], item.type):
            raise ValueError(f"state field '{name}' must be {item.type}")


def _matches_type(value: Any, field_type: str) -> bool:
    if field_type == "any":
        return True
    expected: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "string": str,
        "str": str,
        "integer": int,
        "int": int,
        "number": (int, float),
        "float": (int, float),
        "boolean": bool,
        "bool": bool,
        "object": dict,
        "array": list,
        "messages": list,
    }
    selected = expected.get(field_type)
    if selected is None:
        return False
    if field_type in {"integer", "int", "number", "float"} and isinstance(value, bool):
        return False
    return isinstance(value, selected)
