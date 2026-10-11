"""Workflow packs: one folder per workflow in workflows/<id>/ (plan 11.5, docs/workflows.md).

    workflow.json        the ComfyUI editor file
    workflow.api.json    optional: the API graph, used as given instead of converting workflow.json
    workflow.toml        optional: the manifest (task, inputs, outputs, presets). Without it: a draft.
    preview.webp|png     optional: the card image
    assets/              optional: files the graph loads, copied to ComfyUI's input folder

Packs are re-read when their files change (`Packs.scan()`, cheap when nothing did), and
ComfyUI's workflows folder is kept as a view of them (`sync_comfy_view`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

log = logging.getLogger("comfy")

PACK_ID = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
EDITOR, API, MANIFEST = "workflow.json", "workflow.api.json", "workflow.toml"
PREVIEWS = ("preview.webp", "preview.png", "preview.jpg")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputMap(_Strict):
    """A pack input: which node field it sets, plus anything that differs from the catalog."""
    node: str | None = None             # the node id in the graph (an exec id like "12:5" inside subgraphs)
    title: str | None = None            # …or the node's title, which survives re-saves that renumber nodes
    field: str                          # the node input it sets
    label: str | None = None
    description: str | None = None
    type: Literal["string", "integer", "number", "boolean", "file", "files"] | None = None
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[Any] | None = None
    multiline: bool | None = None
    required: bool | None = None
    hidden: bool = False                # mapped, but not shown in the Run form or offered to the agent
    also: list[str] = []                # more "<node>.<field>" targets that get the same value
    template: str | None = None         # a string input: a short value given by the caller fills "{}" (see resolve.TEMPLATE_WORDS)

    @model_validator(mode="after")
    def _where(self) -> InputMap:
        if not (self.node or self.title):
            raise ValueError("give `node` (an id) or `title`")
        return self


class OutputMap(_Strict):
    node: str | None = None
    title: str | None = None
    kind: Literal["image", "video", "audio", "mesh", "file"] | None = None

    @model_validator(mode="after")
    def _where(self) -> OutputMap:
        if not (self.node or self.title):
            raise ValueError("give `node` (an id) or `title`")
        return self


class Manifest(_Strict):
    name: str = ""
    task: str = "custom"
    description: str = ""
    tags: list[str] = []
    memory_gb: float | None = Field(None, ge=0)
    agent: bool = True                  # false: the page and API run it, the agent's tools don't offer it
    inputs: dict[str, InputMap] = {}
    outputs: dict[str, OutputMap] = {}
    presets: dict[str, dict[str, Any]] = {}
    set: dict[str, Any] = {}            # fixed values: "<node>.<field>" = value, applied before every check and run

    @field_validator("set")
    @classmethod
    def _set_keys(cls, v: dict) -> dict:
        for k in v:
            if "." not in k:
                raise ValueError(f"set: {k!r} must be \"<node id>.<field>\"")
        return v

    @field_validator("inputs", "outputs", "presets")
    @classmethod
    def _names(cls, v: dict) -> dict:
        for k in v:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k):
                raise ValueError(f"name {k!r}: use lowercase letters, digits and _")
        return v

    @model_validator(mode="after")
    def _preset_keys(self) -> Manifest:
        for p, vals in self.presets.items():
            unknown = set(vals) - set(self.inputs) - {"aspect", "megapixels", "seconds"}
            if unknown:
                raise ValueError(f"preset {p!r} sets inputs that don't exist: {', '.join(sorted(unknown))}")
        return self


@dataclass
class Pack:
    id: str
    dir: Path | None                    # None for a loose draft file in ComfyUI's folder
    source: Path | None = None          # the editor file (or the loose draft's file)
    api: Path | None = None
    manifest: Manifest | None = None
    errors: list[str] = field(default_factory=list)
    sig: tuple = ()

    @property
    def draft(self) -> bool:
        return self.manifest is None

    @property
    def name(self) -> str:
        return (self.manifest.name if self.manifest and self.manifest.name else "") or self.id

    @property
    def task(self) -> str:
        return self.manifest.task if self.manifest else "custom"

    @property
    def preview(self) -> Path | None:
        if self.dir:
            for p in PREVIEWS:
                if (self.dir / p).exists():
                    return self.dir / p
        return None

    @property
    def assets(self) -> Path | None:
        return self.dir / "assets" if self.dir and (self.dir / "assets").is_dir() else None

    def graph_file(self) -> Path | None:
        return self.api or self.source

    def load_graph(self) -> dict:
        p = self.graph_file()
        if p is None:
            raise FileNotFoundError("this pack has neither workflow.json nor workflow.api.json")
        return json.loads(p.read_text())

    def editor(self) -> dict | None:
        """The editor file, when there is one (for node properties: packages, model URLs)."""
        if self.source and self.source.exists():
            try:
                d = json.loads(self.source.read_text())
                return d if isinstance(d, dict) and "nodes" in d else None
            except ValueError:
                return None
        return None


def _sig(d: Path) -> tuple:
    out = []
    for p in (d / EDITOR, d / API, d / MANIFEST, *(d / x for x in PREVIEWS)):
        try:
            st = p.stat()
            out.append((p.name, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(out)


def load_pack(d: Path) -> Pack:
    pid = d.name
    pack = Pack(pid, d, sig=_sig(d))
    if not PACK_ID.match(pid):
        pack.errors.append(f"folder name {pid!r} must match [a-z][a-z0-9-]{{1,47}}")
    if (d / EDITOR).exists():
        pack.source = d / EDITOR
    if (d / API).exists():
        pack.api = d / API
    if not pack.source and not pack.api:
        pack.errors.append(f"no {EDITOR} or {API}")
    if (d / MANIFEST).exists():
        try:
            pack.manifest = Manifest.model_validate(tomllib.loads((d / MANIFEST).read_text()))
        except tomllib.TOMLDecodeError as e:
            pack.errors.append(f"{MANIFEST}: {e}")
        except ValidationError as e:
            for err in e.errors():
                where = ".".join(str(x) for x in err["loc"])
                pack.errors.append(f"{MANIFEST}: {where}: {err['msg']}")
        if pack.errors and pack.manifest is None:
            pack.manifest = Manifest()         # broken, but not a draft: show it with its errors
    return pack


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "wf-" + s
    return s[:48].rstrip("-")


class Packs:
    """All packs and drafts; `scan()` re-reads only what changed."""

    def __init__(self, root: Path, comfy_view: Path | None = None):
        self.root, self.view = root, comfy_view
        self._packs: dict[str, Pack] = {}
        self._loose: dict[str, Pack] = {}
        self.version = 0                # bumps when anything changed (for caches and events)

    def scan(self) -> bool:
        changed = False
        self.root.mkdir(parents=True, exist_ok=True)
        seen = set()
        for d in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            seen.add(d.name)
            old = self._packs.get(d.name)
            if old is None or old.sig != _sig(d):
                self._packs[d.name] = load_pack(d)
                changed = True
        for gone in set(self._packs) - seen:
            del self._packs[gone]
            changed = True
        if self.view is not None:
            changed |= sync_comfy_view(self.root, self.view, self._packs)
            loose = self._scan_loose()
            if loose.keys() != self._loose.keys() or any(loose[k].sig != self._loose[k].sig for k in loose):
                changed = True
            self._loose = loose
        if changed:
            self.version += 1
        return changed

    def _scan_loose(self) -> dict[str, Pack]:
        """Workflows saved in ComfyUI that aren't packs yet (any .json that isn't a pack's symlink)."""
        out: dict[str, Pack] = {}
        if not self.view or not self.view.is_dir():
            return out
        for p in sorted(self.view.rglob("*.json")):
            if p.is_symlink() or any(part.startswith(".") for part in p.relative_to(self.view).parts):
                continue
            rel = p.relative_to(self.view)
            base = slug(f"{rel.parent.name}-{p.stem}" if rel.parent.name and p.stem[:1].isdigit() else p.stem)
            pid, n = base, 2
            while pid in out or pid in self._packs:
                pid, n = f"{base[:44]}-{n}", n + 1
            st = p.stat()
            out[pid] = Pack(pid, None, source=p, sig=((p.name, st.st_mtime_ns, st.st_size),))
        return out

    def get(self, pid: str) -> Pack | None:
        return self._packs.get(pid) or self._loose.get(pid)

    def all(self) -> list[Pack]:
        return list(self._packs.values()) + list(self._loose.values())

    def packs(self) -> list[Pack]:
        return list(self._packs.values())

    def count_ready(self) -> int:
        return sum(1 for p in self._packs.values() if not p.draft and not p.errors)

    def count_drafts(self) -> int:
        return sum(1 for p in self._packs.values() if p.draft) + len(self._loose)

    def adopt(self, pid: str, new_id: str | None = None) -> Pack:
        """Turn a loose draft (a file saved in ComfyUI) into a pack folder; its file becomes the
        pack's workflow.json and a symlink takes its place."""
        loose = self._loose.get(pid)
        if loose is None:
            raise KeyError(pid)
        new_id = new_id or pid
        if not PACK_ID.match(new_id):
            raise ValueError(f"{new_id!r} must match [a-z][a-z0-9-]{{1,47}}")
        d = self.root / new_id
        if d.exists():
            raise FileExistsError(f"workflows/{new_id} already exists")
        d.mkdir(parents=True)
        parent = loose.source.parent
        shutil.move(str(loose.source), d / EDITOR)
        if self.view and parent != self.view and parent.is_relative_to(self.view) and not any(parent.iterdir()):
            parent.rmdir()                     # the folder it was saved in, now empty
        self.scan()
        return self._packs[new_id]


