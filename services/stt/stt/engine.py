"""Which speech model is loaded, on what, and the switch between models.

One model at a time. A request naming another model waits for the passes in flight and swaps.
An open live stream or a running file job holds a **lease** on its model: while any lease is held,
the idle unloader leaves the model alone and a request for another model is refused (``ModelBusy``;
the job queue waits and retries). An explicit unload still goes through; a lease holder whose model
is gone loads it again on its next pass.
The model runs in its own process (``asr.isolated``): a GPU fault restarts it, and three faults in
ten minutes move it to the CPU, which ``status`` reports. The server process itself never imports
CTranslate2, so it never touches the GPU.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from . import catalog
from .asr.contract import AsrCapabilities, AsrResult
from .asr.isolated import IsolatedAsrBackend
from .asr.lifecycle import AsrLifecycle
from .config import AsrConfig, Settings

logger = logging.getLogger(__name__)

#: Called after weights are fetched: ``(model name, {"source", "revision"})``.
Registrar = Callable[[str, dict], Awaitable[None]]


def probe_gpu() -> bool:
    """Whether CTranslate2 sees a GPU, asked in a child process so this one never loads HIP."""
    code = "import ctranslate2, sys; sys.stdout.write(str(ctranslate2.get_cuda_device_count()))"
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
        return out.returncode == 0 and int(out.stdout.strip() or 0) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


class ModelBusy(RuntimeError):
    """Another model is wanted while a stream or job holds a lease on the loaded one."""

    def __init__(self, wanted: str, held: dict[str, int]) -> None:
        self.wanted, self.held = wanted, held
        names = ", ".join(sorted(held))
        super().__init__(f"{names} is in use by a live stream or a file job, so {wanted} can't load now")

    @property
    def fix(self) -> str:
        names = " or ".join(sorted(self.held))
        return f"use {names} (the model in use), or try again when the stream or job ends"


class Engine:
    def __init__(self, settings: Settings, *, gpu: bool | None = None, registrar: Registrar | None = None) -> None:
        self.settings = settings
        self._gpu = gpu
        self._registrar = registrar
        self._lifecycle: AsrLifecycle | None = None
        self._switch = asyncio.Lock()
        self._passes = 0                     # passes in flight (file jobs and live streams)
        self._leases: Counter[str] = Counter()   # model → open streams and running jobs that use it
        self._loop: asyncio.AbstractEventLoop | None = None
        self._idle = threading.Condition()
        self.model: str | None = None
        self.device: str | None = None
        self.precision: str | None = None
        self.state = "unloaded"              # unloaded | loading | ready | failed
        self.error = ""
        self.message = ""
        self.fell_back = False
        self.restarts = 0
        self.notices: deque[dict[str, Any]] = deque(maxlen=20)
        self.last_used = time.monotonic()
        self.audio_seconds = 0.0
        self.inference_seconds = 0.0
        #: The language the model detected on its last pass that heard words.
        self.last_language: str | None = None

    # -- what runs where -----------------------------------------------------------

    async def gpu(self) -> bool:
        if self._gpu is None:
            if self.settings.device == "cpu" or self.settings.backend != "faster-whisper":
                self._gpu = self.settings.device == "cuda"
            else:
                self._gpu = await asyncio.to_thread(probe_gpu)
        return self._gpu

    @property
    def ready(self) -> bool:
        return self._lifecycle is not None and self._lifecycle.is_ready

    @property
    def busy(self) -> bool:
        """A pass is running, or a stream or job holds a lease (the hub won't unload a busy mod)."""
        return self._passes > 0 or bool(self.leases)

    @property
    def leases(self) -> dict[str, int]:
        return {m: n for m, n in self._leases.items() if n > 0}

    @property
    def suppressed(self) -> int:
        return self._lifecycle.suppressed if self._lifecycle else 0

    @property
    def capabilities(self) -> AsrCapabilities:
        backend = self._lifecycle.backend if self._lifecycle else None
        return backend.capabilities if backend is not None else AsrCapabilities()

    @property
    def model_id(self) -> str:
        return self._lifecycle.model_id if self._lifecycle else ""

    # -- loading -------------------------------------------------------------------

    async def ensure(self, model: str) -> None:
        """Make ``model`` the loaded one, fetching its weights first if they aren't here.

        Raises ``ModelBusy`` when another model is loaded and a stream or job holds a lease on it."""
        self._loop = asyncio.get_running_loop()
        if self.model == model and self.ready:
            return
        async with self._switch:
            await self._ensure_locked(model)

    async def acquire(self, model: str) -> None:
        """``ensure(model)`` and hold a lease on it until ``release(model)``."""
        self._loop = asyncio.get_running_loop()
        async with self._switch:
            await self._ensure_locked(model)
            self._leases[model] += 1

    def release(self, model: str) -> None:
        """End a lease taken by ``acquire`` (on the event loop). The idle timer starts from now."""
        if self._leases.get(model, 0) > 1:
            self._leases[model] -= 1
        else:
            self._leases.pop(model, None)
        self.last_used = time.monotonic()

    async def _ensure_locked(self, model: str) -> None:
        if self.model == model and self.ready:
            return
        held = {m: n for m, n in self.leases.items() if m != model}
        if held:
            raise ModelBusy(model, held)
        await self._unload_locked()
        gpu = await self.gpu()
        device, precision = catalog.compute_for(model, gpu)
        self.model, self.device, self.precision = model, device, precision
        self.state, self.error, self.fell_back = "loading", "", False
        path = None
        try:
            if self.settings.backend == "faster-whisper":
                if not catalog.is_downloaded(self.settings.weights, model):
                    self.message = f"Fetching {model}"
                    fetched = await asyncio.to_thread(catalog.fetch, self.settings.weights, model)
                    if self._registrar is not None:
                        await self._registrar(model, fetched)
                path = str(catalog.model_dir(self.settings.weights, model))
            self.message = f"Loading {model} on {device} at {precision}"
            config = AsrConfig(backend=self.settings.backend, model=model, device=device,
                               precision=precision, model_path=path)
            lifecycle = AsrLifecycle(config, on_notice=self._notice)
            await lifecycle.load()
        except Exception as exc:  # noqa: BLE001 - reported in status and to the caller
            self.state, self.error, self.message = "failed", str(exc), ""
            raise
        self._lifecycle = lifecycle
        self.state, self.message = "ready", ""
        self.last_used = time.monotonic()

    async def unload(self, *, idle_for: float | None = None) -> bool:
        """Unload the model (after the passes in flight). Asked for explicitly, this goes through even
        while leases are held: their next pass loads the model again. With ``idle_for``, only when no
        lease is held and nothing has run for that many seconds. Returns whether it unloaded."""
        async with self._switch:
            if idle_for is not None and (not self.ready or self.busy
                                         or time.monotonic() - self.last_used <= idle_for):
                return False
            await self._unload_locked()
            return True

    async def _unload_locked(self) -> None:
        # Detach the model once the passes in flight end, so no new pass can start on one being unloaded.
        lifecycle = await asyncio.to_thread(self._detach)
        if lifecycle is not None:
            await lifecycle.unload()
        self.model = self.device = self.precision = None
        self.state, self.message, self.fell_back = "unloaded", "", False

    def _detach(self) -> AsrLifecycle | None:
        with self._idle:
            self._idle.wait_for(lambda: self._passes == 0)
            lifecycle, self._lifecycle = self._lifecycle, None
            return lifecycle

    def _notice(self, kind: str, detail: str) -> None:
        """From the isolated worker: ``restarted`` after a crash, ``fell-back`` to the CPU."""
        self.restarts += 1
        if kind == "fell-back":
            self.fell_back, self.device, self.precision = True, "cpu", "int8"
        self.notices.append({"ts": time.time(), "kind": kind, "detail": detail})

    # -- transcription -------------------------------------------------------------

    def transcribe(self, audio: np.ndarray, prompt: str | None = None, language: str | None = None,
                   model: str | None = None) -> AsrResult:
        """One pass on the loaded model (blocking; call from a thread). Filtered for invented text.

        With ``model`` (a lease holder's), a model that was unloaded meanwhile is loaded again first."""
        while True:
            with self._idle:
                lifecycle = self._lifecycle
                if lifecycle is not None and (model is None or self.model == model):
                    self._passes += 1
                    break
            if model is None or self._loop is None:
                raise RuntimeError("no model is loaded")
            logger.info("Loading %s again for a stream or job that holds it", model)
            asyncio.run_coroutine_threadsafe(self.ensure(model), self._loop).result()
        try:
            result = lifecycle.transcribe(audio, prompt, language)
        finally:
            with self._idle:
                self._passes -= 1
                self._idle.notify_all()
            self.last_used = time.monotonic()
        if result.language and result.words:
            self.last_language = result.language
        self.audio_seconds += audio.size / 16_000
        self.inference_seconds += result.inference_seconds
        return result

    def worker_pid(self) -> int | None:
        backend = self._lifecycle.backend if self._lifecycle else None
        return backend.worker_pid if isinstance(backend, IsolatedAsrBackend) else None

    async def idle_loop(self, interval: float = 15.0) -> None:
        """Unload after ``idle_unload_s`` without a pass and without a lease (0 = never)."""
        while True:
            await asyncio.sleep(interval)
            limit = self.settings.idle_unload_s
            if limit > 0 and self.ready and not self.busy and time.monotonic() - self.last_used > limit:
                model = self.model
                if await self.unload(idle_for=limit):
                    logger.info("Unloaded %s after %.0f s idle", model, limit)

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state, "model": self.model, "model_id": self.model_id, "device": self.device,
            "precision": self.precision, "fell_back": self.fell_back, "restarts": self.restarts,
            "error": self.error, "message": self.message, "notices": list(self.notices),
            "worker_pid": self.worker_pid(), "leases": self.leases,
        }
