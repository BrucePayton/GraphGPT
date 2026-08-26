from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from graphgpt.application.ecosystem import (
    EcosystemArtifact,
    InvocationContract,
    contract_artifact,
)

BUILTIN_ECOSYSTEM_TARGETS = ("dify", "n8n")


class DifyRenderer:
    """Render an OpenAPI custom-tool definition importable by Dify."""

    target = "dify"

    def render(
        self,
        contract: InvocationContract,
        options: MappingProxyType[str, Any],
    ) -> tuple[EcosystemArtifact, ...]:
        del options
        parsed = urlsplit(contract.endpoint)
        server_url = f"{parsed.scheme}://{parsed.netloc}"
        operation: dict[str, Any] = {
            "operationId": contract.operation_id,
            "summary": contract.description,
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": contract.input_schema}},
            },
            "responses": {
                "200": {
                    "description": "GraphGPT workflow result",
                    "content": {"application/json": {"schema": contract.output_schema}},
                }
            },
        }
        document: dict[str, Any] = {
            "openapi": "3.0.3",
            "info": {
                "title": f"GraphGPT: {contract.name}",
                "version": "1.0.0",
                "description": contract.description,
            },
            "servers": [{"url": server_url}],
            "paths": {parsed.path: {"post": operation}},
        }
        if contract.auth == "bearer":
            operation["security"] = [{"bearerAuth": []}]
            document["components"] = {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}
            }
        readme = (
            "# GraphGPT → Dify\n\n"
            "Import `openapi.json` as a Dify Custom Tool, then configure its "
            f"{'Bearer authentication' if contract.auth == 'bearer' else 'network access'}.\n"
            "The tool is a thin adapter; workflow semantics remain owned by GraphGPT/LangGraph.\n"
        )
        return (
            contract_artifact(contract),
            EcosystemArtifact(
                "openapi.json",
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                "application/vnd.oai.openapi+json;version=3.0",
            ),
            EcosystemArtifact("README.md", readme, "text/markdown"),
        )


class N8nRenderer:
    """Render an importable n8n sub-workflow backed by a GraphGPT endpoint."""

    target = "n8n"

    def render(
        self,
        contract: InvocationContract,
        options: MappingProxyType[str, Any],
    ) -> tuple[EcosystemArtifact, ...]:
        del options
        request_parameters: dict[str, Any] = {
            "method": "POST",
            "url": contract.endpoint,
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "application/json",
            "body": "={{ JSON.stringify($json) }}",
            "options": {},
        }
        if contract.auth == "bearer":
            request_parameters.update(
                {
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                }
            )
        workflow = {
            "name": f"GraphGPT - {contract.name}",
            "nodes": [
                {
                    "parameters": {"inputSource": "passthrough"},
                    "id": "graphgpt-input",
                    "name": "When Executed by Another Workflow",
                    "type": "n8n-nodes-base.executeWorkflowTrigger",
                    "typeVersion": 1.1,
                    "position": [0, 0],
                },
                {
                    "parameters": request_parameters,
                    "id": "graphgpt-invoke",
                    "name": "Invoke GraphGPT",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 4.3,
                    "position": [260, 0],
                },
            ],
            "connections": {
                "When Executed by Another Workflow": {
                    "main": [[{"node": "Invoke GraphGPT", "type": "main", "index": 0}]]
                }
            },
            "settings": {"executionOrder": "v1"},
            "active": False,
            "meta": {
                "templateCredsSetupCompleted": False,
                "graphgptContract": contract.api_version,
            },
            "tags": [],
        }
        auth_instruction = (
            "select an HTTP Header Auth credential containing the Bearer token"
            if contract.auth == "bearer"
            else "confirm that the endpoint is intentionally unauthenticated"
        )
        readme = (
            "# GraphGPT → n8n\n\n"
            f"Import `{contract.name}.workflow.json`, open **Invoke GraphGPT**, and "
            f"{auth_instruction}.\n"
            "Use this sub-workflow from n8n's workflow caller or AI workflow-tool node.\n"
            "The export is inactive by design so credentials can be reviewed before use.\n"
        )
        return (
            contract_artifact(contract),
            EcosystemArtifact(
                f"{contract.name}.workflow.json",
                json.dumps(workflow, indent=2, sort_keys=True) + "\n",
                "application/json",
            ),
            EcosystemArtifact("README.md", readme, "text/markdown"),
        )


def builtin_ecosystem_renderer(target: str) -> DifyRenderer | N8nRenderer:
    if target == "dify":
        return DifyRenderer()
    if target == "n8n":
        return N8nRenderer()
    raise KeyError(target)
