from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from graphgpt import PluginCapability, PluginManifest


class DemoPlugin:
    manifest = PluginManifest(
        name="demo",
        version="0.1.0",
        capabilities=frozenset({"node", "route"}),
    )

    def resolve(
        self,
        capability: PluginCapability,
        name: str,
        config: Mapping[str, Any],
    ) -> Any:
        if capability == "node" and name == "prepare":
            prefix = str(config.get("prefix", "demo"))
            api_key = str(config["apiKey"])

            def prepare(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
                items = [int(value.strip()) for value in state["request"].split(",")]
                tenant = config.get("metadata", {}).get("tenant", "unknown")
                return {
                    "items": items,
                    "secret_status": "configured" if api_key else "missing",
                    "audit": [f"{prefix}:tenant={tenant}"],
                }

            return prepare
        if capability == "route" and name == "fanout":
            return lambda state: [Send("worker", {"item": item}) for item in state["items"]]
        raise KeyError(f"unsupported demo resource: {capability}/{name}")


plugin = DemoPlugin()
