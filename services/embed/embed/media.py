"""Bytes → what the model takes, as the model card says: images as RGB, audio as 16 kHz mono float32, video as
frames at 1 fps (fewer when a video is longer than the frame budget). Audio and video go through ffmpeg."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

SAMPLE_RATE = 16000
FRAME_SIDE = 768            # frames are scaled to fit this; the processor resizes them again to its token budget


class MediaError(Exception):
    """The file couldn't be read as the kind asked for (HTTP 415)."""


@dataclass
class Prepared:
    kind: str
    value: Any
    info: dict[str, Any] = field(default_factory=dict)


@contextmanager
def spooled(data: bytes, tmp_dir: Path) -> Iterator[str]:
    """The bytes as a file: ffmpeg can't seek a pipe, and an mp4 often keeps its index at the end. The file
    sits in the mod's state folder (nothing is written outside the project) and is removed afterwards."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=tmp_dir, prefix="in-") as f:
        f.write(data)
        f.flush()
        yield f.name


def _ffmpeg(args: list[str], timeout: float = 300) -> bytes:
    try:
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", *args], capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise MediaError("ffmpeg isn't installed (dnf install ffmpeg)") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError("ffmpeg took too long") from e
    if r.returncode != 0:
        raise MediaError(f"ffmpeg couldn't decode it: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout


def image(data: bytes) -> Prepared:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError) as e:
        raise MediaError(f"not an image: {e}") from e
    return Prepared("image", im.convert("RGB"), {"width": im.width, "height": im.height})


def audio(data: bytes, max_s: float, tmp_dir: Path) -> Prepared:
    with spooled(data, tmp_dir) as src:
        raw = _ffmpeg(["-i", src, "-t", str(max_s + 1), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                       "-f", "f32le", "pipe:1"])
    a = np.frombuffer(raw, dtype=np.float32)
    if a.size == 0:
        raise MediaError("no audio in the file")
    seconds = a.size / SAMPLE_RATE
    info: dict[str, Any] = {"seconds": round(min(seconds, max_s), 2)}
    if seconds > max_s:
        a, info["truncated"] = a[: int(max_s * SAMPLE_RATE)], True
    return Prepared("audio", {"array": a.copy(), "sampling_rate": SAMPLE_RATE}, info)


def duration(src: str) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", src],
                             capture_output=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        return float(json.loads(out.stdout or b"{}")["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return None


def ppm_frames(raw: bytes) -> list[Image.Image]:
    """Split ffmpeg's `-c:v ppm -f image2pipe` stream into images (each is `P6 w h 255` then w·h·3 bytes)."""
    frames, i = [], 0
    while i < len(raw):
        parts, j = [], i
        while len(parts) < 4:                           # magic, width, height, maxval; whitespace-separated
            while raw[j:j + 1].isspace():
                j += 1
            k = j
            while not raw[k:k + 1].isspace():
                k += 1
            parts.append(raw[j:k])
            j = k
        if parts[0] != b"P6":
            raise MediaError("unexpected frame format from ffmpeg")
        w, h = int(parts[1]), int(parts[2])
        start = j + 1
        frames.append(Image.frombytes("RGB", (w, h), raw[start:start + w * h * 3]))
        i = start + w * h * 3
    return frames


def video(data: bytes, max_frames: int, tmp_dir: Path) -> Prepared:
    """1 fps, as the model card says; a video longer than `max_frames` seconds is sampled evenly instead
    (the processor would drop the extra frames anyway)."""
    scale = f"scale='min({FRAME_SIDE},iw)':'min({FRAME_SIDE},ih)':force_original_aspect_ratio=decrease"
    with spooled(data, tmp_dir) as src:
        secs = duration(src)
        fps = 1.0 if not secs or secs <= max_frames else max_frames / secs
        raw = _ffmpeg(["-i", src, "-an", "-vf", f"fps={fps:.6f},{scale}", "-frames:v", str(max_frames),
                       "-c:v", "ppm", "-f", "image2pipe", "pipe:1"])
    frames = ppm_frames(raw)
    if not frames:
        raise MediaError("no video frames in the file")
    info: dict[str, Any] = {"frames": len(frames), "fps": round(fps, 3)}
    if secs:
        info["seconds"] = round(secs, 2)
    return Prepared("video", frames, info)
