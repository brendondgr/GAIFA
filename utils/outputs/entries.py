"""Which files and folders under `outputs/` are outputs (architecture §4.7, plan 4.1).

`walk(outputs, scope)` returns every output under `outputs/<scope>`, keyed by its path
relative to the outputs dir, each with a `sig` (sizes and mtimes) so a rescan can tell
whether it changed without reading it. Rules:

- `outputs/<service>/…`: the first folder is the service. Files directly in `outputs/` are ignored.
- **A folder with `output.json`** is one folder output, indexed only once the sidecar says
  `"complete": true`. Until then it is skipped as a whole (nothing inside it is indexed).
- **Any other folder** (a date folder, or anything a mod made, e.g. ComfyUI's subfolders)
  is walked into; each file in it is one output.
- **Skipped:** dotfiles and dot-folders (the hub's previews and `.trash`), unfinished files
  (`*.part`, `*.tmp`, `*.crdownload`, `*.incomplete`) and sidecars: `<file>.json`, or
  `<stem>.json` next to a non-JSON file with that stem.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("aihub.outputs")

FOLDER_SIDECAR = "output.json"
UNFINISHED = (".part", ".tmp", ".crdownload", ".incomplete")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MAX_DEPTH = 8
MAX_FILES = 2000  # files listed for one folder output

KIND_BY_EXT = {
    **dict.fromkeys(("wav", "mp3", "flac", "ogg", "opus", "m4a", "aac"), "audio"),
    **dict.fromkeys(("png", "jpg", "jpeg", "webp", "gif", "bmp", "avif"), "image"),
    **dict.fromkeys(("mp4", "webm", "mov", "mkv"), "video"),
    **dict.fromkeys(("glb", "gltf", "obj", "ply", "stl", "fbx"), "model3d"),
    **dict.fromkeys(("txt", "md", "json", "srt", "vtt", "csv"), "text"),
    **dict.fromkeys(("zip", "tar", "gz", "7z"), "archive"),
}
KINDS = ("audio", "image", "video", "model3d", "text", "archive", "other")
MAIN_PRIORITY = ("model3d", "video", "image", "audio")


def kind_of(name: str) -> str:
    return KIND_BY_EXT.get(name.rsplit(".", 1)[-1].lower() if "." in name else "", "other")


def day_of(name: str) -> date | None:
    m = DATE_RE.match(name)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def skipped(name: str) -> bool:
    return name.startswith(".") or name.endswith(UNFINISHED) or name == "__pycache__"


def read_sidecar(p: Path) -> dict[str, Any] | None:
    """The sidecar as a dict, or None when it is missing or not a JSON object."""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sidecar_for(f: Path) -> Path | None:
    """`<file>.json`, else `<stem>.json` (a JSON output has no stem sidecar)."""
    for c in (f.with_name(f.name + ".json"), f.with_name(f.stem + ".json") if f.suffix.lower() != ".json" else None):
        if c is not None and c.is_file():
            return c
    return None


def _stamp(st: os.stat_result) -> str:
    return f"{st.st_size}:{st.st_mtime_ns}"


@dataclass
class Found:
    """One output on disk: `rel` is relative to the outputs dir."""

    rel: str
    service: str
    is_dir: bool
    day: date | None
    sig: str
    files: list[tuple[str, int, float]] = field(default_factory=list)  # (rel to outputs, size, mtime)
    sidecar: str | None = None  # rel to outputs


class Walker:
    def __init__(self, outputs: Path) -> None:
        self.outputs = outputs
        self.found: dict[str, Found] = {}
        self._seen: set[tuple[int, int]] = set()  # (dev, inode) of walked folders: symlink loops

    def rel(self, p: Path) -> str:
        return p.relative_to(self.outputs).as_posix()

    def walk(self, scope: str = "") -> dict[str, Found]:
        parts = [x for x in scope.split("/") if x]
        if not parts:
            for d in self._dirs(self.outputs):
                self._container(d, d.name, None, 1)
            return self.found
        start = self.outputs.joinpath(*parts)
        if not start.is_dir() or any(skipped(x) for x in parts):
            return self.found
        day = next((d for d in map(day_of, parts[1:]) if d), None)
        self._container(start, parts[0], day, len(parts))
        return self.found

    def _dirs(self, d: Path) -> list[Path]:
        try:
            return sorted(c for c in d.iterdir() if not skipped(c.name) and c.is_dir())
        except OSError:
            return []

    def _container(self, d: Path, service: str, day: date | None, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        try:
            st = d.stat()
            children = sorted(d.iterdir())
        except OSError as e:
            log.warning("outputs: can't read %s: %s", d, e)
            return
        if (st.st_dev, st.st_ino) in self._seen:
            return
        self._seen.add((st.st_dev, st.st_ino))
        names = {c.name for c in children}
        stems = {c.stem for c in children if c.suffix.lower() != ".json"}
        for c in children:
            if skipped(c.name):
                continue
            try:
                is_dir = c.is_dir()
            except OSError:
                continue
            if is_dir:
                if (c / FOLDER_SIDECAR).exists():
                    self._folder(c, service, day)
                else:
                    self._container(c, service, day_of(c.name) or day, depth + 1)
                continue
            if c.name.lower().endswith(".json") and (c.name[:-5] in names or c.name[:-5] in stems):
                continue  # a sidecar
            try:
                fst = c.stat()
            except OSError:
                continue
            side = sidecar_for(c)
            sig = _stamp(fst) + (f"|{_stamp(side.stat())}" if side else "")
            rel = self.rel(c)
            self.found[rel] = Found(rel, service, False, day, sig, [(rel, fst.st_size, fst.st_mtime)], self.rel(side) if side else None)

    def _folder(self, d: Path, service: str, day: date | None) -> None:
        side = d / FOLDER_SIDECAR
        meta = read_sidecar(side)
        if not meta or meta.get("complete") is not True:
            return  # still being written (or a broken sidecar): not an output yet
        files: list[tuple[str, int, float]] = []
        h = hashlib.sha1(_stamp(side.stat()).encode())
        for p in self._files_in(d):
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((self.rel(p), st.st_size, st.st_mtime))
            h.update(f"{p.relative_to(d)}:{_stamp(st)}\n".encode())
            if len(files) >= MAX_FILES:
                break
        rel = self.rel(d)
        self.found[rel] = Found(rel, service, True, day, h.hexdigest()[:16], files, self.rel(side))

    def _files_in(self, d: Path) -> list[Path]:
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
            dirnames[:] = sorted(x for x in dirnames if not skipped(x))
            base = Path(dirpath)
            for n in sorted(filenames):
                if skipped(n) or (base == d and n == FOLDER_SIDECAR):
                    continue
                out.append(base / n)
        return out


def walk(outputs: Path, scope: str = "") -> dict[str, Found]:
    return Walker(outputs).walk(scope)


def scope_for(outputs: Path, p: Path) -> str | None:
    """The folder to rescan when `p` changes: `<service>/<date>` inside a date folder, else
    `<service>`. None for paths the index ignores (outside the outputs dir, dotfiles, `*.part`)."""
    try:
        parts = p.relative_to(outputs).parts
    except ValueError:
        return None
    if not parts:
        return ""
    if any(skipped(x) for x in parts):
        return None  # previews, .trash, `*.part`: the rename that finishes a file is its own event
    if len(parts) >= 2 and day_of(parts[1]):
        return f"{parts[0]}/{parts[1]}"
    return parts[0]
