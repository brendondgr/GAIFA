"""Engine workers: one subprocess per engine, started on demand, stopped when idle.

Stopping the process is the unload. It hands back every byte of GPU memory (weights,
the caching allocator, captured graphs), which an in-process `del model` does not
reliably do.

Under AIHub, each synthesis (and each Whisper one-shot) takes the GPU slot first (plan 31.3,
`gpu_slot.py`): while another mod's work holds the GPU, the request waits, listed in the status
as a `waiting_gpu` job. An engine set to run on the CPU doesn't take it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from collections.abc import AsyncIterator
from pathlib import Path

from .config import ROOT, breeze_env, settings
from .gpu_slot import GpuCancelled, GpuSlot

log = logging.getLogger("localtts.engines")
WORKERS = ROOT / "workers"
DRAIN_TIMEOUT_S = 30.0  # longest we wait for an abandoned request before restarting the worker

# Base environment for every worker; the service's own environment overrides it.
# ROCm nightly torch loads rocprofiler-sdk, which attaches to every process and wraps its GPU
# queues. Its handlers are polled, so an idle worker pins a CPU core and keeps the GPU at 100%
# busy until it unloads. Nothing here uses the profiler; set ROCPROFILER_REGISTER_ENABLED=1 to profile.
WORKER_ENV = {"ROCPROFILER_REGISTER_ENABLED": "0"}


class EngineError(RuntimeError):
    pass


_GPU: GpuSlot | None = None
WAITING: dict[str, dict] = {}        # request id → the status's waiting_gpu job (plan 31.3)


def gpu() -> GpuSlot:
    """AIHub's GPU slot (AIHUB_URL; without it, work runs at once)."""
    global _GPU
    if _GPU is None:
        _GPU = GpuSlot(service="tts", group="tts")
    return _GPU


@contextlib.asynccontextmanager
async def gpu_lease(label: str, request_id: str | None = None, on_gpu: bool = True):
    """Hold the GPU slot for one piece of work; a request that waits is listed in `WAITING` meanwhile."""
    if not on_gpu:
        yield None
        return
    rid = request_id or os.urandom(4).hex()

    def waiting(lease) -> None:
        WAITING[rid] = {"id": f"speech-{rid}", "label": label, "state": "queued", "progress": None,
                        "stage": "waiting_gpu", "ahead": lease.ahead, "eta_s": lease.eta_s}

    try:
        async with gpu().slot(label, on_wait=waiting) as lease:
            WAITING.pop(rid, None)
            yield lease
    except GpuCancelled as exc:
        raise EngineError(f"{label}: cancelled in the GPU queue") from exc
    finally:
        WAITING.pop(rid, None)


