"""Runs the Node unit tests for web/api.js (utils/tests/web/*.test.mjs).

Uses `node` from PATH, or the host's through `flatpak-spawn --host` when the
tests run inside a toolbox. Skipped when neither exists.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def node_cmd() -> list[str] | None:
    if shutil.which("node"):
        return ["node"]
    if shutil.which("flatpak-spawn"):
        r = subprocess.run(["flatpak-spawn", "--host", "node", "--version"], capture_output=True, timeout=30)
        if r.returncode == 0:
            return ["flatpak-spawn", "--host", "node"]
    return None


def test_api_js_unit_tests():
    cmd = node_cmd()
    if cmd is None:
        pytest.skip("node is not installed")
    files = sorted(str(p) for p in HERE.glob("*.test.mjs"))
    r = subprocess.run([*cmd, "--test", *files], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
