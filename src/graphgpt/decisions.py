"""Provider-independent typed decisions. Refusals are explicit, never inferred from data."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig, RunnableLambda

from graphgpt.domain.ir import DecisionIR


@dataclass(frozen=True)
class DecisionRefusal:
    reason: str


def validate_answer(decision: DecisionIR, value: Any) -> Any:
    question = decision.question
    kind = question["type"]
    valid = False
    if kind == "predicate":
        valid = type(value) is bool
    elif kind == "choice":
        valid = isinstance(value, str) and value in question["options"]
    elif kind == "score":
        valid = (
            type(value) in (int, float)
            and math.isfinite(value)
            and question["min"] <= value <= question["max"]
        )
    if not valid:
        raise ValueError(f"invalid {kind} decision answer for '{decision.output_key}'")
    return value


def make_decision_node(decision: DecisionIR, provider: Any) -> Any:
    """Provider receives {state, question}; returns a raw value or DecisionRefusal.

    Provider exceptions and malformed answers propagate; only an explicit refusal
    may use fallback/interrupt. Runnable config propagates to both execution modes.
    """
    if decision.refusal_policy == "fallback":
        validate_answer(decision, decision.fallback)
    runnable = provider if hasattr(provider, "invoke") else RunnableLambda(provider)

    def finish(answer: Any) -> dict[str, Any]:
        if isinstance(answer, DecisionRefusal):
            if decision.refusal_policy == "fallback":
                answer = decision.fallback
            elif decision.refusal_policy == "interrupt":
                from langgraph.types import interrupt

                answer = interrupt(
                    {
                        "kind": "decision_refusal",
                        "reason": answer.reason,
                        "output_key": decision.output_key,
                        "question": decision.question,
                    }
                )
            else:
                raise ValueError(f"decision provider refused: {answer.reason}")
        return {decision.output_key: validate_answer(decision, answer)}

    def invoke(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        return finish(
            runnable.invoke({"state": state, "question": deepcopy(decision.question)}, config)
        )

    async def ainvoke(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        return finish(
            await runnable.ainvoke(
                {"state": state, "question": deepcopy(decision.question)}, config
            )
        )

    return RunnableLambda(invoke, afunc=ainvoke)
