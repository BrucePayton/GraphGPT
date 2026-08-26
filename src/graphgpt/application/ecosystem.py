from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from graphgpt.domain.ir import GraphIR, StateFieldIR

ECOSYSTEM_API_VERSION = "graphgpt.dev/ecosystem/v1alpha1"


@dataclass(frozen=True, slots=True)
class InvocationContract:
    """Framework-neutral description of a remotely invokable GraphGPT workflow."""

    name: str
    description: str
    endpoint: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    auth: Literal["bearer", "none"] = "bearer"
    api_version: str = ECOSYSTEM_API_VERSION

    @property
    def operation_id(self) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]", "_", self.name)
        return f"invoke_graphgpt_{normalized}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "name": self.name,
            "description": self.description,
            "operation_id": self.operation_id,
            "endpoint": self.endpoint,
            "auth": self.auth,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class EcosystemArtifact:
    """One deterministic, safe-to-write file in an ecosystem export bundle."""

    path: str
    content: str
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        candidate = PurePosixPath(self.path)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.name:
            raise ValueError(f"unsafe ecosystem artifact path: {self.path!r}")


def build_invocation_contract(
    graph: GraphIR,
    *,
    base_url: str,
    auth: Literal["bearer", "none"] = "bearer",
) -> InvocationContract:
    normalized_base = base_url.strip().rstrip("/")
    parsed_base = urlsplit(normalized_base)
    if (
        parsed_base.scheme not in {"http", "https"}
        or not parsed_base.netloc
        or parsed_base.query
        or parsed_base.fragment
    ):
        raise ValueError("base_url must be an absolute HTTP(S) URL without query or fragment")
    state_schema = _state_schema(graph.state_fields)
    description = str(
        graph.metadata.get("description", f"Invoke the GraphGPT workflow '{graph.name}'.")
    )
    return InvocationContract(
        name=graph.name,
        description=description,
        endpoint=f"{normalized_base}/workflows/{graph.name}/invoke",
        input_schema=state_schema,
        output_schema=state_schema,
        auth=auth,
    )


def contract_artifact(contract: InvocationContract) -> EcosystemArtifact:
    return EcosystemArtifact(
        path="graphgpt.contract.json",
        content=json.dumps(contract.to_dict(), indent=2, sort_keys=True) + "\n",
        media_type="application/json",
    )


def _state_schema(fields: tuple[StateFieldIR, ...]) -> dict[str, Any]:
    properties = {field.name: _field_schema(field) for field in fields}
    required = [field.name for field in fields if field.required]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": not bool(fields),
    }
    if required:
        schema["required"] = required
    return schema


def _field_schema(field: StateFieldIR) -> dict[str, Any]:
    aliases = {
        "string": "string",
        "str": "string",
        "integer": "integer",
        "int": "integer",
        "number": "number",
        "float": "number",
        "boolean": "boolean",
        "bool": "boolean",
        "object": "object",
        "array": "array",
        "messages": "array",
    }
    schema: dict[str, Any] = {}
    json_type = aliases.get(field.type)
    if json_type:
        schema["type"] = json_type
    if field.type == "messages":
        schema["items"] = {"type": "object", "additionalProperties": True}
    if field.default is not None:
        schema["default"] = field.default
    return schema
