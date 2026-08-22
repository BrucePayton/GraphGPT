from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, SequenceNode  # type: ignore[import-untyped]

from graphgpt.domain.diagnostics import (
    Diagnostic,
    GraphGPTError,
    Severity,
    SourceLocation,
)
from graphgpt.dsl.models import WorkflowDocument


class SafeYamlWorkflowLoader:
    def load(self, path: Path) -> WorkflowDocument:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GraphGPTError(
                [
                    Diagnostic(
                        code="GRAPHGPT-IO-001",
                        severity=Severity.ERROR,
                        path="$",
                        message=f"could not read workflow '{path}': {exc.strerror or exc}",
                        hint="Check that the workflow exists and is readable.",
                    )
                ]
            ) from exc
        try:
            data = yaml.safe_load(source)
            root = yaml.compose(source, Loader=yaml.SafeLoader)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            location = (
                SourceLocation(str(path), mark.line + 1, mark.column + 1) if mark else None
            )
            raise GraphGPTError(
                [
                    Diagnostic(
                        code="GRAPHGPT-YAML-001",
                        severity=Severity.ERROR,
                        path="$",
                        location=location,
                        message=str(exc).splitlines()[0],
                        hint="Fix the YAML syntax. Custom Python YAML tags are not supported.",
                    )
                ]
            ) from exc
        if not isinstance(data, dict):
            raise GraphGPTError(
                [
                    Diagnostic(
                        code="GRAPHGPT-SCHEMA-001",
                        severity=Severity.ERROR,
                        path="$",
                        message="workflow root must be a mapping",
                    )
                ]
            )
        locations: dict[str, SourceLocation] = {}
        if root:
            _collect_locations(root, "$", str(path), locations)
        try:
            document = WorkflowDocument.model_validate(data)
            document._source_map = locations
            return document
        except ValidationError as exc:
            diagnostics = []
            for error in exc.errors(include_url=False):
                path_parts = [str(part) for part in error["loc"]]
                dotted = ".".join(path_parts)
                lookup = "$" + "".join(
                    f"[{part}]" if part.isdigit() else f".{part}" for part in path_parts
                )
                diagnostics.append(
                    Diagnostic(
                        code="GRAPHGPT-SCHEMA-001",
                        severity=Severity.ERROR,
                        path=dotted or "$",
                        location=_nearest_location(lookup, locations),
                        message=error["msg"],
                        hint="Check the v1alpha1 JSON Schema with `graphgpt schema`.",
                    )
                )
            raise GraphGPTError(diagnostics) from exc


def _collect_locations(
    node: Node, path: str, filename: str, output: dict[str, SourceLocation]
) -> None:
    output[path] = SourceLocation(filename, node.start_mark.line + 1, node.start_mark.column + 1)
    if isinstance(node, MappingNode):
        for key, value in node.value:
            key_text = str(getattr(key, "value", "?"))
            _collect_locations(value, f"{path}.{key_text}", filename, output)
    elif isinstance(node, SequenceNode):
        for index, value in enumerate(node.value):
            _collect_locations(value, f"{path}[{index}]", filename, output)


def _nearest_location(path: str, locations: dict[str, SourceLocation]) -> SourceLocation | None:
    current = path
    while current:
        if current in locations:
            return locations[current]
        current = current.rsplit(".", 1)[0] if "." in current else ""
    return locations.get("$")
