# Universal workflow converter

`graphgpt.dev/universal/v1alpha1` is GraphGPT's conversion boundary. It models six concerns without
assuming that every source is an executable graph:

- JSON Schema input and output interfaces;
- procedural instructions;
- tools, prompts, resources, and other capabilities;
- nodes, edges, conditions, and external bindings;
- source-specific extensions required for round trips;
- conversion notices and semantic fidelity.

## Fidelity

| Level | Meaning |
|---|---|
| `exact` | The source can be reconstructed from the universal asset. |
| `adapted` | Semantics remain available through a bridge, binding, or external runtime. |
| `lossy` | At least one behavior cannot be represented and is reported explicitly. |
| `unsupported` | The requested conversion cannot produce a meaningful artifact. |

`--fail-on-lossy` exits with status 2 before writing files when the final level is `lossy` or
`unsupported`. All successful writes include `conversion-report.json`.

## Built-in formats

| Format | Import | Export contract |
|---|---|---|
| `universal` | Versioned universal JSON | Versioned universal JSON |
| `graphgpt` | Validated YAML Workflow | Valid GraphGPT YAML; foreign actions become explicit `registry:` bindings |
| `mcp` | JSON snapshot containing tools/prompts/resources | MCP capability snapshot; workflows become one endpoint-backed tool |
| `skill` | `SKILL.md` or Skill directory | Agent Skills `SKILL.md`; text resources round-trip |
| `langgraph` | `get_graph().to_json()` topology | LangGraph-compatible topology JSON with binding metadata |
| `dify` | Dify application DSL YAML | Existing DSL round-trip, or endpoint-backed Dify Custom Tool OpenAPI |
| `n8n` | n8n workflow JSON | Existing JSON round-trip, or endpoint-backed callable sub-workflow |

These formats have different control models. MCP defines model-controlled tools, user-controlled
prompts, and application-controlled resources; it does not define an arbitrary workflow file.
Agent Skills are instructions and optional bundled resources, not an execution engine. LangGraph
graph JSON does not contain Python callable bodies. Dify contains provider-specific node payloads.
GraphGPT therefore preserves raw vendor extensions where safe and reports all adaptations instead
of claiming universal lossless translation.

Binary, symlinked, individual files over 1 MB, or Skill text bundles over 5 MB are not embedded in
Universal IR. Their relative paths are recorded and the conversion becomes `lossy`. This prevents a
conversion command from following links or silently embedding unbounded data.

## Examples

```bash
# Dify DSL to inspectable universal JSON
graphgpt convert app.yml --to universal --output build/universal

# GraphGPT workflow as an MCP tool contract
graphgpt convert workflow.yaml --to mcp \
  --base-url https://agents.example.com --output build/mcp

# Agent Skill to a GraphGPT binding scaffold
graphgpt convert ./my-skill --to graphgpt --output build/graphgpt

# LangGraph topology to Agent Skills, refusing the known semantic loss
graphgpt convert graph.json --to skill --fail-on-lossy --output build/skill
```

## Plugin adapters

A plugin declares `converter` and returns a `ConversionAdapter` for
`plugin:<plugin-name>/<format-name>`. The adapter must:

1. load without executing source code;
2. produce a `UniversalAsset` and import notices;
3. render deterministic relative `ConversionArtifact` paths;
4. report every adaptation or loss with stable codes;
5. never place credentials in generated files.

This allows new framework formats to evolve independently from GraphIR and from GraphGPT's release
cycle.
