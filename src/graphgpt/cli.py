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
from graphgpt.application.secrets import redact_secrets
from graphgpt.domain.diagnostics import GraphGPTError, Severity
from graphgpt.dsl.models import WorkflowDocument
from graphgpt.observability import callback_for
from graphgpt.plugin import PLUGIN_API_VERSION, inspect_installed_plugins
from graphgpt.project import TEMPLATES, initialize_plugin, initialize_project, to_mermaid

app = typer.Typer(help="GraphGPT: compile versioned YAML workflows to native LangGraph.")
plugin_app = typer.Typer(help="Create, inspect, and validate GraphGPT plugins.")
app.add_typer(plugin_app, name="plugin")


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
        typer.echo(
            json.dumps(redact_secrets(inspect_workflow(path).to_dict()), indent=2, sort_keys=True)
        )
    except GraphGPTError as exc:
        _emit_diagnostics(exc.diagnostics, OutputFormat.HUMAN)
        raise typer.Exit(1) from exc


@app.command()
def run(
    path: Path,
    input: Annotated[str | None, typer.Option("--input", "-i")] = None,
    stream: Annotated[bool, typer.Option("--stream")] = False,
    trace: Annotated[str, typer.Option("--trace")] = "none",
    thread_id: Annotated[str | None, typer.Option("--thread-id")] = None,
    config: Annotated[
        str,
        typer.Option("--config", help="RunnableConfig JSON with tags, metadata, or configurable."),
    ] = "{}",
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="JSON response for a dynamic interrupt()."),
    ] = None,
    continue_thread: Annotated[
        bool,
        typer.Option("--continue", help="Resume a static interrupt with None input."),
    ] = False,
) -> None:
    """Compile and invoke a workflow locally."""
    if trace not in {"none", "langsmith", "langfuse"}:
        raise typer.BadParameter("trace must be none, langsmith, or langfuse")
    selected_inputs = sum((input is not None, resume is not None, continue_thread))
    if selected_inputs > 1:
        raise typer.BadParameter("--input, --resume, and --continue are mutually exclusive")
    try:
        invocation_config = _json_object(config, "config")
        configurable = invocation_config.setdefault("configurable", {})
        if not isinstance(configurable, dict):
            raise ValueError("config.configurable must be a JSON object")
        if thread_id:
            configurable["thread_id"] = thread_id
        if not configurable:
            invocation_config.pop("configurable")

        if resume is not None:
            from langgraph.types import Command

            resume_value = json.loads(resume)
            if resume_value is None:
                raise ValueError("resume value cannot be null")
            if not configurable.get("thread_id"):
                raise ValueError("--resume requires --thread-id or config.configurable.thread_id")
            payload: Any = Command(resume=resume_value)
        elif continue_thread:
            if not configurable.get("thread_id"):
                raise ValueError("--continue requires --thread-id or config.configurable.thread_id")
            payload = None
        else:
            payload = json.loads(input or "{}")
        graph = compile_workflow(path)
        callback = callback_for(trace)  # type: ignore[arg-type]
        if callback:
            invocation_config["callbacks"] = [callback]
        if stream:
            for event in graph.stream(payload, config=invocation_config or None):
                typer.echo(json.dumps(event, default=str, sort_keys=True))
        else:
            result = graph.invoke(payload, config=invocation_config or None)
            typer.echo(json.dumps(result, default=str))
    except (GraphGPTError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _json_object(value: str, name: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    return parsed


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


@plugin_app.command("list")
def plugin_list(
    output: Annotated[OutputFormat, typer.Option("--output", "-o")] = OutputFormat.HUMAN,
) -> None:
    """Discover and validate installed graphgpt.plugins entry points."""
    inspections = inspect_installed_plugins()
    if output == OutputFormat.JSON:
        typer.echo(json.dumps([item.to_dict() for item in inspections], indent=2))
    elif not inspections:
        typer.echo("No GraphGPT plugins installed.")
    else:
        for item in inspections:
            if item.healthy and item.manifest:
                capabilities = ",".join(sorted(item.manifest.capabilities))
                package = f" ({item.distribution})" if item.distribution else ""
                typer.echo(f"OK {item.name} {item.manifest.version} [{capabilities}]{package}")
            else:
                for diagnostic in item.diagnostics:
                    typer.echo(diagnostic.render())
    if any(not item.healthy for item in inspections):
        raise typer.Exit(1)


@plugin_app.command("init")
def plugin_init(
    destination: Path,
    name: Annotated[str, typer.Option("--name", "-n")],
) -> None:
    """Create an installable community plugin package with tests and entry point."""
    try:
        created = initialize_plugin(name, destination)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created plugin '{name}' with {len(created)} files in {destination}")


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
        rendered = json.dumps(redact_secrets(graph.to_dict()), indent=2, sort_keys=True) + "\n"
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
    typer.echo(f"plugin API: {PLUGIN_API_VERSION}")
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
