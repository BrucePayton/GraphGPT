from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from graphgpt import BindingRegistry
from graphgpt.domain.diagnostics import GraphGPTError


def test_discovers_registers_and_invokes_official_mcp_tool() -> None:
    server = FastMCP("calculator")

    @server.tool
    def add(left: int, right: int) -> int:
        """Add two integers."""
        return left + right

    registry = BindingRegistry(discover_plugins=False)
    references = asyncio.run(registry.add_mcp_tools(server, namespace="math"))
    tool = registry.resolve_tool(references[0])

    assert references == ("registry:math.add",)
    assert tool.name == "add"
    assert tool.metadata["mcp"]["server"]["name"] == "calculator"
    result = asyncio.run(tool.ainvoke({"left": 2, "right": 3}))
    assert result[0]["text"] == "5"


def test_mcp_tool_preserves_input_schema_validation() -> None:
    server = FastMCP("typed")

    @server.tool
    def square(value: int) -> int:
        """Square an integer."""
        return value * value

    registry = BindingRegistry(discover_plugins=False)
    reference = asyncio.run(registry.add_mcp_tools(server))[0]
    tool = registry.resolve_tool(reference)

    result = asyncio.run(tool.ainvoke({"value": "not-an-integer"}))
    assert "validation error" in result[0]["text"]
    assert "valid integer" in result[0]["text"]


def test_mcp_registration_rejects_empty_servers_collisions_and_bad_names() -> None:
    empty = FastMCP("empty")
    registry = BindingRegistry(discover_plugins=False)
    with pytest.raises(ValueError, match="exposed no tools"):
        asyncio.run(registry.add_mcp_tools(empty))

    server = FastMCP("collision")

    @server.tool
    def existing() -> str:
        """Return a value."""
        return "mcp"

    occupied = BindingRegistry({"existing": lambda: "local"}, discover_plugins=False)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        asyncio.run(occupied.add_mcp_tools(server))
    with pytest.raises(ValueError, match="namespace"):
        asyncio.run(registry.add_mcp_tools(server, namespace="bad:name"))


def test_unknown_tool_reference_fails_explicitly() -> None:
    with pytest.raises(GraphGPTError, match="not registered"):
        BindingRegistry(discover_plugins=False).resolve_tool("registry:missing")
