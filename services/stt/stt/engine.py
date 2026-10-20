"""Which speech model is loaded, on what, and the switch between models.

One model at a time. A request naming another model waits for the passes in flight and swaps.
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
from collections import deque
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


class Engine:
    def __init__(self, settings: Settings, *, gpu: bool | None = None, registrar: Registrar | None = None) -> None:
        self.settings = settings
        self._gpu = gpu
        self._registrar = registrar
        self._lifecycle: AsrLifecycle | None = None
        self._switch = asyncio.Lock()
        self._passes = 0                     # passes in flight (file jobs and live streams)
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
        return self._passes > 0

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
        """Make ``model`` the loaded one, fetching its weights first if they aren't here."""
        if self.model == model and self.ready:
            return
        async with self._switch:
            if self.model == model and self.ready:
                return
            await asyncio.to_thread(self._wait_idle)
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

    async def unload(self) -> None:
        async with self._switch:
            await asyncio.to_thread(self._wait_idle)
            await self._unload_locked()

    async def _unload_locked(self) -> None:
        if self._lifecycle is not None:
            await self._lifecycle.unload()
        self._lifecycle = None
        self.model = self.device = self.precision = None
        self.state, self.message, self.fell_back = "unloaded", "", False

    def _wait_idle(self) -> None:
        with self._idle:
            self._idle.wait_for(lambda: self._passes == 0)

    def _notice(self, kind: str, detail: str) -> None:
        """From the isolated worker: ``restarted`` after a crash, ``fell-back`` to the CPU."""
        self.restarts += 1
        if kind == "fell-back":
            self.fell_back, self.device, self.precision = True, "cpu", "int8"
        self.notices.append({"ts": time.time(), "kind": kind, "detail": detail})

    # -- transcription -------------------------------------------------------------

    def transcribe(self, audio: np.ndarray, prompt: str | None = None, language: str | None = None) -> AsrResult:
        """One pass on the loaded model (blocking; call from a thread). Filtered for invented text."""
        lifecycle = self._lifecycle
        if lifecycle is None:
            raise RuntimeError("no model is loaded")
        with self._idle:
            self._passes += 1
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
        """Unload after ``idle_unload_s`` without a pass (0 = never)."""
        while True:
            await asyncio.sleep(interval)
            limit = self.settings.idle_unload_s
            if limit > 0 and self.ready and not self.busy and time.monotonic() - self.last_used > limit:
                logger.info("Unloading %s after %.0f s idle", self.model, limit)
                await self.unload()

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state, "model": self.model, "model_id": self.model_id, "device": self.device,
            "precision": self.precision, "fell_back": self.fell_back, "restarts": self.restarts,
            "error": self.error, "message": self.message, "notices": list(self.notices),
            "worker_pid": self.worker_pid(),
        }
