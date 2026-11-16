"""Which encoder the mod runs (plan capability-enablement 7.3): EmbeddingGemma 2 by default, or any model in a folder
under the models directory (`{models}/embed/<id>/`) with a small `gaifa-model.toml`:

    name = "MiniLM L6 v2"             # what the pages show
    dim = 384                         # its vector size
    dims = [384]                      # sizes it can be cut to (Matryoshka); [dim] when it can't
    kinds = ["text"]                  # what it reads: text, image, audio, video
    query_prompt = "query: "          # put before a search query
    document_prompt = "{text}"        # a document: {title} and {text}
    dtype = "auto"                    # auto | float32 | bfloat16
    backend = "sentence-transformers" # the generic text backend (EmbeddingGemma 2 keeps its own)
    size_gb = 0.09                    # on disk, for the estimate before it has been measured

Each model has its own index: `embed.db` for EmbeddingGemma 2 (as before), `embed-<id>.db` for another. The model in
use is `EMBED_MODEL` unless a finished switch saved another in `<state>/model.json`.
"""

from __future__ import annotations

import gc
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

GEMMA = "embeddinggemma-2"
ALL_KINDS = ("text", "image", "audio", "video")
FILE = "gaifa-model.toml"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
KNOWN = Path(__file__).resolve().parent.parent / "models"     # the descriptions the mod ships, by folder name


class NeedsFullModel(Exception):
    """A kind the model in use doesn't read (a text-only model and a picture)."""

    def __init__(self, kind: str, model: str):
        super().__init__(f"{kind} needs the full model (EmbeddingGemma 2); {model} reads text only")
        self.kind, self.model = kind, model
        self.code = "needs_full_model"
        self.fix = "switch the embed mod back to EmbeddingGemma 2 (Settings → Agent → Memory → Change…), or search in words"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    folder: Path
    name: str
    dim: int
    dims: tuple[int, ...]
    kinds: tuple[str, ...]
    query_prompt: str
    document_prompt: str
    backend: str = "sentence-transformers"      # gemma | sentence-transformers | fake
    dtype: str = "auto"
    size_gb: float | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def full(self) -> bool:
        return set(ALL_KINDS) <= set(self.kinds)

    def reads(self, kind: str) -> bool:
        return kind in self.kinds

    def prompt(self, text: str, task: str, title: str | None = None) -> str:
        if task == "query":
            return self.query_prompt + text
        return self.document_prompt.format(title=(title or "").strip() or "none", text=text)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "dim": self.dim, "dims": list(self.dims), "kinds": list(self.kinds),
                "full": self.full, "size_gb": self.size_gb, "backend": self.backend,
                "weights": weights(self.folder)}


def gemma(folder: Path) -> ModelInfo:
    return ModelInfo(GEMMA, folder, "EmbeddingGemma 2", 768, (768, 512, 256, 128), ALL_KINDS,
                     "task: search result | query: ", "title: {title} | text: {text}", backend="gemma", size_gb=1.5)


def weights(folder: Path) -> bool:
    return any(folder.glob("*.safetensors")) or (folder / "pytorch_model.bin").is_file()


def description(folder: Path) -> Path | None:
    """The folder's own gaifa-model.toml, else the one the mod ships for a model of that name (services/embed/models/)."""
    for f in (folder / FILE, KNOWN / f"{folder.name}.toml"):
        if f.is_file():
            return f
    return None


def read(folder: Path) -> ModelInfo:
    """The model in `folder`: its description, or EmbeddingGemma 2's own facts for its folder."""
    f = description(folder)
    if f is None:
        if folder.name == GEMMA:
            return gemma(folder)
        raise FileNotFoundError(f"{folder} has no {FILE} (what the model reads, its size and prompts)")
    d = tomllib.loads(f.read_text())
    dim = int(d["dim"])
    kinds = tuple(k for k in d.get("kinds", ["text"]) if k in ALL_KINDS) or ("text",)
    dims = tuple(int(x) for x in d.get("dims", [dim])) or (dim,)
    if dims[0] != dim:
        raise ValueError(f"{f}: dims must start with dim ({dim})")
    return ModelInfo(folder.name, folder, str(d.get("name") or folder.name), dim, dims, kinds,
                     str(d.get("query_prompt", "")), str(d.get("document_prompt", "{text}")),
                     backend=str(d.get("backend", "sentence-transformers")), dtype=str(d.get("dtype", "auto")),
                     size_gb=float(d["size_gb"]) if d.get("size_gb") is not None else None, extra=d)


def available(models_dir: Path) -> list[ModelInfo]:
    """Every model folder the mod can run: EmbeddingGemma 2 first, then the others by name."""
    out: list[ModelInfo] = []
    if not models_dir.is_dir():
        return out
    for d in sorted(models_dir.iterdir()):
        if d.is_dir() and ID_RE.match(d.name) and (description(d) is not None or d.name == GEMMA):
            try:
                out.append(read(d))
            except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
                continue
    return sorted(out, key=lambda m: (m.id != GEMMA, m.name.lower()))


def db_name(model_id: str) -> str:
    return "embed.db" if model_id == GEMMA else f"embed-{model_id}.db"


def chosen_file(state_dir: Path) -> Path:
    return state_dir / "model.json"


def chosen(state_dir: Path, default: str) -> str:
    """The model in use: the last finished switch, else the default (EMBED_MODEL)."""
    try:
        v = json.loads(chosen_file(state_dir).read_text()).get("model")
        return v if isinstance(v, str) and ID_RE.match(v) else default
    except (OSError, ValueError, AttributeError):
        return default


def choose(state_dir: Path, model_id: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = chosen_file(state_dir).with_suffix(".part")
    tmp.write_text(json.dumps({"model": model_id}))
    tmp.replace(chosen_file(state_dir))


class TextBackend:
    """Any sentence-transformers text model (plan 7.3): text in, vectors out; no other kinds."""

    def __init__(self, info: ModelInfo, device: str = "auto"):
        self.info = info
        self.want = device
        self.model: Any = None
        self.device = "cpu"
        self.dtype = "float32"

    def load(self, parts: frozenset[str]) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        from . import device as devmod
        from .encoder import choose as choose_device

        if not weights(self.info.folder):
            raise FileNotFoundError(f"no weights in {self.info.folder}")
        self.unload()
        dev, dtype = choose_device(self.want, torch)
        if self.info.dtype == "float32":
            dtype = torch.float32
        elif self.info.dtype == "bfloat16" and dev != "cpu":
            dtype = torch.bfloat16
        self.model = SentenceTransformer(str(self.info.folder), device=dev, local_files_only=True,
                                         model_kwargs={"dtype": dtype}, trust_remote_code=False)
        self.device, self.dtype = dev, str(dtype).removeprefix("torch.")
        self._devmod = devmod

    def unload(self) -> None:
        if self.model is None:
            return
        self.model = None
        gc.collect()
        if self.device != "cpu":
            self._devmod.empty_cache(self.device)

    def encode(self, kind: str, items: list[Any], batch_size: int) -> np.ndarray:
        if kind != "text":
            raise NeedsFullModel(kind, self.info.name)
        out = self.model.encode(items, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False,
                                normalize_embeddings=True)
        return np.asarray(out, dtype=np.float32).reshape(len(items), -1)

    def footprint_bytes(self) -> int:
        from .encoder import footprint_bytes
        return footprint_bytes()
