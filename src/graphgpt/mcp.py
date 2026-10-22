from __future__ import annotations

from typing import Any, Literal


async def discover_mcp_tools(
    target: Any,
    *,
    cache_mode: Literal["use", "refresh", "bypass"] = "use",
) -> tuple[Any, ...]:
    """Discover standard LangChain tools through its first-party MCP adapter."""
    try:
        from langchain.mcp import MCPAdapter
    except ImportError as exc:
        raise RuntimeError("Install GraphGPT with the 'mcp' extra") from exc

    async with MCPAdapter(target) as adapter:
        tools = tuple(await adapter.list_tools(cache_mode=cache_mode))
    if not tools:
        raise ValueError("MCP target exposed no tools")
    names = [_tool_name(tool) for tool in tools]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"MCP target exposed duplicate tool names: {duplicates}")
    return tools


def _tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError("MCP adapter returned a tool without a non-empty name")
    if not callable(getattr(tool, "invoke", None)):
        raise ValueError(f"MCP tool '{name}' is not a LangChain-compatible tool")
    return name
