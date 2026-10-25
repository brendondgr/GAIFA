"""Importing workflows (plan 11.8): from a file (editor JSON, API JSON, a PNG/WebP/video ComfyUI
made, or a zip holding one of those plus extra files), or from ComfyUI's history. Every import
becomes a draft pack: checked, with a suggested workflow.toml, saved only when the user says so.

What's kept: the editor file as workflow.json when there is one. The exact API graph is kept as
workflow.api.json only when the editor file is missing or doesn't convert, because an API graph
is used as given, so later edits to workflow.json in ComfyUI would be ignored.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .convert import ConvertError, is_api, is_editor, to_api
from .nodes import NodeCatalog
from .packs import API, EDITOR, PACK_ID, Packs, slug

MAX_ZIP_FILES = 500
MAX_ZIP_BYTES = 500 * 1024 * 1024
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov")


class ImportError_(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Found:
    editor: dict | None = None
    api: dict | None = None
    assets: dict[str, bytes] = field(default_factory=dict)     # relative path → bytes
    source: str = ""                                            # what it came from, for the notes


def _json(data: bytes | str) -> Any:
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None


def _take(found: Found, d: Any) -> None:
    if is_editor(d) and found.editor is None:
        found.editor = d
    elif is_api(d) and found.api is None:
        found.api = d
    elif isinstance(d, dict) and is_api(d.get("prompt") or {}):         # {"prompt": {...}} wrappers
        found.api = found.api or d["prompt"]


def png_text(data: bytes) -> dict[str, str]:
    """tEXt / iTXt chunks of a PNG (ComfyUI writes `prompt` and `workflow`)."""
    out: dict[str, str] = {}
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    i = 8
    while i + 8 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        kind, body = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        if kind == b"tEXt" and b"\0" in body:
            k, v = body.split(b"\0", 1)
            out[k.decode("latin-1")] = v.decode("latin-1")
        elif kind == b"iTXt" and b"\0" in body:
            k, rest = body.split(b"\0", 1)
            parts = rest[2:].split(b"\0", 2)
            if len(parts) == 3 and rest[0] == 0:
                out[k.decode("utf-8", "replace")] = parts[2].decode("utf-8", "replace")
        elif kind == b"IEND":
            break
        i += 12 + n
    return out


def webp_text(data: bytes) -> dict[str, str]:
    """ComfyUI's WebP files keep `prompt:{…}` / `workflow:{…}` strings in EXIF tags."""
    out: dict[str, str] = {}
    try:
        from PIL import Image
        exif = Image.open(io.BytesIO(data)).getexif()
    except Exception:  # noqa: BLE001
        return out
    for v in exif.values():
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        if isinstance(v, str) and ":" in v:
            k, rest = v.split(":", 1)
            if k.strip().lower() in ("prompt", "workflow"):
                out[k.strip().lower()] = rest
    return out


def video_text(data: bytes, suffix: str) -> dict[str, str]:
    """Container tags (SaveVideo writes `prompt` and `workflow`; VideoHelperSuite a JSON `comment`)."""
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        try:
            r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", f.name],
                               capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return {}
    tags = ((_json(r.stdout) or {}).get("format") or {}).get("tags") or {}
    out = {k.lower(): v for k, v in tags.items() if k.lower() in ("prompt", "workflow")}
    c = _json(tags.get("comment") or tags.get("COMMENT") or "")
    if isinstance(c, dict):
        for k in ("prompt", "workflow"):
            if k in c and k not in out:
                out[k] = c[k] if isinstance(c[k], str) else json.dumps(c[k])
    return out


def read_file(name: str, data: bytes) -> Found:
    """Whatever ComfyUI workflow this file holds."""
    low = name.lower()
    found = Found(source=name)
    if low.endswith(".zip"):
        return read_zip(name, data)
    if low.endswith(".json"):
        _take(found, _json(data))
    else:
        if low.endswith(".png") or data.startswith(b"\x89PNG"):
            meta = png_text(data)
        elif low.endswith(".webp"):
            meta = webp_text(data)
        elif low.endswith(VIDEO_EXTS):
            meta = video_text(data, Path(low).suffix)
        else:
            raise ImportError_(f"{name}: not a workflow file (JSON, PNG, WebP, MP4/WebM, or a zip of those)")
        _take(found, _json(meta.get("workflow", "")))
        _take(found, _json(meta.get("prompt", "")))
    if found.editor is None and found.api is None:
        raise ImportError_(f"{name}: no ComfyUI workflow in it" + ("" if low.endswith(".json") else " (its metadata was stripped?)"))
    return found


def read_all(name: str, data: bytes) -> list[Found]:
    """Every workflow in a file: one for most files, one per workflow JSON in a zip that holds
    several (Civitai packs often ship variants side by side)."""
    if not name.lower().endswith(".zip"):
        return [read_file(name, data)]
    first = read_zip(name, data)
    z = zipfile.ZipFile(io.BytesIO(data))
    jsons = [i.filename for i in z.infolist() if i.filename.lower().endswith(".json") and not i.filename.startswith("__MACOSX")
             and (is_editor(d := _json(z.read(i))) or is_api(d))]
    if len(jsons) <= 1:
        return [first]
    out = []
    for fn in sorted(jsons):
        f = Found(source=f"{name}:{fn}", assets=first.assets)
        _take(f, _json(z.read(fn)))
        out.append(f)
    return out


