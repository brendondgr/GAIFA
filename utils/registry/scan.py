"""The scanner: model files in `data/models/` that aren't in the registry yet (plan 3.2).

`candidates()` walks the tree and groups files into models; `scan()` drops the ones
already registered. The rules, by top folder:

- `llm/`: GGUFs grouped as lcpp's catalog does: split parts (`-00001-of-00003`)
  go with part 1, and `mmproj-*` / `mtp-*` sidecars join the folder's one model.
- `comfyui/<role>/…`: one model per weight file; the kind comes from the role folder.
- `voices/<slug>/`: a folder with `voice.json` (or audio) is one voice.
- `hf-cache/hub/models--org--name`: one model, the snapshot `refs/main` points at.
- Anywhere else: a Hugging Face folder (`config.json`, `model_index.json`, or
  safetensors next to a `*config*.json`) is one model; so is any other folder of
  weights one level below a top folder (`3d/cube3d-v0.5/`); loose weight files are
  one model each.

Dotfiles, `*.part`, `*.lock`, `*.tmp`, `.cache/` and `registry.json` are skipped.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WEIGHT_EXT = {".gguf", ".safetensors", ".sft", ".bin", ".pt", ".pth", ".ckpt", ".onnx", ".pb", ".h5", ".msgpack", ".npz", ".tflite"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus"}
SKIP_SUFFIX = (".part", ".lock", ".tmp", ".incomplete")
SPLIT_RE = re.compile(r"^(?P<prefix>.*-)(?P<index>\d+)-of-(?P<total>\d+)(?P<suffix>\.gguf)$", re.IGNORECASE)
SIDECAR_RE = re.compile(r"^(mmproj|mtp)[-_]", re.IGNORECASE)
VIDEO_RE = re.compile(r"wan|scail|t2v|i2v|video", re.IGNORECASE)
TOKENIZER_RE = re.compile(r"^(tokenizer|vocab|merges|special_tokens|spiece|sentencepiece)", re.IGNORECASE)

COMFY_KINDS = {
    "diffusion_models": "image", "unet": "image", "checkpoints": "image", "diffusers": "image",
    "text_encoders": "text-encoder", "clip": "text-encoder",
    "vae": "vae", "vae_approx": "vae",
    "loras": "lora",
    "clip_vision": "vision",
    "upscale_models": "upscale", "latent_upscale_models": "upscale",
}
VIDEO_ROLES = {"diffusion_models", "unet", "checkpoints", "diffusers"}
TOP_KINDS = {
    "llm": "llm", "tts": "tts", "stt": "stt", "voices": "voice", "3d": "3d", "image": "image", "video": "video",
    "vae": "vae", "lora": "lora", "loras": "lora", "upscale": "upscale", "vision": "vision",
    "text-encoder": "text-encoder", "text-encoders": "text-encoder",
}
HF_KIND_HINTS = [
    (re.compile(r"whisper|wav2vec|parakeet|\bstt\b|asr", re.IGNORECASE), "stt"),
    (re.compile(r"tts|kokoro|speech|voice|bark|vits", re.IGNORECASE), "tts"),
    (re.compile(r"clip|siglip|dino|vision", re.IGNORECASE), "vision"),
    (re.compile(r"t5|umt5|bert|bge|e5-|embed", re.IGNORECASE), "text-encoder"),
    (re.compile(r"wan|video|t2v|i2v", re.IGNORECASE), "video"),
    (re.compile(r"diffusion|flux|sdxl|image", re.IGNORECASE), "image"),
    (re.compile(r"gguf|llama|qwen|gemma|mistral|phi|instruct|chat", re.IGNORECASE), "llm"),
]


@dataclass
class Candidate:
    path: str  # the model's path: its folder, or its main file
    kind: str
    name: str
    format: str
    files: list[dict[str, Any]] = field(default_factory=list)  # {path, role, size_bytes}
    source: dict[str, Any] | None = None

    @property
    def size_bytes(self) -> int:
        return sum(f["size_bytes"] or 0 for f in self.files)

    @property
    def primary(self) -> str:
        return self.files[0]["path"] if self.files else self.path


class Walker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.out: list[Candidate] = []

    # ---- helpers ---------------------------------------------------------------

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def entries(self, d: Path) -> tuple[list[Path], list[Path]]:
        """(visible sub-folders, visible files) of `d`, sorted; skipped names left out."""
        dirs, files = [], []
        try:
            items = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return [], []
        here = None
        for e in items:
            if skipped(e.name):
                continue
            try:
                if e.is_dir():  # follows symlinks: a linked folder of models is scanned…
                    if e.is_symlink():
                        here = here or os.path.realpath(d)
                        real = os.path.realpath(e.path)
                        if here == real or here.startswith(real + os.sep):
                            continue  # …unless it loops back to a folder above
                    dirs.append(Path(e.path))
                elif e.is_file():
                    files.append(Path(e.path))
            except OSError:
                continue
        return dirs, files

    def all_files(self, d: Path, exclude: set[Path] | None = None) -> list[Path]:
        out: list[Path] = []
        dirs, files = self.entries(d)
        out += files
        for sub in dirs:
            if exclude and sub in exclude:
                continue
            out += self.all_files(sub, exclude)
        return out

    def file(self, p: Path, role: str | None = None) -> dict[str, Any]:
        try:
            size: int | None = p.stat().st_size
        except OSError:
            size = None
        return {"path": self.rel(p), "role": role or role_of(p), "size_bytes": size}

    def add(self, path: Path, kind: str, name: str, fmt: str, files: list[Path | dict[str, Any]], source: dict[str, Any] | None = None) -> None:
        recs = [f if isinstance(f, dict) else self.file(f) for f in files]
        if fmt == "hf-dir" and not source and not any(is_weight(Path(r["path"])) for r in recs):
            return  # a Hugging Face folder with only configs (weights not downloaded): not a model yet
        if recs:
            self.out.append(Candidate(self.rel(path), kind, name, fmt, recs, source))

    def label(self, d: Path) -> str:
        """A folder model's name: its path below the top folder (`Qwen-Image/transformer`)."""
        parts = Path(self.rel(d)).parts
        return "/".join(parts[1:]) or d.name

    # ---- the rules -------------------------------------------------------------

    def walk(self) -> list[Candidate]:
        dirs, files = self.entries(self.root)
        for f in files:
            if f.name != "registry.json" and is_weight(f):
                self.add(f, "llm" if f.suffix.lower() == ".gguf" else "other", stem_name(f), fmt_of([f]), [f])
        for d in dirs:
            top = d.name
            if top == "llm":
                self.llm(d)
            elif top == "comfyui":
                self.comfy(d)
            elif top == "voices":
                self.voices(d)
            elif top == "hf-cache":
                self.hf_cache(d)
            else:
                self.generic(d, TOP_KINDS.get(top, "other"), depth=0)
        return sorted(self.out, key=lambda c: c.path)

    def generic(self, d: Path, kind: str, depth: int) -> None:
        if is_hf(d, self.entries(d)[1]):
            self.add(d, kind, self.label(d), "hf-dir", self.all_files(d))
            return
        dirs, files = self.entries(d)
        hf_below = self.hf_dirs(d)
        if depth >= 1 and not hf_below:
            every = self.all_files(d)
            weights = [f for f in every if is_weight(f)]
            if weights:
                self.add(d, kind, self.label(d), fmt_of(weights), sorted(every, key=lambda f: (not is_weight(f), self.rel(f))))
            return
        for f in files:
            if is_weight(f):
                self.add(f, kind, stem_name(f), fmt_of([f]), [f])
        for sub in dirs:
            self.generic(sub, kind, depth + 1)

    def hf_dirs(self, d: Path) -> list[Path]:
        found = []
        for sub in self.entries(d)[0]:
            if is_hf(sub, self.entries(sub)[1]):
                found.append(sub)
            else:
                found += self.hf_dirs(sub)
        return found

    def llm(self, d: Path) -> None:
        dirs, files = self.entries(d)
        ggufs = [f for f in files if f.suffix.lower() == ".gguf"]
        if is_hf(d, files) and not ggufs:
            self.add(d, "llm", self.label(d), "hf-dir", self.all_files(d))
            return
        groups = gguf_groups(ggufs)
        for main, members in groups:
            only = len(groups) == 1 and d != self.root / "llm" and {f.name for f in files} == {m.name for m, _ in members}
            recs = [self.file(p, role) for p, role in members]
            self.add(d if only else main, "llm", stem_name(main), "gguf", recs)
        for f in files:
            if is_weight(f) and f.suffix.lower() != ".gguf":
                self.add(f, "llm", stem_name(f), fmt_of([f]), [f])
        for sub in dirs:
            self.llm(sub)

    def comfy(self, d: Path) -> None:
        dirs, files = self.entries(d)
        for f in files:
            if is_weight(f):
                self.add(f, "other", stem_name(f), fmt_of([f]), [f])
        for role_dir in dirs:
            self.comfy_role(role_dir, role_dir.name)

    def comfy_role(self, d: Path, role: str) -> None:
        dirs, files = self.entries(d)
        if is_hf(d, files) and d.name != role:  # e.g. comfyui/diffusers/<name>/model_index.json
            self.add(d, comfy_kind(role, d.name), d.name, "hf-dir", self.all_files(d))
            return
        for f in files:
            if is_weight(f):
                self.add(f, comfy_kind(role, f.name), stem_name(f), fmt_of([f]), [f])
        for sub in dirs:
            self.comfy_role(sub, role)

    def voices(self, d: Path) -> None:
        dirs, files = self.entries(d)
        for f in files:
            if f.suffix.lower() in AUDIO_EXT:
                self.add(f, "voice", stem_name(f), f.suffix.lower().lstrip("."), [self.file(f, "reference")])
        for v in dirs:
            every = self.all_files(v)
            meta = v / "voice.json"
            audio = [f for f in every if f.suffix.lower() in AUDIO_EXT]
            if not meta.is_file() and not audio:
                continue
            name = voice_name(meta) or v.name.replace("-", " ").replace("_", " ").title()
            recs = sorted((self.file(f, "meta" if f == meta else "reference" if f in audio else None) for f in every), key=lambda r: (r["role"] != "reference", r["path"]))
            fmt = audio[0].suffix.lower().lstrip(".") if audio else "json"
            self.add(v, "voice", name, fmt, recs, {"type": "created"})

    def hf_cache(self, d: Path) -> None:
        hub = d / "hub"
        for repo in self.entries(hub)[0] if hub.is_dir() else []:
            if not repo.name.startswith("models--"):
                continue  # datasets--, spaces--
            org_name = repo.name.removeprefix("models--")
            org, _, name = org_name.partition("--")
            repo_id = f"{org}/{name}" if name else org
            rev = ""
            ref = repo / "refs" / "main"
            try:
                rev = ref.read_text().strip()
            except OSError:
                pass
            snaps = self.entries(repo / "snapshots")[0]
            snap = repo / "snapshots" / rev if rev and (repo / "snapshots" / rev).is_dir() else (max(snaps, key=_mtime) if snaps else None)
            if snap is None:
                continue
            rev = rev or snap.name
            files = [self.file(f) for f in self.all_files(snap)]
            if not files:
                continue
            if ref.is_file():
                files.append(self.file(ref, "ref"))
            weights = [Path(f["path"]) for f in files if is_weight(Path(f["path"]))]
            self.add(repo, hf_kind(repo_id), name or org, "hf-dir" if not weights or fmt_of(weights) != "gguf" else "gguf", files, {"type": "huggingface", "repo": repo_id, "revision": rev})


