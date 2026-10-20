"""A fixture repo in a tmp dir, a fake AIHub root with data/models, and a TestClient for the mod."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small git repo: a package with a failing test, a README, a secret and a big file."""
    r = tmp_path / "proj"
    (r / "pkg").mkdir(parents=True)
    (r / "pkg" / "__init__.py").write_text("")
    (r / "pkg" / "calc.py").write_text("def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_calc.py").write_text("from pkg.calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
                                              "def test_mul():\n    assert mul(2, 3) == 6\n")
    (r / "README.md").write_text("# proj\n\nA tiny calculator. Run the tests with pytest.\n")
    (r / ".env").write_text("TOKEN=hunter2\n")
    (r / ".gitignore").write_text(".env\nnode_modules/\n")
    (r / "node_modules" / "left-pad").mkdir(parents=True)
    (r / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1\n")
    (r / "blob.bin").write_bytes(b"\0\1\2" * 100)
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "first")
    return r


@pytest.fixture
def aihub(tmp_path: Path) -> Path:
    a = tmp_path / "AIHub"
    (a / "data" / "models" / "llm").mkdir(parents=True)
    (a / "utils").mkdir()
    (a / "utils" / "proxy.py").write_text("def proxy():\n    pass\n")
    return a


@pytest.fixture
def client(tmp_path: Path, aihub: Path):
    app = server.create_app(tmp_path / "state", aihub, aihub / "data" / "models", tmp_path / "outputs", "http://127.0.0.1:9")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ctx(client: TestClient):
    return client.app.state.ctx
