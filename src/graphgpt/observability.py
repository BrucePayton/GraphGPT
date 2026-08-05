from __future__ import annotations

from typing import Any, Literal


def callback_for(provider: Literal["langsmith", "langfuse", "none"]) -> Any | None:
    """Create an optional callback without coupling the compiler to an observability vendor."""
    if provider in {"none", "langsmith"}:
        # LangSmith tracing is enabled by its standard environment variables.
        return None
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Install GraphGPT with the 'langfuse' extra") from exc
    return CallbackHandler()
