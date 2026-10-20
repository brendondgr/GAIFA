"""EmbeddingGemma 2 behind one lock: which encoders are loaded, the task prompts, Matryoshka truncation.

The text path (270M) loads first; the vision encoder (images, video) and the audio encoder load on first use
of those kinds, by reloading the model with the union of the parts (sentence-transformers builds the towers
from `config_kwargs`, so a part that isn't asked for takes no memory). Prompts and truncation live here, not
in the backend, so the fake backend the tests use goes through the same code.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("embed")

DIMS = (768, 512, 256, 128)
FULL_DIM = 768
KINDS = ("text", "image", "audio", "video")
PART = {"image": "vision", "video": "vision", "audio": "audio"}     # text needs no extra part
PARTS = ("vision", "audio")
DRM_MEM_RE = re.compile(r"^drm-memory-(?:gtt|vram):\s+(\d+)\s*KiB", re.MULTILINE)
QUERY_PROMPT = "task: search result | query: "
# What a load needs, in GB, until this machine has measured it (memory.json in the state folder): measured on
# gfx1151 in bf16 after first use, as the hub counts it (PSS + GTT); text+audio is interpolated.
DEFAULT_GB = {(): 3.0, ("vision",): 3.9, ("audio",): 4.4, ("audio", "vision"): 5.4}


def prompt(text: str, task: str, title: str | None = None) -> str:
    """The model card's prefixes: a search query, or a document with its title (`none` without one)."""
    if task == "query":
        return QUERY_PROMPT + text
    return f"title: {(title or '').strip() or 'none'} | text: {text}"


def truncate(vectors: np.ndarray, dim: int) -> np.ndarray:
    """Matryoshka: keep the leading `dim` values, then L2-normalize again (a slice of a unit vector isn't one)."""
    v = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)


def parts_for(kinds: set[str] | list[str]) -> frozenset[str]:
    return frozenset(PART[k] for k in kinds if k in PART)


class Backend(Protocol):
    device: str
    dtype: str

    def load(self, parts: frozenset[str]) -> None: ...
    def unload(self) -> None: ...
    def encode(self, kind: str, items: list[Any], batch_size: int) -> np.ndarray: ...
    def footprint_bytes(self) -> int: ...


def footprint_bytes(pid: int | str = "self") -> int:
    """What the hub measures for a process (architecture §7): its PSS plus its GPU memory (GTT and VRAM, from
    the DRM fdinfo, one count per client). torch's own counters miss the ROCm runtime's allocations."""
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