# ---- rules as functions ---------------------------------------------------------


def skipped(name: str) -> bool:
    return name.startswith(".") or name.endswith(SKIP_SUFFIX) or name == "__pycache__"


def is_weight(p: Path) -> bool:
    return p.suffix.lower() in WEIGHT_EXT


def is_hf(d: Path, files: list[Path]) -> bool:
    names = {f.name for f in files}
    if "config.json" in names or "model_index.json" in names:
        return True
    return any(f.suffix.lower() == ".safetensors" for f in files) and any(n.endswith(".json") and "config" in n for n in names)


def role_of(p: Path) -> str:
    n = p.name.lower()
    if is_weight(p):
        return "weights"
    if TOKENIZER_RE.match(n):
        return "tokenizer"
    if n.endswith((".json", ".yaml", ".yml", ".txt", ".py", ".md", ".jinja")):
        return "config"
    if p.suffix.lower() in AUDIO_EXT:
        return "audio"
    return "other"


def fmt_of(files: list[Path]) -> str:
    exts = Counter(f.suffix.lower().lstrip(".") for f in files if is_weight(f))
    return exts.most_common(1)[0][0] if exts else "other"


def stem_name(p: Path) -> str:
    stem = p.name
    for ext in WEIGHT_EXT | AUDIO_EXT:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    return re.sub(r"-\d+-of-\d+$", "", stem)


