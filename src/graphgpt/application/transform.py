from __future__ import annotations

from graphgpt.domain.ir import (
    ActionRefIR,
    ApprovalPolicyIR,
    ApprovalToolPolicyIR,
    CachePolicyIR,
    DecisionIR,
    EdgeIR,
    GraphIR,
    NodeIR,
    RetryPolicyIR,
    RouteIR,
    RuntimeIR,
    StateFieldIR,
    SubgraphIR,
)
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
        NodeIR(
            id=name,
            use=item.use,
            decision=(
                DecisionIR(
                    provider=item.decision.provider,
                    question=item.decision.question.model_dump(),
                    output_key=item.decision.output_key,
                    refusal_policy=item.decision.refusal_policy,
                    fallback=item.decision.fallback,
                )
                if item.decision
                else None
            ),
            action=(
                ActionRefIR(
                    ref=item.action.ref,
                    version=item.action.version,
                    before=tuple(item.action.before),
                    after=tuple(item.action.after),
                )
                if item.action
                else None
            ),
            error_handler=item.error_handler,
            subgraph=(
                SubgraphIR(
                    path=item.subgraph.path,
                    input_map=item.subgraph.input_map,
                    output_map=item.subgraph.output_map,
                    persistence=item.subgraph.persistence,
                )
                if item.subgraph
                else None
            ),
            config=item.with_,
            metadata=item.metadata,
            destinations=tuple(item.destinations),
            writes=tuple(
                dict.fromkeys(
                    [*item.writes, *([item.decision.output_key] if item.decision else [])]
                )
            ),
            retry=(
                RetryPolicyIR(
                    initial_interval=item.retry.initial_interval,
                    backoff_factor=item.retry.backoff_factor,
                    max_interval=item.retry.max_interval,
                    max_attempts=item.retry.max_attempts,
                    jitter=item.retry.jitter,
                )
                if item.retry
                else None
            ),
            cache=CachePolicyIR(ttl=item.cache.ttl) if item.cache else None,
            approval=(
                ApprovalPolicyIR(
                    mode=item.approval.mode,
                    tools={
                        tool_name: ApprovalToolPolicyIR(
                            allowed_decisions=tuple(policy.allowed_decisions),
                            description=policy.description,
                        )
                        for tool_name, policy in item.approval.tools.items()
                    },
                )
                if item.approval
                else None
            ),
        )
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
            kind=item.route.mode if item.route else "direct",
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
            cache=spec.runtime.cache,
            delta_snapshot_frequency=spec.runtime.delta_snapshot_frequency,
        ),
        allowed_modules=tuple(spec.security.allowed_modules),
        metadata={"labels": document.metadata.labels},
        source_map=document.source_map,
    )
