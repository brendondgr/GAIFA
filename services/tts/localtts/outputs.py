"""Where generated speech is saved, and the sidecar that describes it (AIHub architecture §4.7).

    <outputs>/<YYYY-MM-DD>/<HHMMSS>-<slug(text[:40])>-<voice>.<ext>
    <outputs>/<YYYY-MM-DD>/<HHMMSS>-<slug(text[:40])>-<voice>.<ext>.json

The audio is written as `<name>.part` and renamed, then the sidecar is written the same way, so
a folder watcher never sees half a file. A request's `save_dir` is a subfolder of the outputs
folder; absolute paths and `..` are refused.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path, PurePosixPath

AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text[:n].lower()).strip("-")
    return s or "speech"


def check_save_dir(save_dir: str | None) -> PurePosixPath | None:
    """A relative subfolder of the outputs folder, or None. Raises ValueError otherwise."""
    if not save_dir or not save_dir.strip():
        return None
    p = PurePosixPath(save_dir.strip().replace("\\", "/"))
    if p.is_absolute() or save_dir.strip().startswith("~") or ".." in p.parts:
        raise ValueError("save_dir must be a subfolder of the outputs folder (no absolute paths or ..)")
    return p


def output_path(base: Path, text: str, voice: str, ext: str, save_dir: str | None = None,
                now: float | None = None) -> Path:
    """A free path for a new clip. Creates its folder."""
    t = time.localtime(now if now is not None else time.time())
    sub = check_save_dir(save_dir)
    folder = base / sub if sub else base / time.strftime("%Y-%m-%d", t)
    folder.mkdir(parents=True, exist_ok=True)
    v = slug(voice, 32) if voice else "voice"
    stem = f"{time.strftime('%H%M%S', t)}-{slug(text)}-{v}"
    path, n = folder / f"{stem}.{ext}", 2
    while path.exists() or path.with_name(path.name + ".part").exists():
        path, n = folder / f"{stem}-{n}.{ext}", n + 1
    return path


def write_atomic(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


def write_sidecar(path: Path, meta: dict) -> None:
    write_atomic(path.with_name(path.name + ".json"),
                 json.dumps(meta, indent=2, ensure_ascii=False).encode())


def sidecar(*, text: str, voice: str, engine: str, model: str, params: dict, duration_s: float | None,
            request_id: str) -> dict:
    title = " ".join(text.split())
    return {
        "title": title if len(title) <= 80 else title[:79].rstrip() + "…",
        "kind": "audio",
        "prompt": text,
        "voice": voice,
        "engine": engine,
        "model": model,
        "params": {k: v for k, v in params.items() if v is not None},
        "duration_s": round(duration_s, 2) if duration_s is not None else None,
        "source": {"service": "tts", "request_id": request_id},
    }


def save(path: Path, data: bytes, meta: dict) -> None:
    write_atomic(path, data)
    write_sidecar(path, meta)


def clips(base: Path) -> list[Path]:
    """Every saved clip under the outputs folder (recursive; dotfiles and `.part` skipped)."""
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS
            and not any(part.startswith(".") for part in p.relative_to(base).parts)]


def clips_today(base: Path) -> int:
    folder = base / time.strftime("%Y-%m-%d")
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS) \
        if folder.is_dir() else 0


def clips_by_day(base: Path, days: int, now: float | None = None) -> tuple[list[str], dict[str, list[int]]]:
    """(day labels oldest first, {voice: counts per day}) for the last `days` local days."""
    now = now if now is not None else time.time()
    labels = [time.strftime("%Y-%m-%d", time.localtime(now - 86400 * i)) for i in range(days - 1, -1, -1)]
    index = {d: i for i, d in enumerate(labels)}
    counts: dict[str, list[int]] = {}
    for d in labels:
        folder = base / d
        if not folder.is_dir():
            continue
        by_voice = Counter()
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                by_voice[_voice_of(p)] += 1
        for v, c in by_voice.items():
            counts.setdefault(v, [0] * days)[index[d]] = c
    return labels, counts


def _voice_of(p: Path) -> str:
    try:
        return json.loads(p.with_name(p.name + ".json").read_text()).get("voice") or "unknown"
    except (OSError, ValueError, AttributeError):
        return "unknown"


def resolve(base: Path, rel: str) -> Path | None:
    """`rel` inside the outputs folder, or None if it escapes it or isn't a file."""
    try:
        p = (base / rel).resolve()
        p.relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    if any(part.startswith(".") for part in PurePosixPath(rel).parts) or not p.is_file():
        return None
    return p
