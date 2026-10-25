"""Save an output into a folder (plan 48.4): the chat's Save to… on any output. The file comes from GAIFA
(`GET /api/outputs/{id}` and its file) and goes into a folder of the chat's environment at Edit or above, under the
output's own name (numbered when the name is taken), with a checkpoint so it can be undone. A folder outside the
environment is refused with how to add it: GAIFA writes nowhere else."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx

from editing import Change
from folders import Folders, Refused

MAX_SAVE = 2_000_000_000


def free_name(folder: Path, name: str) -> str:
    """`name`, or `name-2.ext`, `name-3.ext`… when it's taken."""
    if not (folder / name).exists():
        return name
    stem, ext = os.path.splitext(name)
    for i in range(2, 1000):
        cand = f"{stem}-{i}{ext}"
        if not (folder / cand).exists():
            return cand
    raise Refused("name_taken", f"{name} and 998 numbered copies exist", "pick a name", 409)


def clean_name(name: str) -> str:
    n = re.sub(r"[\\/\0]", "-", str(name or "")).strip().lstrip(".")
    return n[:180] or "output"


def plan(folders: Folders, where: str, name: str, data: bytes) -> Change:
    """Where it goes: `where` is a folder of the environment (id, name or path) or a path inside one."""
    try:
        f, sub = folders.get(where), "."
    except Refused as e:
        if e.code != "inside_folder":
            raise Refused("folder_not_allowed", f"{where} isn't one of this chat's folders",
                          "add it to this chat's environment at Edit (the environment menu under the message box), then save again", 403) from None
        fid = next(x for x in folders.list() if os.path.realpath(where).startswith(os.path.realpath(x.path) + os.sep))
        f, sub = fid, os.path.relpath(os.path.realpath(where), os.path.realpath(fid.path))
    folders.need(f, "edit", "saving a file")
    root, _ = folders.resolve(f, sub)
    if not root.is_dir():
        raise Refused("not_a_folder", f"{where} isn't a folder", "", 422)
    if len(data) > MAX_SAVE:
        raise Refused("too_large", "the file is over 2 GB", "", 413)
    rel_name = free_name(root, clean_name(name))
    p, rel = folders.resolve(f, os.path.join(sub, rel_name) if sub != "." else rel_name, write=True)
    return Change("write", f, f"new file {rel} ({len(data)} bytes)\n", [(p, rel, data)], f"saved {rel}")


async def fetch_output(hub: str, oid: str) -> tuple[bytes, str]:
    """The output's file and its name, from GAIFA."""
    async with httpx.AsyncClient(base_url=hub, timeout=120, trust_env=False) as c:
        r = await c.get(f"/api/outputs/{oid}")
        if r.status_code == 404:
            raise Refused("unknown_output", f"no output {oid}", "", 404)
        r.raise_for_status()
        o: dict[str, Any] = r.json()
        f = await c.get(f"/api/outputs/{oid}/file")
        f.raise_for_status()
    path = str(o.get("url") or o.get("path") or "")
    name = Path(str(o.get("path") or "")).name if o.get("path") and "." in Path(str(o["path"])).name else None
    if not name:
        ext = {"image": ".png", "video": ".mp4", "audio": ".wav", "model3d": ".glb", "text": ".txt"}.get(o.get("kind"), "")
        cd = f.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";]+)', cd)
        name = m.group(1) if m else re.sub(r"[^\w.-]+", "-", str(o.get("title") or oid))[:60] + ext
    return f.content, name or path or oid