def read_zip(name: str, data: bytes) -> Found:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ImportError_(f"{name}: not a valid zip ({e})") from e
    infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")]
    if len(infos) > MAX_ZIP_FILES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
        raise ImportError_(f"{name}: too big to import ({len(infos)} files)")
    for i in infos:
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ImportError_(f"{name}: {i.filename!r} is a symlink; zip the file itself")
        if "\\" in i.filename or "\x00" in i.filename:
            raise ImportError_(f"{name}: {i.filename!r} has a backslash in its name; zip it again with '/' folders")
    found = Found(source=name)
    workflows = []
    for i in infos:
        b = z.read(i)
        base = Path(i.filename).name
        if base.lower().endswith(".json") and (is_editor(d := _json(b)) or is_api(d)):
            workflows.append((i.filename, d))
        elif base.lower().endswith(".png") and png_text(b).get("workflow") and not workflows:
            pass                                     # a picture of the workflow; the JSON is preferred
        else:
            parts = _parts(i.filename)
            if len(parts) > 1 and len({(_parts(x.filename) or [""])[0] for x in infos}) == 1:
                parts = parts[1:]                    # the zip's own top folder
            if parts:
                found.assets["/".join(parts)] = b
    if not workflows:
        for i in infos:
            if i.filename.lower().endswith((".png", ".webp")):
                try:
                    return read_file(i.filename, z.read(i))
                except ImportError_:
                    continue
        raise ImportError_(f"{name}: no ComfyUI workflow inside")
    workflows.sort(key=lambda w: (not is_editor(w[1]), len(w[0])))
    _take(found, workflows[0][1])
    for _, d in workflows[1:]:
        if is_api(d):
            _take(found, d)
    found.source = f"{name}:{workflows[0][0]}"
    return found


def _parts(entry: str) -> list[str]:
    """A zip entry's name as folder parts that stay relative: no root, drive letter, '.' or '..'."""
    return [p for p in PurePosixPath(entry).parts
            if p not in ("", ".", "..") and not p.startswith("/") and not re.fullmatch(r"[A-Za-z]:", p)]


def _asset_path(assets: Path, rel: str) -> Path | None:
    """Where an asset goes: inside the pack's assets/ folder, or None."""
    if not rel or "\\" in rel or "\x00" in rel or rel.startswith("/") or re.search(r"(^|/)\.\.?(/|$)", rel):
        return None
    p = assets / rel
    return p if p.resolve().is_relative_to(assets.resolve()) else None


def unique_id(packs: Packs, base: str) -> str:
    base = slug(base)[:44] or "workflow"
    pid, n = base, 2
    while (packs.root / pid).exists() or packs.get(pid):
        pid, n = f"{base}-{n}", n + 1
    return pid


def create(packs: Packs, catalog: NodeCatalog, found: Found, wid: str | None, name_hint: str) -> str:
    """A draft pack folder from what was found. Returns its id."""
    pid = wid or unique_id(packs, Path(name_hint).stem)
    if not PACK_ID.match(pid):
        raise ImportError_(f"{pid!r}: ids are lowercase letters, digits and -, starting with a letter")
    d = packs.root / pid
    if d.exists():
        raise ImportError_(f"workflows/{pid} already exists")
    keep_api = found.api is not None and found.editor is None
    if found.editor is not None and found.api is not None and catalog:
        try:
            to_api(found.editor, catalog)
        except ConvertError:
            keep_api = True
    d.mkdir(parents=True)
    try:
        if found.editor is not None:
            (d / EDITOR).write_text(json.dumps(found.editor, indent=1))
        if keep_api:
            (d / API).write_text(json.dumps(found.api, indent=1))
        for rel, b in found.assets.items():
            p = _asset_path(d / "assets", rel)
            if p is None:
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
    except OSError:
        shutil.rmtree(d, ignore_errors=True)
        raise
    packs.scan()
    return pid


def history_list(history: dict) -> list[dict]:
    """ComfyUI's history, newest first, as import choices."""
    out = []
    for pid, h in history.items():
        p = h.get("prompt") or []
        graph = p[2] if len(p) > 2 else {}
        extra = p[3] if len(p) > 3 and isinstance(p[3], dict) else {}
        editor = (extra.get("extra_pnginfo") or {}).get("workflow")
        gaifa = (extra.get("extra_pnginfo") or {}).get("gaifa")
        files = [it.get("filename") for o in (h.get("outputs") or {}).values() for v in o.values() if isinstance(v, list)
                 for it in v if isinstance(it, dict) and it.get("type") == "output"]
        types = sorted({n.get("class_type") for n in graph.values() if isinstance(n, dict)})
        out.append({"prompt_id": pid, "number": p[0] if p else 0, "nodes": len(graph), "has_editor": bool(editor),
                    "status": ((h.get("status") or {}).get("status_str")), "files": files[:4],
                    "from_gaifa": (gaifa or {}).get("workflow"), "types": types[:12]})
    return sorted(out, key=lambda x: -(x["number"] or 0))


def from_history(entry: dict) -> Found:
    p = entry.get("prompt") or []
    found = Found(source="ComfyUI history")
    if len(p) > 2 and is_api(p[2]):
        found.api = p[2]
    extra = p[3] if len(p) > 3 and isinstance(p[3], dict) else {}
    ed = (extra.get("extra_pnginfo") or {}).get("workflow")
    if is_editor(ed):
        found.editor = ed
    if found.api is None and found.editor is None:
        raise ImportError_("that history entry has no graph")
    return found
