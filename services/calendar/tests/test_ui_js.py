"""Runs the Calendar page's node tests (tests/ui/*.test.mjs) in New York time. Uses `node` from PATH, or the
host's through `flatpak-spawn --host` inside a toolbox; skipped when neither exists (as utils/tests/web)."""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent / "ui"


def node_cmd() -> list[str] | None:
    if shutil.which("node"):
        return ["env", "TZ=America/New_York", "node"]
    if shutil.which("flatpak-spawn"):
        r = subprocess.run(["flatpak-spawn", "--host", "node", "--version"], capture_output=True, timeout=30)
        if r.returncode == 0:
            return ["flatpak-spawn", "--host", "env", "TZ=America/New_York", "node"]
    return None


def test_ui_node_tests():
    cmd = node_cmd()
    if cmd is None:
        pytest.skip("node is not installed")
    files = sorted(str(p) for p in HERE.glob("*.test.mjs"))
    assert files
    r = subprocess.run([*cmd, "--test", *files], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
