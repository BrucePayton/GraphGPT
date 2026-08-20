from __future__ import annotations

from typing import Any, cast

from graphgpt.adapters.langgraph_compiler import LangGraphCompiler
from graphgpt.application.subgraphs import GraphTree
from graphgpt.registry import BindingRegistry


def compile_graph_tree(
    tree: GraphTree,
    *,
    registry: BindingRegistry | None,
    bindings: dict[str, Any] | None,
    root: bool = True,
    persistence: str = "per-invocation",
) -> Any:
    resolver = registry or BindingRegistry(
        bindings,
        allowed_modules=tree.graph.allowed_modules,
        search_path=tree.path.parent,
    )
    actions: dict[str, Any] = {}
    for node in tree.graph.nodes:
        if node.subgraph is None:
            continue
        child = compile_graph_tree(
            tree.children[node.id],
            registry=registry,
            bindings=bindings,
            root=False,
            persistence=node.subgraph.persistence,
        )
        actions[node.id] = _mapped_subgraph(
            child,
            node.subgraph.input_map,
            node.subgraph.output_map,
        )
    compiler = LangGraphCompiler(resolver)
    if root:
        return compiler.compile(tree.graph, node_actions=actions)
    checkpointer = {
        "per-invocation": None,
        "per-thread": True,
        "stateless": False,
    }[persistence]
    return compiler.compile(
        tree.graph,
        node_actions=actions,
        checkpointer_override=checkpointer,
    )


def _mapped_subgraph(
    graph: Any,
    input_map: dict[str, str],
    output_map: dict[str, str],
) -> Any:
    if not input_map and not output_map:
        return graph

    from langchain_core.runnables import RunnableConfig, RunnableLambda

    def invoke(state: Any, config: RunnableConfig) -> dict[str, Any]:
        result = graph.invoke(_map_input(cast(dict[str, Any], state), input_map), config=config)
        return _map_output(result, output_map)

    async def ainvoke(state: Any, config: RunnableConfig) -> dict[str, Any]:
        result = await graph.ainvoke(
            _map_input(cast(dict[str, Any], state), input_map), config=config
        )
        return _map_output(result, output_map)

    return RunnableLambda(invoke, afunc=ainvoke)


def _map_input(state: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {child: state[parent] for parent, child in mapping.items()}


def _map_output(state: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {parent: state[child] for child, parent in mapping.items()}
