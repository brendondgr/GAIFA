"""The models this mod offers, the presets, and where their weights live.

Weights are kept in ``data/models/stt/<name>/`` (``$AIHUB_MODELS/stt``), one plain folder per model
(``model.bin``, ``config.json``, ``tokenizer.json``, ``vocabulary.*``), never in ``~/.cache``.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    repo: str
    size: str
    size_bytes: int
    #: Rough peak memory while loaded at float16 on the GPU (weights plus the decoder's working set).
    memory_gb: float
    note: str


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo("tiny", "Systran/faster-whisper-tiny", "75 MB", 75_000_000, 0.4, "Fastest; noticeably less accurate"),
    ModelInfo("base", "Systran/faster-whisper-base", "142 MB", 142_000_000, 0.6, "Fast; fine for clear speech"),
    ModelInfo("small", "Systran/faster-whisper-small", "464 MB", 464_000_000, 1.2, "Balanced: the default"),
    ModelInfo("medium", "Systran/faster-whisper-medium", "1.5 GB", 1_530_000_000, 2.6, "Superseded by large-v3-turbo"),
    ModelInfo("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "1.6 GB", 1_620_000_000, 2.8,
              "Nearly large-v3's accuracy at about four times its speed"),
    ModelInfo("large-v3", "Systran/faster-whisper-large-v3", "3.1 GB", 3_090_000_000, 4.8, "Most accurate; slowest"),
)
BY_NAME = {m.name: m for m in CATALOG}

#: Preset → model. ``balanced`` is what a caller gets when it names neither.
PRESETS: dict[str, str] = {"fast": "base", "balanced": "small", "accurate": "large-v3-turbo", "best": "large-v3"}
DEFAULT_PRESET = "balanced"
#: The model names int8 may be used with on the GPU here (the rest fault gfx1151; acceleration.py).
GPU_INT8_OK = frozenset({"tiny", "base"})
#: Written beside the weights: the repo and revision they came from (for the registry).
SOURCE_FILE = ".source.json"
WEIGHT_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*")


class UnknownModel(ValueError):
    pass


def pick(model: str | None = None, preset: str | None = None) -> str:
    """The model to run: ``model`` by name, else the preset's, else ``balanced``'s (``small``)."""
    if model:
        if model not in BY_NAME:
            raise UnknownModel(f"unknown model {model!r}; choose one of {', '.join(BY_NAME)}")
        return model
    if preset:
        if preset not in PRESETS:
            raise UnknownModel(f"unknown preset {preset!r}; choose one of {', '.join(PRESETS)}")
        return PRESETS[preset]
    return PRESETS[DEFAULT_PRESET]


def compute_for(model: str, gpu: bool, *, precision: str | None = None) -> tuple[str, str]:
    """(device, precision) to load ``model`` with: float16 on the GPU, int8 on the CPU.

    int8 on the GPU is honoured only for tiny and base when asked for; for small and up it is
    replaced with float16, because it faults gfx1151 rather than failing.
    """
    if not gpu:
        return "cpu", "int8"
    if precision == "int8" and model in GPU_INT8_OK:
        return "cuda", "int8"
    if precision == "float32":
        return "cuda", "float32"
    return "cuda", "float16"


def model_dir(weights: Path, name: str) -> Path:
    return weights / name


def is_downloaded(weights: Path, name: str) -> bool:
    folder = model_dir(weights, name)
    return (folder / "model.bin").is_file() and (folder / "config.json").is_file()


def find_in_hf_cache(name: str, cache: Path | None = None) -> Path | None:
    """A complete snapshot of ``name`` already in the user's Hugging Face cache, to copy rather than
    download. Reading outside the project root is fine; writing is not."""
    info = BY_NAME[name]
    hub = cache or Path.home() / ".cache" / "huggingface" / "hub"
    snapshots = hub / f"models--{info.repo.replace('/', '--')}" / "snapshots"
    try:
        for snap in sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (snap / "model.bin").is_file() and (snap / "config.json").is_file():
                return snap
    except OSError:
        return None
    return None


def fetch(weights: Path, name: str, *, cache: Path | None = None) -> dict:
    """Make ``name``'s weights present in ``weights/<name>``; returns ``{"source", "revision"}``.

    Copies a cached snapshot when there is one, else downloads from Hugging Face. Either way the
    files land in ``<name>.part`` first and are renamed when complete.
    """
    info = BY_NAME[name]
    target = model_dir(weights, name)
    if is_downloaded(weights, name):
        return {"source": "present", "revision": None}
    part = target.with_name(f"{name}.part")
    shutil.rmtree(part, ignore_errors=True)
    weights.mkdir(parents=True, exist_ok=True)
    cached = find_in_hf_cache(name, cache)
    if cached is not None:
        logger.info("Copying %s from %s", name, cached)
        shutil.copytree(cached, part, symlinks=False)
        source, revision = "copied", cached.name
    else:
        logger.info("Downloading %s from %s", name, info.repo)
        from huggingface_hub import snapshot_download

        snapshot_download(info.repo, local_dir=str(part), allow_patterns=list(WEIGHT_FILES))
        shutil.rmtree(part / ".cache", ignore_errors=True)
        source, revision = "downloaded", _revision(info.repo)
    (part / SOURCE_FILE).write_text(json.dumps({"repo": info.repo, "revision": revision, "how": source}))
    shutil.rmtree(target, ignore_errors=True)
    part.rename(target)
    return {"source": source, "revision": revision}


def recorded_source(weights: Path, name: str) -> dict:
    """What :func:`fetch` wrote about where the weights came from (``{}`` if nothing)."""
    try:
        return json.loads((model_dir(weights, name) / SOURCE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def _revision(repo: str) -> str | None:
    try:
        from huggingface_hub import HfApi

        return HfApi().model_info(repo).sha
    except Exception:  # noqa: BLE001 - the revision is a nicety for the registry
        return None


def describe(weights: Path, *, loaded: str | None, gpu: bool) -> list[dict]:
    """``GET /v1/models``: every model with its size, whether it is here, loaded, and how it runs."""
    presets = {v: k for k, v in PRESETS.items()}
    rows = []
    for m in CATALOG:
        device, precision = compute_for(m.name, gpu)
        rows.append({
            "name": m.name, "repo": m.repo, "size": m.size, "size_bytes": m.size_bytes,
            "preset": presets.get(m.name), "default": m.name == PRESETS[DEFAULT_PRESET],
            "downloaded": is_downloaded(weights, m.name), "loaded": m.name == loaded,
            "device": device, "precision": precision, "note": m.note,
        })
    return rows
