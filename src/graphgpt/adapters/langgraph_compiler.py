from __future__ import annotations

import operator
from collections.abc import Hashable
from typing import Annotated, Any, NotRequired, Required, TypedDict, cast

from graphgpt.application.ports import BindingResolver
from graphgpt.domain.ir import GraphIR


class LangGraphCompiler:
    def __init__(self, resolver: BindingResolver):
        self._resolver = resolver

    def compile(self, graph: GraphIR) -> Any:
        from langgraph.graph import END, START, StateGraph

        state_schema = _make_state_schema(graph)
        builder = StateGraph(state_schema)
        for node in graph.nodes:
            builder.add_node(
                node.id,
                self._resolver.resolve_node(node.use, node.config),
                metadata=node.metadata or None,
            )
        names = {"$start": START, "$end": END}
        for edge in graph.edges:
            source = names.get(edge.source, edge.source)
            if edge.target:
                builder.add_edge(source, names.get(edge.target, edge.target))
            elif edge.route:
                path_map = edge.route.path_map or {
                    target: names.get(target, target) for target in edge.route.targets
                }
                path_map = {key: names.get(value, value) for key, value in path_map.items()}
                builder.add_conditional_edges(
                    source,
                    self._resolver.resolve_route(edge.route.use),
                    cast(dict[Hashable, str], path_map),
                )
        checkpointer = (
            self._resolver.resolve_runtime(graph.runtime.checkpointer)
            if graph.runtime.checkpointer and graph.runtime.checkpointer != "server-managed"
            else None
        )
        store = (
            self._resolver.resolve_runtime(graph.runtime.store)
            if graph.runtime.store and graph.runtime.store != "server-managed"
            else None
        )
        return builder.compile(
            checkpointer=checkpointer,
            store=store,
            interrupt_before=list(graph.runtime.interrupt_before),
            interrupt_after=list(graph.runtime.interrupt_after),
            name=graph.name,
        )


def _make_state_schema(graph: GraphIR) -> Any:
    from langgraph.graph.message import add_messages

    types: dict[str, Any] = {
        "any": Any,
        "string": str,
        "str": str,
        "integer": int,
        "int": int,
        "number": float,
        "float": float,
        "boolean": bool,
        "bool": bool,
        "object": dict[str, Any],
        "array": list[Any],
        "messages": list[Any],
    }
    reducers = {"add": operator.add, "messages": add_messages}
    annotations: dict[str, Any] = {}
    if graph.state_type == "messages":
        annotations["messages"] = Annotated[list[Any], add_messages]
    for item in graph.state_fields:
        annotation = types.get(item.type, Any)
        if item.reducer:
            reducer = reducers.get(item.reducer)
            if reducer is None:
                reducer = self_resolver_error(item.reducer)
            annotation = Annotated[annotation, reducer]
        annotations[item.name] = Required[annotation] if item.required else NotRequired[annotation]
    return TypedDict(  # type: ignore[operator]
        f"{graph.name.title().replace('_', '')}State", annotations, total=False
    )


def self_resolver_error(reference: str) -> Any:
    raise ValueError(
        f"unknown reducer '{reference}'; v0.1 supports 'add' and 'messages' built-ins"
    )
