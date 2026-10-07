"""Tool results (plan 13.2): JSON capped for the model, and media turned into output references.

- **Outputs:** any path in a result that lies under `outputs/` (absolute, `<mod>/<date>/…`, or
  `<date>/…` inside the mod's own folder) becomes `{output_id, ref, url, kind, title, summary}`.
  A file inside a folder output (a 3D job) maps to the folder. The index is synced first, so a
  file written a moment ago is found.
- **Binary responses** (audio, images): the mod's saved copy (`X-AIHub-Output`, or tts's
  `X-LocalTTS-Path`) is used; without one, the hub saves the bytes to `outputs/<mod>/<date>/`.
- **Capping:** JSON over 8 KB becomes `{truncated: true, preview, full}`; the full result stays in
  `tool_calls` and `GET /api/tools/calls/{id}/result` pages through it.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from utils.outputs.entries import kind_of

if TYPE_CHECKING:
    from utils.server import Hub

CAP_BYTES = 8000
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/flac": "flac", "audio/ogg": "ogg",
       "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm",
       "model/gltf-binary": "glb"}
PATH_HEADERS = ("x-aihub-output", "x-localtts-path")


def cap(result: Any, call_id: str, limit: int = CAP_BYTES) -> Any:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text.encode()) <= limit:
        return result
    return {"truncated": True, "bytes": len(text.encode()), "preview": text[: limit // 2],
            "full": f"/api/tools/calls/{call_id}/result", "hint": "read the rest with offset/limit on the full result"}


def _strings(obj: Any, out: list[str], depth: int = 0) -> None:
    if depth > 8 or len(out) > 200:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:100]:
            _strings(v, out, depth + 1)


def candidates(hub: Hub, mod: str, obj: Any) -> list[str]:
    """Paths relative to the outputs root that the result mentions."""
    root = hub.paths.outputs.resolve()
    found: list[str] = []
    strings: list[str] = []
    _strings(obj, strings)
    for s in strings:
        s = unquote(s.strip())
        if not s or len(s) > 500 or "\n" in s or s.startswith(("http://", "https://")):
            continue
        rel: str | None = None
        if s.startswith("/api/outputs/"):
            continue
        if s.startswith("/"):
            try:
                rel = str(Path(s).resolve().relative_to(root))
            except (ValueError, OSError):
                rel = None
        else:
            parts = PurePosixPath(s).parts
            if len(parts) >= 2 and parts[0] == mod and DAY.match(parts[1]):
                rel = s
            elif len(parts) >= 2 and DAY.match(parts[0]):
                rel = f"{mod}/{s}"
            elif len(parts) >= 3 and DAY.match(parts[1]) and (root / parts[0]).is_dir():
                rel = s
        if rel and rel not in found and (root / rel).exists():
            found.append(rel)
    return found


async def outputs_for(hub: Hub, rels: list[str]) -> list[dict[str, Any]]:
    """The indexed outputs behind these paths (a file in a folder output → the folder)."""
    if not rels or hub.outputs is None:
        return []
    scopes = []
    for rel in rels:
        parts = PurePosixPath(rel).parts
        scope = "/".join(parts[:2]) if len(parts) >= 2 and DAY.match(parts[1]) else parts[0]
        if scope not in scopes:
            scopes.append(scope)
    for sc in scopes:
        await hub.outputs.sync(sc)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rel in rels:
        p = PurePosixPath(rel)
        chain = [str(p)] + [str(a) for a in p.parents if str(a) not in (".", "")]
        row = None
        for c in chain:
            row = await hub.db.fetchone("SELECT * FROM outputs WHERE path = ?", (c,))
            if row:
                break
        if row and row["id"] not in seen:
            seen.add(row["id"])
            out.append(brief(hub.outputs.view(row)))
    return out


def brief(o: dict[str, Any]) -> dict[str, Any]:
    meta = o.get("meta") or {}
    summary = o["title"]
    if o.get("dims"):
        summary += f" ({o['dims']['w']}×{o['dims']['h']})"
    if o.get("duration_s"):
        summary += f" ({o['duration_s']:.1f} s)"
    out = {"output_id": o["id"], "ref": f"output:{o['id']}", "kind": o["kind"], "title": o["title"],
           "url": o["url"], "preview": o.get("preview"), "summary": summary}
    if meta.get("prompt"):
        out["prompt"] = str(meta["prompt"])[:300]
    return out


def save_bytes(hub: Hub, mod: str, data: bytes, ctype: str, tool: str, meta: dict[str, Any]) -> str:
    """Store a binary result the mod didn't save itself. Returns its path relative to outputs/."""
    ext = EXT.get(ctype.split(";")[0].strip().lower(), "bin")
    now = time.localtime()
    day = hub.paths.outputs / mod / time.strftime("%Y-%m-%d", now)
    day.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", tool.lower()).strip("-") or "output"
    path = day / f"{time.strftime('%H%M%S', now)}-{slug}.{ext}"
    n = 2
    while path.exists():
        path = day / f"{time.strftime('%H%M%S', now)}-{slug}-{n}.{ext}"
        n += 1
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    side = {"title": str(meta.get("prompt") or meta.get("text") or tool)[:80], "kind": kind_of(path.name),
            "source": {"service": mod, "tool": tool}, **{k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}}
    path.with_name(path.name + ".json").write_text(json.dumps(side, indent=1))
    part.rename(path)
    return str(path.relative_to(hub.paths.outputs))


def saved_path(headers: Any) -> str | None:
    for h in PATH_HEADERS:
        v = headers.get(h)
        if v:
            return unquote(v)
    return None
