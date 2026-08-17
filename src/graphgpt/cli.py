from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from graphgpt import __version__
from graphgpt.api import compile_workflow, inspect_workflow, validate_workflow
from graphgpt.domain.diagnostics import GraphGPTError, Severity
from graphgpt.dsl.models import WorkflowDocument
from graphgpt.observability import callback_for
from graphgpt.project import TEMPLATES, initialize_project, to_mermaid

app = typer.Typer(help="GraphGPT: compile versioned YAML workflows to native LangGraph.")


class OutputFormat(StrEnum):
    HUMAN = "human"
    JSON = "json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """Build, validate, and run native LangGraph applications."""


@app.command()
def validate(
    path: Path,
    output: Annotated[OutputFormat, typer.Option("--output", "-o")] = OutputFormat.HUMAN,
) -> None:
    """Validate schema and graph semantics without importing user code."""
    try:
        diagnostics = validate_workflow(path)
    except GraphGPTError as exc:
        _emit_diagnostics(exc.diagnostics, output)
        raise typer.Exit(1) from exc
    _emit_diagnostics(diagnostics, output)
    if any(item.severity == Severity.ERROR for item in diagnostics):
        raise typer.Exit(1)
    if not diagnostics and output == OutputFormat.HUMAN:
        typer.echo(f"OK: {path}")


@app.command("inspect")
def inspect_command(path: Path) -> None:
    """Print deterministic normalized IR as JSON."""
    try:
        typer.echo(json.dumps(inspect_workflow(path).to_dict(), indent=2, sort_keys=True))
    except GraphGPTError as exc:
        _emit_diagnostics(exc.diagnostics, OutputFormat.HUMAN)
        raise typer.Exit(1) from exc


@app.command()
def run(
    path: Path,
    input: Annotated[str, typer.Option("--input", "-i")] = "{}",
    stream: Annotated[bool, typer.Option("--stream")] = False,
    trace: Annotated[str, typer.Option("--trace")] = "none",
    thread_id: Annotated[str | None, typer.Option("--thread-id")] = None,
) -> None:
    """Compile and invoke a workflow locally."""
    if trace not in {"none", "langsmith", "langfuse"}:
        raise typer.BadParameter("trace must be none, langsmith, or langfuse")
    try:
        payload = json.loads(input)
        graph = compile_workflow(path)
        callback = callback_for(trace)  # type: ignore[arg-type]
        config: dict[str, Any] = {}
        if callback:
            config["callbacks"] = [callback]
        if thread_id:
            config.setdefault("configurable", {})["thread_id"] = thread_id
        if stream:
            for event in graph.stream(payload, config=config or None):
                typer.echo(json.dumps(event, default=str, sort_keys=True))
        else:
            typer.echo(json.dumps(graph.invoke(payload, config=config or None), default=str))
    except (GraphGPTError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def init(
    destination: Path,
    template: Annotated[str, typer.Option("--template", "-t")] = "chat",
) -> None:
    """Create a LangGraph CLI-ready GraphGPT project."""
    try:
        created = initialize_project(template, destination)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created {len(created)} files in {destination}")


@app.command()
def schema(output: Annotated[Path | None, typer.Option("--output", "-o")] = None) -> None:
    """Export the v1alpha1 JSON Schema."""
    rendered = json.dumps(WorkflowDocument.model_json_schema(), indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)


@app.command()
def export(
    path: Path,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    format: Annotated[str, typer.Option("--format", "-f")] = "mermaid",
) -> None:
    """Export a normalized workflow as Mermaid or JSON IR."""
    graph = inspect_workflow(path)
    if format == "mermaid":
        rendered = to_mermaid(graph)
    elif format == "json":
        rendered = json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n"
    else:
        raise typer.BadParameter("format must be mermaid or json")
    if output:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def dev(
    context: typer.Context,
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("langgraph.json"),
) -> None:
    """Delegate development serving to the official LangGraph CLI."""
    executable = shutil.which("langgraph")
    if not executable:
        typer.echo("langgraph CLI not found; install langgraph-cli[inmem]", err=True)
        raise typer.Exit(1)
    config_path = config.expanduser().resolve()
    if not config_path.is_file():
        typer.echo(f"LangGraph config not found: {config}", err=True)
        raise typer.Exit(1)
    result = subprocess.run(
        [executable, "dev", "--config", config_path.name, *context.args],
        cwd=config_path.parent,
        check=False,
    )
    raise typer.Exit(result.returncode)


@app.command()
def doctor() -> None:
    """Report runtime, integrations, and CLI compatibility."""
    typer.echo(f"GraphGPT {__version__}")
    typer.echo(f"Python {sys.version.split()[0]}")
    for package in ("langgraph", "langchain", "langsmith", "langfuse"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "not installed"
        typer.echo(f"{package}: {version}")
    typer.echo(f"langgraph CLI: {shutil.which('langgraph') or 'not installed'}")
    typer.echo("templates: " + ", ".join(TEMPLATES))


def _emit_diagnostics(diagnostics: list[Any], output: OutputFormat) -> None:
    if output == OutputFormat.JSON:
        typer.echo(json.dumps([item.to_dict() for item in diagnostics], indent=2))
    else:
        for item in diagnostics:
            typer.echo(item.render())


if __name__ == "__main__":
    app()
