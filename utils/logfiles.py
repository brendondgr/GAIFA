"""Logs in `data/logs/` (plan 16.1).

- **Mods:** a shipper follows each mod's output through the backend (the systemd journal, or the
  child process's pipes) and appends it to `data/logs/<id>.log`, one line per log line:
  `2026-10-07T01:02:03.456 err text` (`out`/`err` for stdout/stderr). Files rotate at 10 MB
  and 5 old files are kept (`<id>.log.1` … `.5`). journald keeps its own copy.
- **The hub:** its own log goes to `data/logs/aihub.log`, rotated the same way.

`read(id, n)` gives the last `n` lines back as `LogLine`s (the Logs tab and `aihub logs`).
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.backends.base import LogLine

log = logging.getLogger("aihub.logs")
MAX_BYTES = 10 * 1024 * 1024
KEEP = 5


def fmt(line: LogLine) -> str:
    ts = datetime.fromtimestamp(line["ts"]).isoformat(timespec="milliseconds")
    text = line["text"].replace("\r", "").replace("\n", " ⏎ ")
    return f"{ts} {'err' if line['stream'] == 'stderr' else 'out'} {text}\n"


def parse(raw: str) -> LogLine | None:
    parts = raw.rstrip("\n").split(" ", 2)
    if len(parts) < 2:
        return None
    try:
        ts = datetime.fromisoformat(parts[0]).timestamp()
    except ValueError:
        return {"ts": 0.0, "text": raw.rstrip("\n"), "stream": "stdout"}
    return {"ts": ts, "text": parts[2] if len(parts) > 2 else "", "stream": "stderr" if parts[1] == "err" else "stdout"}


class LogFiles:
    def __init__(self, dir: Path, max_bytes: int = MAX_BYTES, keep: int = KEEP) -> None:
        self.dir, self.max_bytes, self.keep = dir, max_bytes, keep
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.backend: Any = None

    def path(self, sid: str) -> Path:
        return self.dir / f"{sid}.log"

    def append(self, sid: str, lines: list[LogLine]) -> None:
        if not lines:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.path(sid)
        data = "".join(fmt(x) for x in lines).encode()
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        if size and size + len(data) > self.max_bytes:
            self.rotate(sid)
        with p.open("ab") as f:
            f.write(data)

    def rotate(self, sid: str) -> None:
        p = self.path(sid)
        for i in range(self.keep, 0, -1):
            src = p if i == 1 else p.with_name(f"{p.name}.{i - 1}")
            dst = p.with_name(f"{p.name}.{i}")
            if src.exists():
                os.replace(src, dst)

    def read(self, sid: str, n: int) -> list[LogLine]:
        """The last `n` lines, oldest first (across rotated files when needed)."""
        p = self.path(sid)
        files = [p] + [p.with_name(f"{p.name}.{i}") for i in range(1, self.keep + 1)]
        out: list[str] = []
        for f in files:
            if len(out) >= n or not f.exists():
                break
            out = _tail(f, n - len(out)) + out
        return [x for x in map(parse, out[-n:]) if x]

    # ---- shipping ----------------------------------------------------------------------------

    def ship(self, sid: str) -> None:
        """Follow a mod's output into its file (idempotent)."""
        t = self.tasks.get(sid)
        if t is None or t.done():
            self.tasks[sid] = asyncio.create_task(self._follow(sid))

    async def _follow(self, sid: str) -> None:
        delay = 1.0
        while True:
            try:
                buf: list[LogLine] = []
                last = time.monotonic()
                async for line in self.backend.follow(sid):
                    buf.append(line)
                    if len(buf) >= 50 or time.monotonic() - last > 0.5:
                        await asyncio.to_thread(self.append, sid, buf)
                        buf, last = [], time.monotonic()
                    delay = 1.0
                if buf:
                    await asyncio.to_thread(self.append, sid, buf)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep shipping after a hiccup
                log.warning("log shipper for %s: %s", sid, e)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def close(self) -> None:
        for t in self.tasks.values():
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def _tail(p: Path, n: int, block: int = 65536) -> list[str]:
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        data = b""
        while end > 0 and data.count(b"\n") <= n:
            start = max(0, end - block)
            f.seek(start)
            data = f.read(end - start) + data
            end = start
    lines = data.decode(errors="replace").splitlines(keepends=True)
    return lines[-n:]


def hub_handler(dir: Path) -> logging.Handler:
    """The hub's own log file, `data/logs/aihub.log`."""
    dir.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(dir / "aihub.log", maxBytes=MAX_BYTES, backupCount=KEEP, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.setLevel(logging.INFO)
    return h
