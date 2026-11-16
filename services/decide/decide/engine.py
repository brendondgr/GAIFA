"""Which decision model is loaded, the one lock every load, unload and ask takes, and the measured memory.

`LocalBackend` holds an adapter (decide/models/) in this process: the worker runs one, and the tests use one
with the fake model directly. `Decider` keeps the state the server reports: loaded model, busy, counts, latency.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("decide")
DRM_MEM_RE = re.compile(r"^drm-memory-(?:gtt|vram):\s+(\d+)\s*KiB", re.MULTILINE)
DEFAULT_GB = 3.5            # until this machine has measured a model (memory.json in the state folder)


def footprint_bytes(pid: int | str = "self") -> int:
    """What the hub measures for a process (architecture §7): its PSS plus its GPU memory (GTT and VRAM, from
    the DRM fdinfo, one count per client)."""
    proc = Path("/proc") / str(pid)
    pss = 0
    try:
        for line in (proc / "smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                pss = int(line.split()[1]) * 1024
    except OSError:
        pass
    gpu: dict[str, int] = {}
    for f in (proc / "fdinfo").glob("*"):
        try:
            text = f.read_text()
        except OSError:
            continue
        client = re.search(r"^drm-client-id:\s+(\d+)", text, re.MULTILINE)
        if client:
            gpu[client.group(1)] = sum(int(n) * 1024 for n in DRM_MEM_RE.findall(text))
    return pss + sum(gpu.values())


class Backend(Protocol):
    device: str
    dtype: str

    def load(self, model_id: str) -> None: ...
    def unload(self) -> None: ...
    def ask(self, model_id: str, state: Any, questions: list[dict], images: list[bytes] | None,
            videos: list[tuple[str, bytes]] | None) -> dict[str, Any]: ...
    def footprint_bytes(self) -> int: ...


class LocalBackend:
    """One adapter in this process. Loading another model unloads the first."""

    def __init__(self, adapters: dict[str, type], models_dir: Path, device: str = "auto", batch_size: int = 8,
                 verify: str = "full"):
        from .models import with_cards

        self.adapters = with_cards(adapters, models_dir)     # cards are rebuilt here: a worker can't unpickle them
        self.models_dir = models_dir
        self.want = device
        self.batch_size = batch_size
        self.verify = verify
        self.model: Any = None
        self.model_id: str | None = None
        self.device = "cpu"
        self.dtype = "bfloat16"

    def load(self, model_id: str) -> None:
        if self.model_id == model_id:
            return
        self.unload()
        cls = self.adapters[model_id]
        m = cls()
        m.load(self.models_dir / cls.FOLDER, self.want, self.batch_size, self.verify)
        self.model, self.model_id = m, model_id
        self.device, self.dtype = m.device, m.dtype

    def unload(self) -> None:
        if self.model is not None:
            self.model.unload()
        self.model = self.model_id = None

    def ask(self, model_id: str, state: Any, questions: list[dict], images: list[bytes] | None = None,
            videos: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
        self.load(model_id)
        return self.model.ask(state, questions, images, videos)

    def footprint_bytes(self) -> int:
        return footprint_bytes()


class Decider:
    def __init__(self, backend: Backend, state_dir: Path | None = None):
        self.backend = backend
        self.model: str | None = None               # None = unloaded
        self.lock = threading.Lock()
        self.busy = False
        self.loading = False
        self.last_used = time.time()
        self.calls = 0
        self.questions = 0
        self.recent_ms: list[float] = []             # the last 100 asks, for the latency stat
        self.state_file = state_dir / "memory.json" if state_dir else None
        self.measured: dict[str, float] = self._read_measured()

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def _read_measured(self) -> dict[str, float]:
        try:
            return json.loads(self.state_file.read_text()) if self.state_file else {}
        except (OSError, ValueError):
            return {}

    def estimate_gb(self, model_id: str | None) -> float:
        return self.measured.get(model_id or "", DEFAULT_GB) if model_id else 0.0

    def load(self, model_id: str) -> None:
        with self.lock:
            self._load(model_id)

    def _load(self, model_id: str) -> None:
        if self.model == model_id:
            return
        self.loading = True
        t = time.time()
        try:
            self.model = None
            self.backend.load(model_id)
        finally:
            self.loading = False
        self.model = model_id
        log.info("loaded %s on %s (%s) in %.1f s, %.1f GB", model_id, self.backend.device, self.backend.dtype,
                 time.time() - t, self.measure())
        self.last_used = time.time()

    def measure(self) -> float:
        """Record what the loaded model uses, keeping the most seen (the first asks add kernels and caches)."""
        gb = math.ceil(self.backend.footprint_bytes() / 1e8) / 10    # rounded up to 0.1 GB
        if self.model and gb > self.measured.get(self.model, 0):
            self.measured[self.model] = gb
            self._write_measured()
        return gb

    def _write_measured(self) -> None:
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_name(self.state_file.name + ".part")
            tmp.write_text(json.dumps(self.measured, indent=1))
            os.replace(tmp, self.state_file)
        except OSError as e:
            log.warning("couldn't save the memory measurement: %s", e)

    def idle_due(self, idle_s: float, now: float | None = None) -> bool:
        return (idle_s > 0 and self.loaded and not self.busy and not self.loading
                and (now or time.time()) - self.last_used > idle_s)

    def unload(self) -> bool:
        with self.lock:
            was = self.model is not None
            self.backend.unload()
            self.model = None
            return was

    def ask(self, model_id: str, state: Any, questions: list[dict], images: list[bytes] | None = None,
            videos: list[tuple[str, bytes]] | None = None) -> tuple[dict[str, Any], float]:
        """Answers by question id, and the model's time in ms. Loads `model_id` first when it isn't loaded."""
        with self.lock:
            self._load(model_id)
            self.busy = True
            t = time.perf_counter()
            try:
                answers = self.backend.ask(model_id, state, questions, images, videos)
            except Exception:
                if not getattr(self.backend, "alive", True):     # the worker died: nothing is loaded
                    self.model = None
                raise
            finally:
                self.busy = False
                self.last_used = time.time()
            ms = (time.perf_counter() - t) * 1000
            self.calls += 1
            self.questions += len(questions)
            self.recent_ms = (self.recent_ms + [ms])[-100:]
            if self.calls <= 3 or self.calls % 50 == 0:
                self.measure()
        return answers, ms
