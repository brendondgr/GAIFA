"""Uploads: a file sent to `POST /api/outputs/upload` becomes an ordinary output.

Images, video, audio, text (UTF-8, or UTF-16 with a BOM; anything else is `upload_encoding`) and
documents (plan 24.1). It is written to `{outputs}/uploads/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext>` with a sidecar (the original
name as its title, `source.service = "upload"`), so the index, the Outputs page, Chat's attachments
and every `output:<id>` input (the comfy edit tools) treat it like anything a mod made (§4.7).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .entries import ext_of, kind_of

FOLDER = "uploads"
MAX_BYTES = 64 * 1024 * 1024
ALLOWED = ("image", "video", "audio", "text", "document")  # what Chat and the mods can take as input


class UploadError(ValueError):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _slug(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48].strip("-")
    return s or "upload"


def as_text(data: bytes) -> str | None:
    """`data` as text: UTF-8 (a BOM is dropped), or UTF-16 with a BOM. None for anything else,
    and for text with NUL bytes (a binary that happens to decode)."""
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16")
        else:
            text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def save_upload(outputs: Path, name: str, data: bytes, now: float | None = None) -> str:
    """Write the upload and its sidecar; returns its path relative to `outputs`. Raises UploadError."""
    name = Path(name or "").name
    kind = kind_of(name)
    if kind not in ALLOWED:
        raise UploadError(415, "upload_type", f'"{name or "(no name)"}" isn\'t an image, video, audio, text or document file')
    if not data:
        raise UploadError(400, "upload_empty", f'"{name}" is empty')
    if len(data) > MAX_BYTES:
        raise UploadError(413, "upload_too_large", f'"{name}" is {len(data) / 2**20:.0f} MB; uploads are at most {MAX_BYTES // 2**20} MB')
    if kind == "text" and as_text(data) is None:
        raise UploadError(415, "upload_encoding", f'"{name}" is not a text file (text must be UTF-8, or UTF-16 with a BOM)')
    t = datetime.fromtimestamp(now if now is not None else time.time())
    day = outputs / FOLDER / t.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    ext = "." + ext_of(name) if "." in name else ""
    base = f"{t:%H%M%S}-{_slug(name[: len(name) - len(ext)] if ext else name)}"
    target, n = day / f"{base}{ext}", 1
    while True:   # claim the name by creating its sidecar exclusively: two uploads at once never share one
        side = target.with_name(target.name + ".json")
        if not target.exists():
            try:
                with side.open("x") as f:
                    f.write(json.dumps({"title": name, "kind": kind, "source": {"service": "upload"}}))
                break
            except FileExistsError:
                pass
        n += 1
        target = day / f"{base}-{n}{ext}"
    part = target.with_name(target.name + ".part")
    part.write_bytes(data)
    part.replace(target)
    return target.relative_to(outputs).as_posix()
