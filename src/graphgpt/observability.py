from __future__ import annotations

from importlib import import_module
from typing import Any, Literal


def callback_for(provider: Literal["langsmith", "langfuse", "none"]) -> Any | None:
    """Create an optional callback without coupling the compiler to an observability vendor."""
    if provider in {"none", "langsmith"}:
        # LangSmith tracing is enabled by its standard environment variables.
        return None
    try:
        callback_handler = import_module("langfuse.langchain").CallbackHandler
    except ImportError as exc:
        raise RuntimeError("Install GraphGPT with the 'langfuse' extra") from exc
    return callback_handler()


def flush_tracing(provider: str) -> None:
    """Drain queued Langfuse observations before a short-lived CLI process exits."""
    if provider == "langfuse":
        import_module("langfuse").get_client().flush()
