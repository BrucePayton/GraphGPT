# GraphGPT Ecosystem

GraphGPT compiles to native LangGraph objects, so the surrounding LangChain ecosystem remains
available without a second runtime.

## Verified integrations

| Integration | Support | Entry point |
|---|---|---|
| LangGraph 1.x | Core compiler and runtime | `compile_workflow` |
| LangGraph CLI / Agent Server / Studio | Generated `langgraph.json` | `graphgpt dev` |
| LangChain 1.x | Models, agents, tools, Runnable nodes | `graphgpt-builder[langchain]` |
| LangSmith | Standard tracing environment and callbacks | `--trace langsmith` |
| Langfuse 3.x | Optional LangChain callback adapter | `graphgpt-builder[langfuse]` |
| Third-party extensions | Versioned Python entry points | `graphgpt.plugins` |

## Community plugins

No third-party plugin is endorsed yet. This table will list independently maintained packages after
their first compatibility review.

| Package | Capabilities | Maintainer | GraphGPT range | Status |
|---|---|---|---|---|
| _Submit a PR_ | node/route/tool/runtime | — | — | candidate |

Listing does not transfer ownership or imply a security audit. Users must evaluate publishers and
package provenance themselves.

## Submit a plugin

1. Generate a package with `graphgpt plugin init`.
2. Publish source, tests, license, and a PyPI release under an independent repository.
3. Confirm `graphgpt plugin list --output json` reports a healthy manifest.
4. Test the oldest and newest GraphGPT versions in the package's declared range.
5. Open a PR adding one row above with links to source and PyPI.

See the full [plugin author guide](docs/PLUGINS.md).
