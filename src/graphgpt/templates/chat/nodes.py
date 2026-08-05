from typing import Any


def reply(state: dict[str, Any]) -> dict[str, Any]:
    return {"messages": [{"role": "assistant", "content": "GraphGPT is ready."}]}
