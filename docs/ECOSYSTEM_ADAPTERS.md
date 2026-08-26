# Agent ecosystem adapter contract

GraphGPT integrates with agent frameworks at the tool boundary. It does not translate Dify or n8n
graphs into LangGraph, and it does not embed their runtimes. A deployment exposes one GraphGPT
workflow through this convention:

```text
POST {base-url}/workflows/{workflow-name}/invoke
Content-Type: application/json
Authorization: Bearer <token>  # default; optional only when explicitly exported with --auth none
```

The request is the workflow state input and the successful JSON response is the resulting state.
The generated `graphgpt.contract.json` freezes that input/output schema and operation ID under
`graphgpt.dev/ecosystem/v1alpha1`. Deployment adapters may be implemented with LangGraph Agent
Server, a serverless function, ASGI, or another runtime; the compiler core does not choose one.

## Built-in targets

### Dify

`--target dify` creates:

- `openapi.json`: import as a Dify Custom Tool;
- `graphgpt.contract.json`: portable source contract;
- `README.md`: bundle-specific setup notes.

Bearer security is represented as an OpenAPI HTTP security scheme. Authentication material is
configured inside Dify and never emitted by GraphGPT.

### n8n

`--target n8n` creates:

- `<workflow>.workflow.json`: an importable sub-workflow using Execute Workflow Trigger and HTTP
  Request;
- `graphgpt.contract.json`: portable source contract;
- `README.md`: bundle-specific setup notes.

The sub-workflow can be called from a normal workflow or selected by n8n's AI workflow-tool node.
It is exported inactive. With the default Bearer mode, select an HTTP Header Auth credential on the
HTTP Request node before activation.

## Third-party targets

Plugins declare `ecosystem` in `PluginManifest.capabilities` and resolve a renderer:

```python
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from graphgpt import EcosystemArtifact, InvocationContract


class MyRenderer:
    target = "my-framework"

    def render(
        self,
        contract: InvocationContract,
        options: MappingProxyType[str, Any],
    ) -> tuple[EcosystemArtifact, ...]:
        return (EcosystemArtifact("contract.txt", contract.endpoint + "\n"),)


class Plugin:
    # manifest includes frozenset({"ecosystem"})
    def resolve(self, capability: str, name: str, config: Mapping[str, Any]) -> Any:
        if capability == "ecosystem" and name == "my-framework":
            return MyRenderer()
        raise KeyError(name)
```

Then export using `--target plugin:my-plugin/my-framework`. Artifact paths must be relative and may
not contain `..`; existing files are never overwritten. Renderers should be deterministic, must not
include credentials, and should leave framework assets inactive when setup is incomplete.
