"""Tool results (plan 13.2): JSON capped for the model, and media turned into output references.

- **Outputs:** any path in a result that lies under `outputs/` (absolute, `<mod>/<date>/…`, or
  `<date>/…` inside the mod's own folder) becomes `{output_id, ref, url, kind, title, summary}`.
  A file inside a folder output (a 3D job) maps to the folder. The index is synced first, so a
  file written a moment ago is found.
- **Binary responses** (audio, images): the mod's saved copy (`X-GAIFA-Output`, or tts's
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
PATH_HEADERS = ("x-gaifa-output", "x-localtts-path")


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


MADE = (("3d", "model3d"), ("mesh", "model3d"), ("video", "video"), ("animate", "video"), ("speak", "audio"),
        ("voice", "audio"), ("speech", "audio"), ("image", "image"), ("background", "image"), ("upscale", "image"))


def made_kind(tool: str) -> str | None:
    """The output kind a generating tool makes, from its name (for dry runs)."""
    low = tool.lower()
    for word, kind in MADE:
        if word in low:
            return kind
    return None


def stand_in(hub: Hub, kind: str, tool: str, args: dict[str, Any], source: dict[str, Any] | None) -> str:
    """A dry run's output in `outputs/eval/<date>/`: an image drawn from the prompt, a hard link
    to `source` (an outputs row; a copy across filesystems), or with no source a small stub (a
    second of silence, a one-triangle GLB, a one-second video). Returns its path relative to
    outputs/. The eval harness deletes it when the run ends."""
    import hashlib
    import shutil

    words = str(args.get("prompt") or args.get("text") or args.get("description") or tool)
    now = time.localtime()
    day = hub.paths.outputs / "eval" / time.strftime("%Y-%m-%d", now)
    day.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")[:40] or "output"
    stem = f"{time.strftime('%H%M%S', now)}-dry-{slug}-{hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:4]}"
    side = {"title": words[:80], "kind": kind, "prompt": words, "dry_run": True, "params": {k: v for k, v in args.items() if k != "prompt"},
            "source": {"service": "eval", "tool": tool}}

    def finish(path: Path) -> str:
        path.with_name(path.name + ".json").write_text(json.dumps(side, indent=1))
        path.with_name(path.name + ".part").rename(path)
        return str(path.relative_to(hub.paths.outputs))

    if source is None and kind in STUBS:
        path = day / f"{stem}.{STUBS[kind]}"
        if _stub(kind, path.with_name(path.name + ".part"), _drawn(words, args)):
            return finish(path)
    if kind == "image" or source is None:
        path = day / f"{stem}.png"
        _drawn(words, args).save(path.with_name(path.name + ".part"), "PNG")
        return finish(path)
    src = hub.paths.outputs / source["path"]
    if source["is_dir"]:
        dst = day / stem
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".*", "output.json"), copy_function=_link)
        meta = {}
        try:
            meta = json.loads((src / "output.json").read_text())
        except (OSError, ValueError):
            pass
        meta.update(side)
        meta["complete"] = True
        (dst / "output.json").write_text(json.dumps(meta, indent=1))
        return str(dst.relative_to(hub.paths.outputs))
    dst = day / f"{stem}{src.suffix}"
    _link(src, dst.with_name(dst.name + ".part"))
    return finish(dst)


STUBS = {"audio": "wav", "model3d": "glb", "video": "mp4"}


def _link(src: Any, dst: Any) -> None:
    """A hard link (a stand-in costs no space), or a copy when the link can't be made."""
    import os
    import shutil

    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _drawn(words: str, args: dict[str, Any]) -> Any:
    """The stand-in picture: the prompt written on a colour from its hash."""
    import hashlib

    from PIL import Image, ImageDraw

    w, h = 1024, 576
    a = str(args.get("aspect") or "")
    if a.startswith(("9:16", "2:3", "3:4")):
        w, h = 576, 1024
    elif a.startswith("1:1"):
        w, h = 768, 768
    hue = int(hashlib.sha1(words.encode()).hexdigest()[:2], 16)
    im = Image.new("RGB", (w, h), (40 + hue // 3, 60 + (hue * 7) % 120, 90 + (hue * 3) % 140))
    d = ImageDraw.Draw(im)
    lines, line = [], ""
    for word in words.split():
        if len(line) + len(word) > 34:
            lines.append(line)
            line = ""
        line += word + " "
    lines.append(line)
    y = h // 2 - 14 * len(lines[:12])
    for ln in lines[:12]:
        d.text((40, y), ln.strip(), fill=(255, 255, 255))
        y += 28
    d.text((40, 30), "DRY RUN (eval stand-in)", fill=(255, 230, 120))
    return im


def _stub(kind: str, out: Path, picture: Any) -> bool:
    """Write a tiny file of `kind` to `out`. False when it can't (no ffmpeg for a video)."""
    import struct
    import wave

    if kind == "audio":
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 16000)
        return True
    if kind == "model3d":
        pos = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
        gltf = {"asset": {"version": "2.0", "generator": "GAIFA dry run"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                "buffers": [{"byteLength": len(pos)}], "bufferViews": [{"buffer": 0, "byteLength": len(pos), "target": 34962}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}]}
        js = json.dumps(gltf).encode()
        js += b" " * (-len(js) % 4)
        body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(pos), 0x004E4942) + pos
        out.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)
        return True
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    png = out.with_name(f".{out.name}.png")        # a dotfile: the index never sees it
    picture.resize((picture.width // 4 * 2, picture.height // 4 * 2)).save(png)
    try:
        r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", "1", "-r", "8",
                            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-f", "mp4", str(out)], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        png.unlink(missing_ok=True)
    return r.returncode == 0 and out.exists()
