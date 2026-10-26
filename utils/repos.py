"""Mods that are their own git repositories (plan mod-repos).

Standard library only: `utils/cli.py` imports it. Every git call runs with `-C <folder>`, no prompts
(`GIT_TERMINAL_PROMPT=0`) and a timeout, and none of them changes a working tree.

- `ignore_gap(root, sid)`: files GAIFA ignores under `services/<sid>/` that the mod's own `.gitignore`
  files don't. Once the folder is a submodule only its own rules apply, so each of these would show
  up as untracked there (a venv, a key, a runtime). An ignored folder is checked as a folder: a rule
  for it or for everything in it (`runtime/`, `runtime/*`) covers it, and a `!` rule inside it isn't
  looked into (the folders can hold 100,000 files).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

GIT_TIMEOUT_S = 30
SKIP_DIRS = {".git", ".venv", "node_modules", "runtime", "__pycache__"}


class GitError(RuntimeError):
    """A git command failed; the message is git's own."""


def git(folder: Path, *args: str, timeout: float = GIT_TIMEOUT_S, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASK_YESNO": "false", "LC_ALL": "C"}
    try:
        r = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)}: no answer within {timeout:.0f}s") from e
    if check and r.returncode:
        raise GitError((r.stderr or r.stdout).strip() or f"git {' '.join(args)} exited {r.returncode}")
    return r


def _own_ignore_files(mod: Path) -> list[Path]:
    """The mod's `.gitignore` files (its top one and nested ones), not those inside venvs or runtimes."""
    found = []
    for dirpath, dirnames, filenames in os.walk(mod):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if ".gitignore" in filenames:
            found.append(Path(dirpath) / ".gitignore")
    return found


def ignore_gap(root: Path, sid: str) -> list[str]:
    """Paths (relative to the mod, directories with a trailing `/`) that GAIFA ignores under
    `services/<sid>/` but the mod's own rules don't. Empty when the mod can stand alone."""
    mod = root / "services" / sid
    listed = git(root, "status", "--ignored", "--porcelain=v1", "--", f"services/{sid}").stdout.splitlines()
    prefix = f"services/{sid}/"
    ignored = [line[3:].strip('"')[len(prefix):] for line in listed if line.startswith("!! ")]
    ignored = [p for p in ignored if p and not p.startswith(".git/")]
    if not ignored:
        return []
    with tempfile.TemporaryDirectory(prefix="gaifa-ignore-") as tmp:
        scratch = Path(tmp)
        git(scratch, "init", "-q")
        for f in _own_ignore_files(mod):
            dest = scratch / f.relative_to(mod)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
        r = subprocess.run(["git", "-C", str(scratch), "-c", "core.excludesFile=/dev/null", "check-ignore", "--no-index",
                            "--stdin", "-z", "-v", "-n"], input="\0".join(ignored) + "\0", capture_output=True,
                           text=True, timeout=GIT_TIMEOUT_S)
        # -v -n -z: source, linenum, pattern, path per entry; no source means no rule matched it, and a
        # `!pattern` match means a rule un-ignores it.
        fields = r.stdout.split("\0")
        return [fields[i + 3] for i in range(0, len(fields) - 3, 4)
                if not fields[i] or fields[i + 2].startswith("!")]
