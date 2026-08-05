from typing import Any


def retrieve(state: dict[str, Any]) -> dict[str, Any]:
    return {"context": ["Replace this with any LangChain Retriever."]}


def generate(state: dict[str, Any]) -> dict[str, Any]:
    return {"answer": f"{state['query']}: {state['context'][0]}"}
