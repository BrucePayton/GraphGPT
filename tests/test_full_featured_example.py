import json
import shutil
import subprocess
from pathlib import Path

import pytest

UV = shutil.which("uv")
EXAMPLE = Path(__file__).parents[1] / "examples" / "full-featured"


@pytest.mark.integration
@pytest.mark.skipif(UV is None, reason="uv is required to install the example plugin")
def test_full_featured_example_runs_as_installed_project() -> None:
    result = subprocess.run(
        [str(UV), "run", "--project", str(EXAMPLE), "--locked", "graphgpt-full-example"],
        cwd=EXAMPLE,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert set(report["features"]) >= {
        "plugin",
        "send-fanout",
        "subgraph-mapping",
        "retry",
        "cache",
        "command",
        "interrupt-resume",
        "sync-async-stream",
    }
