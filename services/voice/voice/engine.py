"""llama.cpp's server as this mod's child process: one model loaded at a time, started on a free loopback port.

`Engine.load()` asks GAIFA for memory, starts `llama-server` with the language model and the projector, and
waits for its health; `ensure()` loads when nothing is loaded and starts it again when the child died.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from . import config
from .config import Settings
from .hub import Hub

log = logging.getLogger(__name__)

ESTIMATE_GB = {"q4_k_m": 4.5, "q8_0": 5.2}
LOAD_TIMEOUT_S = 90.0


class EngineError(Exception):
    def __init__(self, status: int, detail: str, code: str, fix: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.code, self.fix = status, detail, code, fix


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Engine:
    def __init__(self, settings: Settings, hub: Hub, log_dir: Path | None = None) -> None:
        self.settings, self.hub = settings, hub
        self.quant = settings.quant
        self.state = "unloaded"                   # unloaded | loading | ready | failed
        self.error: str | None = None
        self.port: int | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.loaded_at: float | None = None
        self.last_used = time.time()
        self.restarts = 0
        self.sessions = 0
        self.log_path = (log_dir or config.MOD_DIR / "runtime" / "logs") / "llama-server.log"
        self._lock = asyncio.Lock()

    # ---- what is on disk

    def models(self) -> list[dict[str, Any]]:
        s = self.settings
        mm = s.mmproj_path.is_file()
        out = []
        for quant, name in config.QUANTS.items():
            p = s.model_path(quant)
            out.append({"quant": quant, "label": config.QUANT_LABELS[quant], "file": name, "present": p.is_file() and mm,
                        "size_bytes": (p.stat().st_size if p.is_file() else 0) + (s.mmproj_path.stat().st_size if mm else 0),
                        "loaded": self.state == "ready" and self.quant == quant, "default": quant == s.quant})
        return out

    def _check_files(self, quant: str) -> None:
        s = self.settings
        if quant not in config.QUANTS:
            raise EngineError(422, f"unknown size {quant!r}: one of {', '.join(config.QUANTS)}", "invalid_quant")
        missing = [p.name for p in (s.model_path(quant), s.mmproj_path) if not p.is_file()]
        if missing:
            raise EngineError(409, f"the model isn't downloaded: {', '.join(missing)} missing in {s.folder}", "model_missing",
                              fix=f"gaifa setup voice (or download {', '.join(missing)} from huggingface.co/{config.REPO} into {s.folder})")
        if not s.llama_bin.is_file():
            raise EngineError(409, f"llama.cpp isn't installed: no {s.llama_bin}", "engine_missing", fix="gaifa install voice")

    # ---- the child

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def argv(self, quant: str, port: int) -> list[str]:
        s = self.settings
        return [str(s.llama_bin), "-m", str(s.model_path(quant)), "--mmproj", str(s.mmproj_path), "--reasoning", "off",
                "--temp", "0", "--host", "127.0.0.1", "--port", str(port), "-c", str(config.CONTEXT),
                "-np", str(config.SLOTS), "-ngl", str(s.gpu_layers), "--no-webui"]

    async def load(self, quant: str | None = None, make_room: bool = False, own: bool = False) -> dict[str, Any]:
        quant = (quant or self.quant).lower()
        async with self._lock:
            if self.state == "ready" and self.alive() and quant == self.quant:
                self.last_used = time.time()
                return self.status()
            self._check_files(quant)
            if self.sessions and self.alive() and not own:
                raise EngineError(409, "a conversation is open: end it before changing the model", "busy")
            await self._stop()
            self.state, self.error = "loading", None
            try:
                await self.hub.acquire(ESTIMATE_GB[quant], f"{config.MODEL} {config.QUANT_LABELS[quant]}", make_room)
                await self._start(quant)
            except BaseException as e:
                self.state = "failed" if not isinstance(e, asyncio.CancelledError) else "unloaded"
                self.error = getattr(e, "detail", None) or str(e)
                await self._stop(keep_state=True)
                raise
            self.quant, self.state, self.loaded_at, self.last_used = quant, "ready", time.time(), time.time()
            return self.status()

    async def _start(self, quant: str) -> None:
        port = free_port()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        lib = str(self.settings.llama_bin.resolve().parent)
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        with self.log_path.open("ab") as out:
            self.proc = await asyncio.create_subprocess_exec(*self.argv(quant, port), stdout=out, stderr=out,
                                                             stdin=asyncio.subprocess.DEVNULL, env=env)
        self.port = port
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        async with httpx.AsyncClient(timeout=2) as c:
            while time.monotonic() < deadline:
                if not self.alive():
                    raise EngineError(500, f"llama.cpp stopped while loading (exit {self.proc.returncode}): {self.log_tail()}",
                                      "engine_failed")
                try:
                    if (await c.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                        log.info("llama-server ready on %s with %s", port, quant)
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.15)
        raise EngineError(504, f"llama.cpp didn't become ready in {LOAD_TIMEOUT_S:.0f} s: {self.log_tail()}", "engine_timeout")

    async def _stop(self, keep_state: bool = False) -> None:
        proc, self.proc, self.port = self.proc, None, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 8)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        if not keep_state:
            self.state, self.loaded_at = "unloaded", None

    async def unload(self) -> dict[str, Any]:
        async with self._lock:
            await self._stop()
            self.error = None
        return self.status()

    async def ensure(self, quant: str | None = None) -> int:
        """The child's port, loading the model (or starting it again after it died) when needed. `quant`: the size
        the one conversation that is opening wants; another size loaded is replaced."""
        if self.state == "ready" and not self.alive():
            log.warning("llama-server died (exit %s); starting it again", self.proc.returncode if self.proc else "?")
            self.restarts += 1
            self.state = "unloaded"
        if self.state != "ready" or (quant and quant != self.quant):
            await self.load(quant, own=True)
        self.last_used = time.time()
        assert self.port
        return self.port

    def touch(self) -> None:
        self.last_used = time.time()

    async def idle_check(self) -> bool:
        """Unload after idle_unload_s with no conversation open; True when it unloaded."""
        s = self.settings.idle_unload_s
        if s > 0 and self.state == "ready" and not self.sessions and time.time() - self.last_used > s:
            log.info("idle for %.0f s: unloading", s)
            await self.unload()
            return True
        return False

    # ---- reporting

    def rss_bytes(self) -> int:
        if not self.alive():
            return 0
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return 0

    def log_tail(self, n: int = 3) -> str:
        try:
            return " | ".join(self.log_path.read_text(errors="replace").strip().splitlines()[-n:])[-600:]
        except OSError:
            return ""

    def status(self) -> dict[str, Any]:
        ready = self.state == "ready" and self.alive()
        return {"state": self.state if ready or self.state != "ready" else "failed", "quant": self.quant,
                "label": f"{config.MODEL} {config.QUANT_LABELS[self.quant]}", "model": config.MODEL,
                "pid": self.proc.pid if self.alive() else None, "port": self.port if ready else None,
                "rss_bytes": self.rss_bytes(), "loaded_at": self.loaded_at, "restarts": self.restarts,
                "error": self.error, "voices": list(config.VOICES)}
