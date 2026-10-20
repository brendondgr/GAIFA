"""The preflight the hub asks before deciding a call (plan 27.4)."""

from __future__ import annotations

import pytest

from limits import first_word, remote_git


@pytest.fixture
def proj(client, repo):
    client.post("/v1/folders", json={"path": str(repo), "level": "edit", "allow_bypass": True})
    return repo


def lim(client, tool, origin=None, **args):
    r = client.post("/v1/limits", json={"tool": tool, "arguments": args, "origin": origin or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_reads(client, proj):
    out = lim(client, "read", folder="proj", path="README.md")
    assert out["action"] == "read" and out["level"] == "edit" and out["allow_bypass"] and out["key"] == "proj" and not out.get("refuse")
    assert lim(client, "read", folder="proj", path=".env")["refuse"]["code"] == "secret_file"
    assert not lim(client, "read", {"named": [".env"]}, folder="proj", path=".env").get("refuse")
    assert lim(client, "folders")["action"] == "read"
    assert lim(client, "tree", folder="nope")["refuse"]["code"] == "unknown_folder"


def test_edits_carry_their_diff_and_write_nothing(client, proj):
    before = (proj / "pkg" / "calc.py").read_text()
    out = lim(client, "edit", folder="proj", path="pkg/calc.py", old="a - b", new="a + b")
    assert out["action"] == "edit" and "+    return a + b" in out["preview"]["diff"]
    assert (proj / "pkg" / "calc.py").read_text() == before
    assert lim(client, "delete", folder="proj", path="README.md")["action"] == "delete"
    c = lim(client, "git_commit", folder="proj", message="m")
    assert c["refuse"]["code"] == "nothing_to_commit"
    (proj / "x.txt").write_text("x")
    c = lim(client, "git_commit", folder="proj", message="m")
    assert c["action"] == "commit" and c["once"] and c["preview"]["summary"] == "commit in proj: m"
    assert lim(client, "edit", folder="proj", path="pkg/calc.py", old="nope", new="x")["refuse"]["code"] == "old_not_found"
    assert lim(client, "write", folder="proj", path=".git/config", content="x")["refuse"]["code"] == "git_dir"


def test_levels_refuse(client, proj):
    client.patch("/v1/folders/proj", json={"level": "read"})
    out = lim(client, "edit", folder="proj", path="pkg/calc.py", old="a - b", new="a + b")
    assert out["refuse"]["code"] == "level" and out["allow_bypass"] is False
    assert lim(client, "run", folder="proj", command="pytest")["refuse"]["code"] == "level"
    client.patch("/v1/folders/proj", json={"level": "run"})
    assert not lim(client, "run", folder="proj", command="pytest").get("refuse")
    assert lim(client, "run", folder="proj", command="pip install six", network=True)["refuse"]["code"] == "level"
    client.patch("/v1/folders/proj", json={"level": "run_net"})
    assert lim(client, "run", folder="proj", command="pip install six", network=True)["action"] == "network"


def test_runs(client, proj):
    client.patch("/v1/folders/proj", json={"level": "run_net"})
    out = lim(client, "run", folder="proj", command="uv run pytest -q")
    assert out["action"] == "command" and out["key"] == "proj pytest" and not out["once"]
    assert out["preview"] == {"command": "uv run pytest -q", "where": "sandbox", "network": False, "cwd": str(proj)}
    host = lim(client, "run", folder="proj", command="make", where="host")
    assert host["action"] == "host" and host["once"] and "your machine" in host["preview"]["note"]
    push = lim(client, "run", folder="proj", command="git add -A && git push origin main", network=True)
    assert push["action"] == "remote" and push["once"]
    for bad in ("sudo ls", "ls && sudo rm x", "echo hi | doas sh"):
        assert lim(client, "run", folder="proj", command=bad)["refuse"]["code"] == "sudo", bad
    assert lim(client, "python", code="print(1)")["key"] == "python"
    assert lim(client, "python", code="print(1)", network=True)["refuse"]["code"] == "level"
    assert lim(client, "python", folder="proj", code="print(1)")["key"] == "proj python"


@pytest.mark.parametrize("cmd,word", [
    ("pytest -q", "pytest"), ("uv run pytest", "pytest"), ("python -m pytest tests", "pytest"), ("python3.12 -m pytest", "pytest"),
    ("FOO=1 env pytest", "pytest"), (".venv/bin/pytest -x", "pytest"), ("npx vitest run", "vitest"), ("npm test", "npm"),
    ("time make -j4 && make test", "make"), ("ls -la", "ls"), ("", ""),
])
def test_first_word(cmd, word):
    assert first_word(cmd) == word


def test_remote_git():
    assert remote_git("git push") == "push" and remote_git("git -C x fetch origin") == "fetch"
    assert remote_git("git status && git log") is None and remote_git("echo git push") is None
