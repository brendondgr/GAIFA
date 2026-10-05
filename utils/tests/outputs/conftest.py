"""Fixtures for the outputs index: a fake `outputs/` tree and an `Outputs` on a temp hub.db.

- `Tree.put(rel, data | size, mtime=, sidecar=)` writes a file (and `<file>.json`).
- `Tree.wav / png / mp4` write real media (ffmpeg for video; tests needing it skip without it).
- `Tree.folder(rel, files, complete=)` writes a folder output with `output.json`.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import wave
from datetime import datetime
from pathlib import Path

import pytest

from utils.db import Database
from utils.events import ActivityLog, EventBus
from utils.outputs import Outputs
from utils.paths import Paths

def _host_ffmpeg() -> bool:
    """Inside a toolbox without ffmpeg, the host's (via `flatpak-spawn --host`) can stand in."""
    if not shutil.which("flatpak-spawn"):
        return False
    try:
        return subprocess.run(["flatpak-spawn", "--host", "ffprobe", "-version"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HOST_FFMPEG = not HAVE_FFMPEG and _host_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not (HAVE_FFMPEG or HOST_FFMPEG), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def _ffmpeg_on_path(tmp_path_factory, monkeypatch):
    """Put wrappers for the host's ffmpeg/ffprobe first on PATH when only the host has them."""
    from utils.outputs import media

    if HOST_FFMPEG:
        bin_dir = tmp_path_factory.getbasetemp() / "host-ffmpeg"
        if not bin_dir.exists():
            bin_dir.mkdir()
            for name in ("ffmpeg", "ffprobe"):
                w = bin_dir / name
                w.write_text(f'#!/bin/sh\nexec flatpak-spawn --host {name} "$@"\n')
                w.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    media.tool.cache_clear()
    yield
    media.tool.cache_clear()


def ts(s: str) -> float:
    """Local time "2026-10-04 14:30:12" → unix seconds."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class Tree:
    def __init__(self, outputs: Path) -> None:
        self.dir = outputs

    def put(self, rel: str, data: bytes | str | int = b"x", mtime: float | None = None, sidecar: dict | None = None) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, int):
            data = b"\0" * data
        p.write_bytes(data.encode() if isinstance(data, str) else data)
        if sidecar is not None:
            p.with_name(p.name + ".json").write_text(json.dumps(sidecar))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def wav(self, rel: str, seconds: float = 1.5, rate: int = 8000, **kw) -> Path:
        p = self.put(rel, b"", **kw)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"\0\0" * int(seconds * rate))
        if kw.get("mtime"):
            os.utime(p, (kw["mtime"], kw["mtime"]))
        return p

    def float_wav(self, rel: str, seconds: float = 2.0, rate: int = 8000) -> Path:
        """IEEE-float WAV: the stdlib `wave` module can't read it, ffprobe can."""
        n = int(seconds * rate)
        data = struct.pack(f"<{n}f", *([0.0] * n))
        fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
        body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
        return self.put(rel, b"RIFF" + struct.pack("<I", len(body)) + body)

    def png(self, rel: str, w: int = 64, h: int = 48, **kw) -> Path:
        from PIL import Image

        p = self.put(rel, b"", **kw)
        Image.new("RGB", (w, h), (200, 120, 40)).save(p, "PNG")
        if kw.get("mtime"):
            os.utime(p, (kw["mtime"], kw["mtime"]))
        return p

    def mp4(self, rel: str, seconds: float = 2.0, size: str = "320x240") -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=10",
                        "-pix_fmt", "yuv420p", str(p)], check=True, timeout=60)
        return p

    def folder(self, rel: str, files: dict[str, bytes | int], complete: bool = True, **sidecar) -> Path:
        d = self.dir / rel
        d.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            self.put(f"{rel}/{name}", data)
        (d / "output.json").write_text(json.dumps({"complete": complete, **sidecar}))
        return d


@pytest.fixture
def tree(tmp_path) -> Tree:
    out = tmp_path / "outputs"
    out.mkdir()
    return Tree(out)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "data" / "databases" / "hub.db")
    d.open()
    yield d
    d.close()


@pytest.fixture
async def outs(tmp_path, tree, db, bus):
    o = Outputs(Paths.build(tmp_path), db, bus, ActivityLog(db, bus))
    o.start()
    yield o
    await o.close()


@pytest.fixture
def hub_tree(root) -> Tree:
    """`outputs/` of the hub the `app` / `client` fixtures run."""
    (root / "outputs").mkdir(exist_ok=True)
    return Tree(root / "outputs")


async def index(app) -> None:
    """Index now, instead of waiting for the hub's watcher."""
    await app.state.hub.outputs.sync(publish=False)


def drain(sub) -> list[dict]:
    return [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
