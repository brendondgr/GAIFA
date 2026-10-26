"""Throwaway git repositories for the repos tests: a mod's own repository (with a bare "GitHub"),
and a GAIFA-like project that took it in with a `git subtree add`-shaped merge."""

from __future__ import annotations

import subprocess
from pathlib import Path

ENV = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd: Path, *args: str, date: str | None = None) -> str:
    import os
    env = {**os.environ, **ENV, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    if date:
        env |= {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


_tick = [1_760_000_000]


def commit(cwd: Path, msg: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        f = cwd / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    g(cwd, "add", "-A")
    _tick[0] += 60
    g(cwd, "commit", "-qm", msg, date=f"{_tick[0]} +0000")
    return g(cwd, "rev-parse", "HEAD")


def mod_repo(tmp: Path, name: str = "m", branch: str = "main") -> tuple[Path, Path]:
    """A mod's working repository and its bare remote, with two pushed commits."""
    bare = tmp / f"{name}.git"
    g(tmp, "init", "-q", "--bare", "-b", branch, str(bare))
    work = tmp / f"{name}-work"
    g(tmp, "init", "-q", "-b", branch, str(work))
    commit(work, "first", {"app.py": "v1\n", ".gitignore": ".venv/\n"})
    commit(work, "second", {"app.py": "v2\n"})
    g(work, "remote", "add", "origin", str(bare))
    g(work, "push", "-q", "origin", branch)
    return work, bare


def subtree_add(project: Path, sid: str, source: Path, rev: str = "HEAD") -> str:
    """What `git subtree add --prefix services/<sid> <source> <rev>` makes: a merge of the mod's commit."""
    g(project, "fetch", "-q", str(source), rev)
    up = g(project, "rev-parse", "FETCH_HEAD")
    g(project, "merge", "-q", "-s", "ours", "--no-commit", "--allow-unrelated-histories", up)
    g(project, "read-tree", f"--prefix=services/{sid}/", "-u", up)
    _tick[0] += 60
    g(project, "commit", "-qm", f"Add 'services/{sid}/' from commit '{up}'", date=f"{_tick[0]} +0000")
    return g(project, "rev-parse", "HEAD")


def project(tmp: Path) -> Path:
    root = tmp / "gaifa"
    g(tmp, "init", "-q", "-b", "main", str(root))
    commit(root, "hub", {"app.py": "hub\n", ".gitignore": "/services/*/.venv/\n"})
    return root
