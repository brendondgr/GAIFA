"""One output on disk → its row in the `outputs` table (plan 4.1). Blocking (reads the
sidecar, probes media): callers run it in a thread.

- **Sidecar** (architecture §4.7): `title`, `kind`, `main`, `preview` and `created_ts` steer
  the row; everything else (prompt, model, voice, seed, params, source, …) goes to `meta`.
- **Title:** the sidecar's, else the file or folder name as words, minus a `HHMMSS-` prefix.
- **Kind:** the sidecar's, else from the main file's extension.
- **Main file of a folder:** the sidecar's `main`, else the first model3d > video > image >
  audio file (top level first), else the first file.
- **Created:** the sidecar's `created_ts`; else, inside a date folder, that date with the
  name's `HHMMSS-` time (or the file's time of day); else the main file's mtime.
- **id** = `sha1(path relative to outputs/)[:12]`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, time
from pathlib import Path, PurePosixPath
from typing import Any

from utils.outputs import media
from utils.outputs.entries import KINDS, MAIN_PRIORITY, Found, kind_of, read_sidecar

STEERING = ("title", "kind", "main", "preview", "complete", "created_ts")
HMS_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})[-_]")
PREVIEW_NAMES = ("preview.png", "preview.jpg", "preview.jpeg", "preview.webp")


def output_id(rel: str) -> str:
    return hashlib.sha1(rel.encode()).hexdigest()[:12]


def title_from(name: str, is_dir: bool) -> str:
    stem = name if is_dir or "." not in name[1:] else name.rsplit(".", 1)[0]
    words = re.sub(r"[-_\s]+", " ", HMS_RE.sub("", stem)).strip()
    return words or name


def _inside(base: str, sub: Any) -> str | None:
    """`base/sub` when `sub` is a plain relative path (no `..`, not absolute)."""
    if not isinstance(sub, str) or not sub.strip():
        return None
    p = PurePosixPath(sub.strip())
    if p.is_absolute() or ".." in p.parts:
        return None
    return str(PurePosixPath(base) / p) if base else str(p)


def _main(f: Found, side: dict[str, Any], preview: str | None) -> str | None:
    rels = [r for r, _, _ in f.files]
    if not f.is_dir:
        return rels[0] if rels else None
    want = _inside(f.rel, side.get("main"))
    if want in rels:
        return want
    pool = [r for r in rels if r != preview] or rels
    for k in MAIN_PRIORITY:
        hits = [r for r in pool if kind_of(r) == k]
        if hits:
            return min(hits, key=lambda r: (r.count("/"), r))
    return pool[0] if pool else None


def _preview_file(outputs: Path, f: Found, side: dict[str, Any]) -> str | None:
    """A preview the output brings itself (3D jobs): the sidecar's `preview`, or `preview.png`."""
    rels = {r for r, _, _ in f.files}
    base = f.rel if f.is_dir else str(PurePosixPath(f.rel).parent)
    want = _inside("" if base == "." else base, side.get("preview"))
    if want and (want in rels or (not f.is_dir and (outputs / want).is_file())):
        return want
    if f.is_dir:
        for n in PREVIEW_NAMES:
            if f"{f.rel}/{n}" in rels:
                return f"{f.rel}/{n}"
    return None


def _created(f: Found, side: dict[str, Any], mtime: float) -> float:
    ts = side.get("created_ts")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
        return float(ts)
    if f.day is None:
        return mtime
    m = HMS_RE.match(PurePosixPath(f.rel).name)
    if m and int(m[1]) < 24 and int(m[2]) < 60 and int(m[3]) < 60:
        return datetime.combine(f.day, time(int(m[1]), int(m[2]), int(m[3]))).timestamp()
    local = datetime.fromtimestamp(mtime)
    return mtime if local.date() == f.day else datetime.combine(f.day, local.time()).timestamp()


def _role(f: Found, rel: str, main: str | None, preview: str | None) -> str | None:
    if rel == main:
        return "main"
    if rel == preview:
        return "preview"
    inner = PurePosixPath(rel).relative_to(f.rel).parts
    if len(inner) > 1:  # parts/part_00.glb → "part"
        d = inner[0]
        return d[:-1] if d.endswith("s") and len(d) > 3 else d
    return None


def describe(outputs: Path, f: Found) -> dict[str, Any] | None:
    """The row for `f`, or None if it vanished meanwhile."""
    if not (outputs / f.rel).exists():
        return None
    side = (read_sidecar(outputs / f.sidecar) if f.sidecar else None) or {}
    preview = _preview_file(outputs, f, side)
    main = _main(f, side, preview)
    mtimes = {r: m for r, _, m in f.files}
    kind = side.get("kind") if side.get("kind") in KINDS else (kind_of(main) if main else "other")
    title = side["title"].strip() if isinstance(side.get("title"), str) and side["title"].strip() else title_from(PurePosixPath(f.rel).name, f.is_dir)
    row: dict[str, Any] = {
        "id": output_id(f.rel), "service": f.service, "kind": kind, "title": title[:300], "path": f.rel,
        "is_dir": int(f.is_dir), "main": main, "preview": None, "size_bytes": sum(s for _, s, _ in f.files),
        "created_ts": _created(f, side, mtimes.get(main or "", 0.0) or (outputs / f.rel).stat().st_mtime),
        "duration_s": None, "width": None, "height": None, "sig": f.sig,
    }
    main_kind = kind_of(main) if main else None
    dims = None
    if main and main_kind in ("audio", "video", "image"):
        p = outputs / main
        probe = media.ffprobe(p) if main_kind == "video" or (main_kind == "audio" and p.suffix.lower() != ".wav") else None
        if main_kind in ("audio", "video"):
            row["duration_s"] = media.duration(p, probe)
        dims = media.image_dims(p) if main_kind == "image" else media.video_dims(probe)
        if dims:
            row["width"], row["height"] = dims
    if main and main_kind in ("image", "video") and media.needs_cache(main_kind, dims):
        if main_kind == "image" or media.tool("ffmpeg"):
            row["preview"] = str(PurePosixPath(main).with_name(media.cache_path(Path(main)).name))
    elif main and main_kind == "image":
        row["preview"] = main
    if row["preview"] is None and preview:
        row["preview"] = preview
    meta = {k: v for k, v in side.items() if k not in STEERING}
    if kind == "text" and main and "excerpt" not in meta and not isinstance(meta.get("prompt"), str):
        if (ex := media.excerpt(outputs / main)) is not None:
            meta["excerpt"] = ex
    row["meta"] = json.dumps(meta, ensure_ascii=False, default=str)
    row["files"] = json.dumps([
        {"path": r, "kind": kind_of(r), "size_bytes": s, **({"role": role} if (role := _role(f, r, main, preview)) else {})} if f.is_dir
        else {"path": r, "kind": kind, "size_bytes": s}
        for r, s, _ in f.files
    ])
    prompt = meta.get("prompt") if isinstance(meta.get("prompt"), str) else ""
    row["search"] = " ".join((title, prompt, PurePosixPath(f.rel).name)).lower()
    return row