def sync_comfy_view(root: Path, view: Path, packs: dict[str, Pack]) -> bool:
    """Keep ComfyUI's workflows folder a view of the packs: `<id>.json` → the pack's workflow.json.
    ComfyUI saves by writing a temporary file and renaming it over the old one, which replaces the
    symlink with a file: that file is the new version, so it moves into the pack. Only symlinks
    into the packs folder are ever removed; regular files are never deleted."""
    changed = False
    view.mkdir(parents=True, exist_ok=True)
    root_r = root.resolve()
    wanted = {f"{pid}.json": p for pid, p in packs.items() if p.source and p.source.name == EDITOR}
    for name, pack in wanted.items():
        link = view / name
        target = pack.source
        if link.is_symlink():
            if link.resolve() != target.resolve():
                link.unlink()
                link.symlink_to(os.path.relpath(target, view))
                changed = True
        elif link.exists():
            # A save from ComfyUI replaced the symlink: the file is the edited workflow.
            try:
                json.loads(link.read_text())
            except (OSError, ValueError):
                continue                       # half-written; next scan
            os.replace(link, target)
            link.symlink_to(os.path.relpath(target, view))
            log.info("workflow %s saved in ComfyUI: moved into its pack", pack.id)
            changed = True
        else:
            link.symlink_to(os.path.relpath(target, view))
            changed = True
    for link in view.glob("*.json"):
        if link.is_symlink() and link.name not in wanted:
            try:
                inside = Path(os.path.realpath(link)).is_relative_to(root_r)
            except OSError:
                inside = False
            if inside or not link.exists():
                link.unlink()
                changed = True
    return changed
