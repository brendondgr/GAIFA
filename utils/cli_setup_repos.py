"""`gaifa setup` and the mods that are their own repositories (plan mod-repos 4.3). Standard library only.

A clone made without `--recurse-submodules` has empty `services/relay`, `lcpp`, `tts` and `gen3d`, and
their setup docs are inside them, so setup checks the chosen ones out before it reads the docs (with
`--plan` too: a checkout installs nothing). Asked for nothing in particular, it checks out every
missing one. A checkout that fails (no SSH key, no access to a private repository, offline) leaves
that mod out with git's message and the fix, instead of failing the run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

TIMEOUT_S = 900


def submodules(root: Path) -> list[tuple[str, str, str]]:
    """(id, path, url) for each `services/<id>` submodule in `.gitmodules`."""
    if not (root / ".gitmodules").is_file():
        return []
    r = subprocess.run(["git", "-C", str(root), "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$"],
                       capture_output=True, text=True)
    by: dict[str, dict[str, str]] = {}
    for line in r.stdout.splitlines():
        key, _, value = line.partition(" ")
        name, _, attr = key[len("submodule."):].rpartition(".")
        by.setdefault(name, {})[attr] = value
    return sorted((v["path"].split("/", 1)[1], v["path"], v.get("url", "")) for v in by.values()
                  if v.get("path", "").startswith("services/") and v["path"].count("/") == 1)


def missing(root: Path) -> list[tuple[str, str, str]]:
    """The submodule mods whose folder isn't checked out (no service.toml in it)."""
    return [s for s in submodules(root) if not (root / s[1] / "service.toml").is_file()]


def wanted(targets: list[str], sid: str) -> bool:
    """Whether the targets (mod ids or setup ids such as `tts-kokoro`) ask for this mod; none: all."""
    return not targets or any(t == sid or t.startswith(sid + "-") for t in targets)


def _fix(url: str, error: str) -> str:
    low = error.lower()
    if "permission denied" in low or "publickey" in low or "could not read from remote" in low or "repository not found" in low:
        return f"add an SSH key with access to {url} (ssh -T git@github.com), or leave this mod out"
    if "could not resolve" in low or "network" in low or "timed out" in low:
        return "check the network, then run gaifa setup again"
    return f"git submodule update --init and read git's message; or leave this mod out"


def checkout(root: Path, targets: list[str]) -> dict[str, list[Any]]:
    """Check out the missing submodule mods the targets need: {done: [ids], failed: [{setup, mod, why, url, error, fix}]}."""
    done, failed = [], []
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")}
    for sid, path, url in missing(root):
        if not wanted(targets, sid):
            continue
        try:
            r = subprocess.run(["git", "-C", str(root), "submodule", "update", "--init", "--", path],
                               capture_output=True, text=True, env=env, timeout=TIMEOUT_S)
            ok, error = r.returncode == 0 and (root / path / "service.toml").is_file(), (r.stderr or r.stdout).strip()
        except subprocess.TimeoutExpired:
            ok, error = False, f"no answer within {TIMEOUT_S}s"
        if ok:
            done.append(sid)
            continue
        lines = [x for x in error.splitlines() if x.strip()]
        short = next((x for x in lines if x.lower().startswith(("fatal:", "error:", "git@", "permission"))), lines[-1] if lines else "git failed")
        fix = _fix(url, error)
        failed.append({"setup": sid, "mod": sid, "url": url, "error": short, "fix": fix,
                       "why": f"couldn't check out {url}: {short} (fix: {fix})"})
    return {"done": done, "failed": failed}