def comfy_kind(role: str, filename: str) -> str:
    kind = COMFY_KINDS.get(role, "other")
    if role in VIDEO_ROLES and VIDEO_RE.search(filename):
        return "video"
    return kind


def hf_kind(repo_id: str) -> str:
    for rx, kind in HF_KIND_HINTS:
        if rx.search(repo_id):
            return kind
    return "other"


def voice_name(meta: Path) -> str | None:
    try:
        data = json.loads(meta.read_text())
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return str(name) if isinstance(name, str) and name.strip() else None


def gguf_groups(ggufs: list[Path]) -> list[tuple[Path, list[tuple[Path, str]]]]:
    """[(main file, [(file, role), …])] for one folder's GGUFs (lcpp's catalog rules)."""
    names = {f.name: f for f in ggufs}
    mains, sidecars, used = [], [], set()
    for f in ggufs:
        m = SPLIT_RE.match(f.name)
        if SIDECAR_RE.match(f.name):
            sidecars.append(f)
        elif m and int(m.group("index")) != 1:
            continue  # a later split part: joins its part 1
        else:
            mains.append(f)
    groups = []
    for main in mains:
        members: list[tuple[Path, str]] = [(main, "model")]
        m = SPLIT_RE.match(main.name)
        if m and int(m.group("total")) > 1:
            width, total = len(m.group("index")), int(m.group("total"))
            for i in range(2, total + 1):
                part = f"{m.group('prefix')}{i:0{width}d}-of-{m.group('total')}{m.group('suffix')}"
                if part in names:
                    members.append((names[part], "split"))
                    used.add(part)
        groups.append((main, members))
    if len(groups) == 1:  # sidecars only attach when the folder holds one model
        for s in sidecars:
            groups[0][1].append((s, "mmproj" if s.name.lower().startswith("mmproj") else "draft"))
    return groups


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def candidates(models_dir: Path) -> list[Candidate]:
    if not models_dir.is_dir():
        return []
    return Walker(models_dir).walk()


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-.")[:64].strip("-.")
    return s or "model"


def unique_id(base: str, taken: set[str]) -> str:
    base = slug(base)
    if base not in taken:
        return base
    for i in range(2, 1000):
        cand = f"{base[:60]}-{i}"
        if cand not in taken:
            return cand
    raise ValueError("no free id")
