"""Browsing folders to add one to an environment (plan 42.4, the user's ask: pick a folder instead of typing its path).

`GET /v1/browse?path=` lists the folders in `path` (the home folder when it's left out) and says which can be added
(`check_folder`: not the home folder or above it). Only the places the agent may ask for (`grant_roots`: the home
folder and mounted drives) can be browsed, and hidden or secret-looking folders (~/.ssh, a `secrets` folder) are
left out, as `grantable` does. It reads folder names only, never files, and changes nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import folders
from folders import Refused, check_folder, inside, is_secret

MAX_DIRS = 400


def _addable(p: Path) -> bool:
    try:
        check_folder(str(p))
        return True
    except Refused:
        return False


def roots() -> list[dict[str, str]]:
    """The places that can be browsed and exist: the home folder, then mounted drives."""
    out, seen = [], set()
    for r in folders.grant_roots():
        if r.is_dir() and str(r) not in seen:
            seen.add(str(r))
            out.append({"name": "Home" if r == Path(os.path.realpath(Path.home())) else str(r), "path": str(r)})
    return out


def browse(path: str | None = None) -> dict[str, Any]:
    """The folders in `path`, each with whether it can be added, plus the way up (none at a root)."""
    raw = os.path.expanduser((path or "~").strip())
    if not raw.startswith("/") or "\0" in raw:
        raise Refused("bad_path", f"{path} isn't a full path", "pick a folder from the list", 422)
    real = Path(os.path.realpath(raw))
    if not real.is_dir():
        raise Refused("not_a_folder", f"{path} isn't a folder", "pick a folder from the list", 404)
    root = next((r for r in folders.grant_roots() if real == r or inside(real, r)), None)
    if root is None:
        raise Refused("not_browsable", f"{real} is outside your home folder and mounted drives", "pick a folder from the list", 403)
    rel = real.relative_to(root)
    if any(p.startswith(".") for p in rel.parts) or is_secret(str(rel)):
        raise Refused("not_browsable", f"{real} is a hidden or secret-looking folder", "pick a folder from the list", 403)
    dirs: list[dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(real), key=lambda e: e.name.lower())
    except OSError as e:
        raise Refused("unreadable", f"{real} can't be read ({e.strerror or e})", "pick another folder", 403) from None
    for e in entries:
        if e.name.startswith(".") or is_secret(e.name):
            continue
        try:
            if not e.is_dir():
                continue
        except OSError:
            continue
        p = Path(e.path)
        dirs.append({"name": e.name, "path": str(p), "addable": _addable(p)})
        if len(dirs) >= MAX_DIRS:
            break
    return {"path": str(real), "name": real.name or str(real), "parent": None if real == root else str(real.parent),
            "addable": _addable(real), "dirs": dirs, "truncated": len(dirs) >= MAX_DIRS, "roots": roots()}