class GemmaBackend:
    """sentence-transformers on the GPU in bf16 (never fp16: the card says it overflows), else fp32 on the CPU."""

    def __init__(self, model_dir: Path, device: str = "auto"):
        self.model_dir = model_dir
        self.want = device
        self.model: Any = None
        self.device = "cpu"
        self.dtype = "float32"

    def load(self, parts: frozenset[str]) -> None:
        import torch                                        # imported on first load: health answers at once
        from sentence_transformers import SentenceTransformer

        if not (self.model_dir / "model.safetensors").is_file():
            raise FileNotFoundError(f"no weights in {self.model_dir}")
        self.unload()
        gpu = torch.cuda.is_available() and self.want in ("auto", "cuda")
        if self.want == "cuda" and not gpu:
            raise RuntimeError("EMBED_DEVICE=cuda but torch sees no GPU")
        dtype = torch.bfloat16 if gpu and torch.cuda.is_bf16_supported() else torch.float32
        off = {"vision": "vision_config", "audio": "audio_config"}
        config = {off[p]: None for p in PARTS if p not in parts}
        self.model = SentenceTransformer(str(self.model_dir), device="cuda" if gpu else "cpu", local_files_only=True,
                                         model_kwargs={"dtype": dtype}, config_kwargs=config)
        self.device, self.dtype = ("cuda" if gpu else "cpu"), str(dtype).removeprefix("torch.")

    def unload(self) -> None:
        if self.model is None:
            return
        self.model = None
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def encode(self, kind: str, items: list[Any], batch_size: int) -> np.ndarray:
        inputs = items if kind == "text" else [{kind: x} for x in items]
        out = self.model.encode(inputs, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
        if self.device == "cuda":                       # long inputs leave GBs of activations in torch's cache
            import torch
            torch.cuda.empty_cache()
        return np.asarray(out, dtype=np.float32).reshape(len(items), -1)

    def footprint_bytes(self) -> int:
        return footprint_bytes()


class Encoder:
    """The loaded state and the one lock every load, unload and encode takes."""

    def __init__(self, backend: Backend, state_dir: Path | None = None):
        self.backend = backend
        self.parts: frozenset[str] | None = None           # None = unloaded
        self.lock = threading.Lock()
        self.busy = False
        self.loading = False
        self.last_used = time.time()
        self.counts = {k: 0 for k in KINDS}
        self.ms = {k: 0.0 for k in KINDS}                   # total encode time per kind, for the speed stats
        self.state_file = state_dir / "memory.json" if state_dir else None
        self.measured: dict[str, float] = self._read_measured()

    @property
    def loaded(self) -> bool:
        return self.parts is not None

    def _read_measured(self) -> dict[str, float]:
        try:
            return json.loads(self.state_file.read_text()) if self.state_file else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def key(parts: frozenset[str]) -> str:
        return "+".join(["text", *sorted(parts)])

    def estimate_gb(self, parts: frozenset[str]) -> float:
        return self.measured.get(self.key(parts)) or DEFAULT_GB[tuple(sorted(parts))]

    def needs(self, kinds: set[str]) -> frozenset[str] | None:
        """The parts to load for these kinds (the union with what's loaded), or None when nothing changes."""
        want = parts_for(kinds) | (self.parts or frozenset())
        return None if self.parts is not None and want <= self.parts else want

    def load(self, parts: frozenset[str] = frozenset()) -> None:
        with self.lock:
            self._load(parts | (self.parts or frozenset()))

    def _load(self, parts: frozenset[str]) -> None:
        if self.parts is not None and parts <= self.parts:
            return
        self.loading = True
        t = time.time()
        try:
            self.parts = None
            self.backend.load(parts)
        finally:
            self.loading = False
            if not getattr(self.backend, "alive", True):
                self.parts = None
        self.parts = parts
        log.info("loaded %s on %s (%s) in %.1f s, %.1f GB", self.key(parts), self.backend.device,
                 self.backend.dtype, time.time() - t, self.measure())
        self.last_used = time.time()

    def measure(self) -> float:
        """Record what the loaded set uses, keeping the most seen (the first encode adds kernels and caches)."""
        gb = math.ceil(self.backend.footprint_bytes() / 1e8) / 10    # rounded up to 0.1 GB
        key = self.key(self.parts or frozenset())
        if gb > self.measured.get(key, 0):
            self.measured[key] = gb
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
        """Loaded, not working, and unused for longer than `idle_s` (0 = never)."""
        return (idle_s > 0 and self.loaded and not self.busy and not self.loading
                and (now or time.time()) - self.last_used > idle_s)

    def unload(self) -> bool:
        with self.lock:
            was = self.parts is not None
            self.backend.unload()
            self.parts = None
            return was

    def embed(self, items: list[tuple[str, Any]], dim: int, batch: dict[str, int]) -> np.ndarray:
        """`items` are (kind, prepared input) with text already prompted; returns (n, dim) unit vectors, in order.
        Inputs of one kind go to the model together, in batches of `batch[kind]`."""
        if dim not in DIMS:
            raise ValueError(f"dim must be one of {DIMS}")
        kinds = {k for k, _ in items}
        with self.lock:
            want = self.needs(kinds)
            if want is not None:
                self._load(want)
            self.busy = True
            try:
                out = np.zeros((len(items), FULL_DIM), dtype=np.float32)
                for kind in KINDS:
                    idx = [i for i, (k, _) in enumerate(items) if k == kind]
                    if not idx:
                        continue
                    t = time.perf_counter()
                    try:
                        vecs = self.backend.encode(kind, [items[i][1] for i in idx], batch.get(kind, 1))
                    except Exception:
                        if not getattr(self.backend, "alive", True):     # the worker died: nothing is loaded
                            self.parts = None
                        raise
                    self.ms[kind] += (time.perf_counter() - t) * 1000
                    self.counts[kind] += len(idx)
                    out[idx] = vecs[:, :FULL_DIM]
            finally:
                self.busy = False
                self.last_used = time.time()
            self.measure()
        return truncate(out, dim)


class FakeBackend:
    """Deterministic vectors from a hash of the input, for tests: the same input always gives the same vector,
    and a text that names an image's `label` points the same way as that image."""

    device = "cpu"
    dtype = "float32"

    def __init__(self):
        self.parts: frozenset[str] | None = None
        self.loads: list[frozenset[str]] = []
        self.batches: list[tuple[str, int]] = []

    def load(self, parts: frozenset[str]) -> None:
        self.parts = parts
        self.loads.append(parts)

    def unload(self) -> None:
        self.parts = None

    @staticmethod
    def vector(seed: str) -> np.ndarray:
        rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
        v = rng.standard_normal(FULL_DIM).astype(np.float32)
        return v / np.linalg.norm(v)

    def encode(self, kind: str, items: list[Any], batch_size: int) -> np.ndarray:
        assert self.parts is not None, "encode while unloaded"
        if kind in PART and PART[kind] not in self.parts:
            raise RuntimeError(f"{kind} needs the {PART[kind]} encoder")
        for i in range(0, len(items), batch_size):
            self.batches.append((kind, len(items[i:i + batch_size])))
        return np.stack([self.vector(self.label(kind, x)) for x in items])

    @staticmethod
    def label(kind: str, x: Any) -> str:
        if kind == "text":
            return x.split(": ")[-1].strip().lower()          # the text after its prompt
        if kind == "image":
            return (getattr(x, "info", {}) or {}).get("label") or str(x.size)
        if kind == "audio":
            return f"audio:{len(x['array'])}"
        return f"video:{len(x)}"

    def footprint_bytes(self) -> int:
        return int(1e9)
