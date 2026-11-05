# Typed workflows (0.11)

The Python compiler now supports `decision` and versioned `action` nodes alongside
`use` and `subgraph`. Each node declares exactly one. Normalized IR is version 0.5;
existing v1alpha1 YAML remains accepted. Graph content hashes change with this IR
version, so retain the old graph version when querying historical traces.

## Decisions

```yaml
decide:
  decision:
    provider: registry:classifier
    question:
      type: choice
      prompt: Which team should handle this request?
      options: [billing, support]
    outputKey: team
    refusalPolicy: fallback
    fallback: support
```

Declare `team` as a string state field. Predicate questions require a boolean field;
score questions require a number field and finite `min`/`max` bounds (`min < max`).
Choice options must be unique, non-empty strings. A regular registered router may
read the validated result and choose a declared edge.

The provider is an explicitly registered callable or LangChain Runnable. It receives
`{"state": state, "question": question}` and returns a raw bool/string/number, or
`DecisionRefusal(reason)`. Both invoke and ainvoke propagate RunnableConfig.
Changing the provider binding switches implementation without changing the IR.
This contract does not automatically translate OpenAI/Jev SDK response envelopes:
an application adapter must normalize those responses explicitly.

Only explicit refusals trigger the policy. Malformed answers and provider exceptions
fail; fallback does not mask them. `interrupt` requires a checkpointer and validates
the resumed answer against the same question. As with native LangGraph interrupts,
the node/provider may run again on resume; providers must tolerate replay.
Type correctness does not establish the factual correctness of a decision.

## Versioned actions and hooks

Register `ActionDefinition(handler, InputModel, OutputModel)` with
`registry.register_action("approval.review", "1.0", definition)`. Input/output
models are Pydantic BaseModel subclasses using plain state field names. The compiler
checks field presence and top-level JSON types against State Schema. Runtime strict
validation enforces the model's detailed constraints. Exact versions are required;
missing versions, missing hooks and incompatible fields fail during compilation.

```yaml
review:
  action:
    ref: approval.review
    version: "1.0"
    before: [registry:audit_request]
    after: [registry:audit_result]
  writes: [result]
```

Hooks run in declaration order before/after successful execution. They observe deep
copies of validated input/output, their return values are ignored, and their errors
propagate. Hooks must be replay-safe when nodes use retries or checkpoint recovery.
Declare `writes` for fan-out actions as for ordinary nodes. Schema aliases and complex
top-level union/reference types are outside this first action contract.

## Recovery policy

`errorHandler: registry:recover` resolves a native LangGraph node error handler.
Unknown handlers fail compilation. The handler follows native state update and
Command semantics; GraphGPT adds no synthetic recovery edges.

`runtime.deltaSnapshotFrequency` (positive integer, default 100) applies to state
fields with `{type: array, reducer: delta-add}`. It maps to
`DeltaChannel(snapshot_frequency=...)` and does not alter ordinary `add` reducers.
The deterministic delta reducer concatenates batches in runtime order. DeltaChannel
and its persistence representation remain upstream beta APIs.

Tests compare generated and native graphs for parallel errors, nested graph errors,
values/updates/tasks streams and replay after 105 updates at snapshot frequencies
2 and 100. Historical branch updates must not mutate their source checkpoint.

## Local asynchronous tasks

`AsyncTaskIR` and `AsyncTaskRunner` wrap a compiled graph's `ainvoke` API. The task
record requires parent/child thread identities, timeout and optional exclusive
resource names. `start`, `status`, `cancel`, `resume`, and async `result` expose the
lifecycle. `(parent_thread_id, task_id)` is an idempotency key; reusing it for another
graph/input fails. Results retain parent/task association for caller-controlled delivery.

This is a separate Python execution contract, not a new YAML node kind or hosted
Deep Agents adapter. One event loop owns the runner. Records are process-local;
restart recovery, cross-process locks, notifications and durable scheduling are not
implemented. `resume` handles interrupted tasks with a live checkpointer. Cancellation
is cooperative: synchronous code running in worker threads cannot be forcibly stopped.
Resource names protect cooperating tasks only; they are not filesystem sandboxing.

Run the credential-free decision → interrupt → resume → action → async result example:

```bash
uv run python examples/typed-decision/run.py
uv run graphgpt evaluation examples/typed-decision/workflow.yaml
```

## Evaluation

`evaluation_manifest(inspect_workflow(path))` generates deterministic node-level checks.
`LangSmithEvaluationAdapter(client).evaluate(graph_ir, project_name="project", node_id=...)`
iterates SDK `list_runs` results with graph/version/compiler/node metadata filters and
returns records with `run_id`, check and status. It never writes remote feedback.

Execution and typed-output checks have local implementations. Interrupt correctness
and absence of side effects require application evaluators; without one they report
`not_evaluated`, never a fabricated pass. Running traces report `pending` for execution.
The query contract is tested with a stub SDK client; remote queries need credentials
and have not been verified. This uses the Python SDK iterator, not the CLI V2 stream API.

Sources: [LangGraph 1.2.18](https://github.com/langchain-ai/langgraph/releases/tag/1.2.18),
[typed decision interface inspiration](https://github.com/langchain-ai/langchainjs/pull/11930),
[LangSmith trace export](https://docs.langchain.com/langsmith/export-traces).