class Engine:
    def __init__(self, name: str, python: Path, script: str, env: dict[str, str] | None = None,
                 device_env: str | None = None):
        self.name = name
        self.device_env = device_env      # the variable that can put the engine on the CPU
        self.python = python
        self.script = WORKERS / script
        self.env = env or {}
        self.proc: asyncio.subprocess.Process | None = None
        self.info: dict = {}
        self.state = "unloaded"  # unloaded | loading | ready | busy
        self.last_used = time.monotonic()
        self.loaded_at: float | None = None
        self._lock = asyncio.Lock()        # one request at a time per engine
        self._load_lock = asyncio.Lock()
        self._stale = False  # an abandoned request is still emitting; read it off before the next

    # ---- lifecycle -------------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def ensure_loaded(self) -> None:
        async with self._load_lock:
            if self.alive and self.state != "loading":
                return
            if not self.python.exists():
                raise EngineError(f"{self.name} is not installed (no Python at {self.python}); set it up with: bash engines/setup.sh --plan")
            self.state = "loading"
            log.info("%s: starting worker", self.name)
            env = {**WORKER_ENV, **os.environ, "PYTHONUNBUFFERED": "1", **self.env}
            self.proc = await asyncio.create_subprocess_exec(
                str(self.python), str(self.script),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=None, cwd=str(WORKERS), env=env,
                limit=1 << 20, start_new_session=True,
            )
            try:
                msg = await asyncio.wait_for(self._read_event(), settings.load_timeout_s)
            except Exception:
                await self.unload(reason="failed to load")
                raise
            if msg.get("event") != "ready":
                await self.unload(reason="failed to load")
                raise EngineError(f"{self.name}: failed to load: {msg.get('message', msg)}")
            self.info = {k: v for k, v in msg.items() if k != "event"}
            self.state = "ready"
            self.loaded_at = time.monotonic()
            self.last_used = time.monotonic()
            log.info("%s: ready %s", self.name, self.info)

    async def unload(self, reason: str = "requested") -> bool:
        proc, self.proc, self._stale = self.proc, None, False
        self.state, self.info, self.loaded_at = "unloaded", {}, None
        if proc is None or proc.returncode is not None:
            return False
        log.info("%s: unloading (%s), pid %s", self.name, reason, proc.pid)
        try:
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), 10)
        except (asyncio.TimeoutError, ProcessLookupError, BrokenPipeError, ConnectionResetError):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        return True

    async def maybe_idle_unload(self) -> None:
        if (settings.idle_unload_s > 0 and self.alive and self.state == "ready" and not self._lock.locked()
                and time.monotonic() - self.last_used > settings.idle_unload_s):
            await self.unload(reason=f"idle for {settings.idle_unload_s:.0f}s")

    def status(self) -> dict:
        idle = time.monotonic() - self.last_used
        return {
            "state": self.state if self.alive or self.state == "loading" else "unloaded",
            "pid": self.proc.pid if self.alive else None,
            "idle_s": round(idle, 1) if self.alive else None,
            "unloads_in_s": round(max(0.0, settings.idle_unload_s - idle), 1)
            if self.alive and self.state == "ready" and settings.idle_unload_s > 0 else None,
            **({"info": self.info} if self.info else {}),
        }

    @property
    def on_gpu(self) -> bool:
        """Whether its work needs the GPU slot: not when set to the CPU, or when it loaded on the CPU."""
        if self.device_env and (self.env.get(self.device_env) or os.environ.get(self.device_env) or "auto") == "cpu":
            return False
        return str(self.info.get("device", "")).lower() != "cpu"

    # ---- protocol --------------------------------------------------------------------------

    async def _read_event(self) -> dict:
        line = await self.proc.stdout.readline()
        if not line:
            code = await self.proc.wait()
            raise EngineError(f"{self.name}: worker exited (code {code}); see `localtts logs`")
        return json.loads(line)

    async def generate(self, **params) -> AsyncIterator[bytes]:
        """Yield PCM s16le chunks; the final item is the worker's `done` stats dict."""
        async with self._lock, gpu_lease(f"{self.name.title()} speech", params.get("request_id"), self.on_gpu):
            if self._stale and self.alive:
                await self._drain()
            await self.ensure_loaded()
            self.state = "busy"
            error = None
            try:
                self.proc.stdin.write((json.dumps({"op": "generate", **params}) + "\n").encode())
                await self.proc.stdin.drain()
                while True:
                    msg = await self._read_event()
                    ev = msg.get("event")
                    if ev == "chunk":
                        yield await self.proc.stdout.readexactly(msg["nbytes"])
                    elif ev == "done":
                        yield msg
                        return
                    elif ev == "error":
                        # The worker reported and is still in sync; keep it loaded.
                        error = EngineError(f"{self.name}: {msg.get('message')}")
                        break
            except (asyncio.IncompleteReadError, BrokenPipeError, ConnectionResetError) as exc:
                await self.unload(reason="worker died")
                raise EngineError(f"{self.name}: worker died mid-request ({exc})") from exc
            except BaseException:
                # Client went away mid-stream (e.g. Cancel in the UI): the worker is still
                # emitting audio for this request. Tell it to stop after its current chunk, and
                # read off what it already sent before the next request rather than restarting
                # the worker, which would cost a full model load.
                if self.alive:
                    self._stale = True
                    with contextlib.suppress(OSError, RuntimeError):   # pipe gone: the drain restarts it
                        self.proc.stdin.write((json.dumps({"op": "cancel", "request_id": params.get("request_id")}) + "\n").encode())
                raise
            finally:
                if self.alive:
                    self.state = "ready"
                self.last_used = time.monotonic()
            raise error


    async def _drain(self) -> None:
        """Read off an abandoned request's remaining output; restart the worker if it takes long."""
        log.info("%s: finishing an abandoned request first", self.name)
        try:
            async with asyncio.timeout(DRAIN_TIMEOUT_S):
                while True:
                    msg = await self._read_event()
                    if msg.get("event") == "chunk":
                        await self.proc.stdout.readexactly(msg["nbytes"])
                    elif msg.get("event") in ("done", "error"):
                        break
            self._stale = False
        except (TimeoutError, asyncio.IncompleteReadError, EngineError, ValueError):
            await self.unload(reason=f"abandoned request still running after {DRAIN_TIMEOUT_S:.0f}s")


async def _oneshot(script: str, args: list[str], what: str, timeout: float = 600) -> dict:
    """Run a worker once in a throwaway process (Breeze venv, which has Whisper); return its result."""
    if not settings.breeze_python.exists():
        raise EngineError(f"{what} needs Whisper from the Breeze environment ({settings.breeze_python} not found)")
    async with gpu_lease(f"Whisper {what}", on_gpu=breeze_env().get("BREEZE_DEVICE") != "cpu"):
        return await _oneshot_run(script, args, what, timeout)


async def _oneshot_run(script: str, args: list[str], what: str, timeout: float) -> dict:
    proc = await asyncio.create_subprocess_exec(
        str(settings.breeze_python), str(WORKERS / script), *args,
        stdout=asyncio.subprocess.PIPE, stderr=None, cwd=str(WORKERS),
        env={**WORKER_ENV, **os.environ, "HF_HUB_OFFLINE": "1", **breeze_env()},
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    for line in out.decode().splitlines():
        msg = json.loads(line)
        if msg.get("event") == "result":
            return msg
        if msg.get("event") == "error":
            raise EngineError(f"{what} failed: {msg.get('message')}")
    raise EngineError(f"{what} failed (exit {proc.returncode}); see `localtts logs`")


async def transcribe(path: Path, language: str | None = None) -> str:
    """Whisper transcript of a voice reference."""
    return (await _oneshot("transcribe_worker.py", [str(path)] + ([language] if language else []), "transcription"))["text"]


async def align_clips(job_file: Path) -> dict:
    """Word timings for finished clips: {id: {duration, sample_rate, words}}."""
    return (await _oneshot("align_worker.py", [str(job_file)], "alignment"))["items"]


ENGINES: dict[str, Engine] = {
    "breeze": Engine("breeze", settings.breeze_python, "breeze_worker.py", device_env="BREEZE_DEVICE",
                     env={"HF_HUB_OFFLINE": "1", **breeze_env(),
                          # Persistent torch.compile cache (the default lives in /tmp, wiped at boot).
                          "TORCHINDUCTOR_CACHE_DIR": str(Path("~/.cache/localtts/inductor").expanduser())}),
    "kokoro": Engine("kokoro", settings.kokoro_python, "kokoro_worker.py"),
}
