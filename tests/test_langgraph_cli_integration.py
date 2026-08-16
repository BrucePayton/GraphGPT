from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from graphgpt.project import initialize_project

LANGGRAPH_CLI = shutil.which("langgraph")


@pytest.mark.integration
@pytest.mark.skipif(LANGGRAPH_CLI is None, reason="install the 'cli' extra")
def test_generated_project_loads_in_langgraph_agent_server(tmp_path: Path) -> None:
    project = tmp_path / "agent"
    initialize_project("branch", project)

    validated = subprocess.run(
        [str(LANGGRAPH_CLI), "validate", "--config", "langgraph.json"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert "is valid" in validated.stdout

    port = _available_port()
    server = subprocess.Popen(
        [
            str(LANGGRAPH_CLI),
            "dev",
            "--config",
            "langgraph.json",
            "--no-browser",
            "--no-reload",
            "--port",
            str(port),
        ],
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                pytest.fail(_server_output(server, "Agent Server exited during startup"))
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ok", timeout=1) as response:
                    assert response.status == 200
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.2)
        else:
            pytest.fail(_server_output(server, "Agent Server did not become healthy"))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _server_output(server: subprocess.Popen[str], message: str) -> str:
    if server.poll() is None:
        return message
    output = server.stdout.read() if server.stdout else ""
    return f"{message}\n{output}"
