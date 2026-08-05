from __future__ import annotations

from graphgpt.domain.ir import EdgeIR, GraphIR, NodeIR, RouteIR, RuntimeIR, StateFieldIR
from graphgpt.dsl.models import WorkflowDocument


def to_ir(document: WorkflowDocument) -> GraphIR:
    spec = document.spec
    fields = tuple(
        StateFieldIR(
            name=name,
            type=item.type,
            required=item.required,
            reducer=item.reducer,
            default=item.default,
        )
        for name, item in sorted(spec.state.fields.items())
    )
    nodes = tuple(
        NodeIR(id=name, use=item.use, config=item.with_, metadata=item.metadata)
        for name, item in sorted(spec.nodes.items())
    )
    edges = tuple(
        EdgeIR(
            source=item.source,
            target=item.target,
            route=(
                RouteIR(
                    use=item.route.use,
                    targets=tuple(item.route.targets),
                    path_map=item.route.path_map,
                )
                if item.route
                else None
            ),
            kind="conditional" if item.route else "direct",
        )
        for item in spec.edges
    )
    return GraphIR(
        name=document.metadata.name,
        api_version=document.api_version,
        state_type=spec.state.type,
        state_fields=fields,
        nodes=nodes,
        edges=edges,
        runtime=RuntimeIR(
            interrupt_before=tuple(spec.runtime.interrupt_before),
            interrupt_after=tuple(spec.runtime.interrupt_after),
            checkpointer=spec.runtime.checkpointer,
            store=spec.runtime.store,
        ),
        allowed_modules=tuple(spec.security.allowed_modules),
        metadata={"labels": document.metadata.labels},
    )

