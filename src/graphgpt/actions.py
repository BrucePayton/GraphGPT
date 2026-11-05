"""Exact-version action catalog with typed state contracts and observer hooks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig, RunnableLambda
from pydantic import BaseModel


@dataclass(frozen=True)
class ActionDefinition:
    handler: Any
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]


def make_action_node(
    definition: ActionDefinition,
    before: list[Any],
    after: list[Any],
) -> Any:
    def runnable(value: Any) -> Any:
        return value if hasattr(value, "invoke") else RunnableLambda(value)

    action = runnable(definition.handler)
    before_hooks = [runnable(hook) for hook in before]
    after_hooks = [runnable(hook) for hook in after]

    def prepare(state: dict[str, Any]) -> dict[str, Any]:
        subset = {key: state[key] for key in definition.input_schema.model_fields if key in state}
        return definition.input_schema.model_validate(subset, strict=True).model_dump()

    def finish(result: Any) -> dict[str, Any]:
        if isinstance(result, BaseModel):
            result = result.model_dump()
        if (
            not isinstance(result, dict)
            or set(result) - definition.output_schema.model_fields.keys()
        ):
            raise ValueError("action returned undeclared output fields")
        return definition.output_schema.model_validate(result, strict=True).model_dump()

    def invoke(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        payload = prepare(state)
        for hook in before_hooks:
            hook.invoke(deepcopy(payload), config)
        result = finish(action.invoke(payload, config))
        for hook in after_hooks:
            hook.invoke(deepcopy(result), config)
        return result

    async def ainvoke(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        payload = prepare(state)
        for hook in before_hooks:
            await hook.ainvoke(deepcopy(payload), config)
        result = finish(await action.ainvoke(payload, config))
        for hook in after_hooks:
            await hook.ainvoke(deepcopy(result), config)
        return result

    return RunnableLambda(invoke, afunc=ainvoke)
