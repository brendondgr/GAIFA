"""Media details and previews for outputs (plan 4.1, 4.3). Everything here blocks: callers
run it in a thread. Failures return None and are logged; they never stop indexing.

- **Duration:** WAV via the stdlib `wave` module, anything else (and WAVs `wave` can't
  read, e.g. float PCM) via `ffprobe`.
- **Size:** images via Pillow, videos via `ffprobe`.
- **Previews:** images over 4 MP get a 640 px JPEG, videos a poster frame at 1 s (`ffmpeg`),
  both cached next to the file as `.<name>.preview.jpg`.
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import shutil
import subprocess
import wave
from pathlib import Path

log = logging.getLogger("aihub.outputs")

PREVIEW_PX = 640
PREVIEW_OVER_PX = 4_000_000  # images larger than this (w × h) get a cached preview
PROBE_TIMEOUT_S = 15
POSTER_AT_S = 1.0
EXCERPT_CHARS = 400
EXCERPT_MAX_BYTES = 1024 * 1024


@functools.cache
def tool(name: str) -> str | None:
    return shutil.which(name)


def ffprobe(p: Path) -> dict | None:
    exe = tool("ffprobe")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(p)],
            capture_output=True, timeout=PROBE_TIMEOUT_S, check=False,
        )
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        log.info("ffprobe %s: %s", p.name, e)
        return None


def duration(p: Path, probe: dict | None = None) -> float | None:
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as w:
                if w.getframerate():
                    return round(w.getnframes() / w.getframerate(), 2)
        except (wave.Error, EOFError, OSError):
            pass  # not plain PCM: ask ffprobe
    probe = probe if probe is not None else ffprobe(p)
    try:
        d = float((probe or {}).get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return None
    return round(d, 2) if d >= 0 else None


def video_dims(probe: dict | None) -> tuple[int, int] | None:
    for s in (probe or {}).get("streams", []):
        if s.get("codec_type") == "video" and s.get("width") and s.get("height"):
            return int(s["width"]), int(s["height"])
    return None


def image_dims(p: Path) -> tuple[int, int] | None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(p) as im:
            w, h = im.size
            with contextlib.suppress(Exception):  # rotated photos report their stored size
                if im.getexif().get(0x0112) in (5, 6, 7, 8):
                    w, h = h, w
            return w, h
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as e:
        log.info("image size %s: %s", p.name, e)
        return None


def excerpt(p: Path) -> str | None:
    """The first lines of a text output, for its card."""
    try:
        if p.stat().st_size > EXCERPT_MAX_BYTES:
            return None
        with p.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read(EXCERPT_CHARS + 1)
    except OSError:
        return None
    text = text.strip()
    return (text[:EXCERPT_CHARS] + "…") if len(text) > EXCERPT_CHARS else text or None


def cache_path(main: Path) -> Path:
    return main.with_name(f".{main.name}.preview.jpg")


def needs_cache(kind: str, dims: tuple[int, int] | None) -> bool:
    """Whether the preview is a generated JPEG (else the image itself, or a 3D preview file)."""
    if kind == "video":
        return True
    return kind == "image" and dims is not None and dims[0] * dims[1] > PREVIEW_OVER_PX


def make_preview(src: Path, kind: str) -> Path | None:
    """Write `src`'s cached preview if it is missing or older than `src`. Returns it, or None."""
    out = cache_path(src)
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
    except OSError:
        return None
    tmp = out.with_name(out.name[:-4] + ".part.jpg")
    try:
        ok = _image_preview(src, tmp) if kind == "image" else _poster(src, tmp)
        if not ok or not tmp.exists() or tmp.stat().st_size == 0:
            return None
        os.replace(tmp, out)
        return out
    except Exception as e:  # noqa: BLE001: a bad file must never break indexing
        log.warning("preview for %s failed: %s", src, e)
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _image_preview(src: Path, out: Path) -> bool:
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im.draft("RGB", (PREVIEW_PX * 2, PREVIEW_PX * 2))  # JPEG: decode at a reduced size
        im = ImageOps.exif_transpose(im)
        im.thumbnail((PREVIEW_PX, PREVIEW_PX))
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (19, 25, 38))  # the UI's inset color under transparency
            im = im.convert("RGBA")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        im.save(out, "JPEG", quality=82)
    return True


def _poster(src: Path, out: Path) -> bool:
    exe = tool("ffmpeg")
    if not exe:
        return False
    for at in (POSTER_AT_S, 0.0):  # clips shorter than 1 s: the first frame
        r = subprocess.run(
            [exe, "-v", "error", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1",
             "-vf", f"scale='min({PREVIEW_PX},iw)':-2", "-f", "image2", "-c:v", "mjpeg", str(out)],
            capture_output=True, timeout=60, check=False,
        )
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True
    log.info("ffmpeg poster for %s: %s", src.name, r.stderr.decode(errors="replace").strip()[-300:])
    return False
