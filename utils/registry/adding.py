"""`POST /api/models/scan` and `POST /api/models` (plan 3.2): what's unregistered, and adding it.

A mod that downloads a model registers it the same way: `POST /api/models` with
its path (a file or folder in `data/models/`) and its source. The files are found
with the scanner's rules, unless the request lists them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from utils.registry import scan as scanner
from utils.registry.model import ID_RE, Entry, Kind, RegistryError, Source, first_error, now_iso, rel_path

if TYPE_CHECKING:
    from utils.registry.store import Registry


class InputFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    role: str = "weights"
    sha256: str | None = None

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return rel_path(v)


class ModelInput(BaseModel):
    """Brief `ModelInput`, plus optional `id`, `files`, `format`, `tags` and `notes`."""

    model_config = ConfigDict(extra="forbid")
    path: str
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    id: str | None = None
    services: list[str] = []
    source: Source | None = None
    files: list[InputFile] | None = None
    format: str | None = None
    tags: list[str] = []
    notes: str = ""

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return rel_path(v)


def owned_dirs(reg: Registry) -> list[str]:
    """Registered models that own their whole folder (HF folders, voices, …; not a GGUF folder,
    which can gain another quant)."""
    out = []
    for e in reg.entries.values():
        if (e.format != "gguf" or e.path.startswith("hf-cache/")) and reg.abs(e.path).is_dir():
            out.append(e.path)
    return out


def known_files(reg: Registry) -> dict[str, str]:
    """Registered file path (as written, and resolved through symlinks) → model id."""
    out: dict[str, str] = {}
    root = reg.paths.models.resolve()
    for mid, e in reg.entries.items():
        for f in e.files:
            out[f.path] = mid
            try:
                real = reg.abs(f.path).resolve()
                if real.is_relative_to(root):
                    out[real.relative_to(root).as_posix()] = mid
            except OSError:
                pass
    return out


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def discovered(reg: Registry) -> list[dict[str, Any]]:
    reg.refresh()
    known = known_files(reg)
    owned = owned_dirs(reg)
    registered_paths = {e.path for e in reg.entries.values()}
    taken = set(reg.entries)
    out = []
    for c in scanner.candidates(reg.paths.models):
        if c.path in registered_paths or c.primary in known or any(_under(c.path, d) for d in owned):
            continue
        files = [f for f in c.files if f["path"] not in known and _real(reg, f["path"]) not in known]
        if not files:
            continue
        mid = scanner.unique_id(c.name, taken)
        taken.add(mid)
        d: dict[str, Any] = {
            "path": c.path,
            "size_bytes": sum(f["size_bytes"] or 0 for f in files),
            "suggested_kind": c.kind,
            "suggested_name": c.name,
            "suggested_id": mid,
            "format": c.format,
            "files": files,
        }
        if c.source:
            d["source"] = c.source
        out.append(d)
    return out


def _real(reg: Registry, rel: str) -> str:
    try:
        real = reg.abs(rel).resolve()
        return real.relative_to(reg.paths.models.resolve()).as_posix()
    except (OSError, ValueError):
        return rel


async def add(reg: Registry, inp: ModelInput) -> dict[str, Any]:
    reg.refresh()
    if reg.readonly:
        raise RegistryError(409, "registry_invalid", reg.readonly)
    target = reg.inside(inp.path)
    if target is None or not (target.exists() or target.is_symlink()):
        raise RegistryError(422, "invalid_request", f"path: {inp.path} doesn't exist in data/models")
    cand = _candidate(reg, inp.path)
    if inp.files is not None:
        files = [{"path": f.path, "role": f.role, "sha256": f.sha256} for f in inp.files]
        fmt = inp.format or (cand.format if cand else scanner.fmt_of([Path(f["path"]) for f in files]))
    elif cand is not None:
        files = [{"path": f["path"], "role": f["role"]} for f in cand.files]
        fmt = inp.format or cand.format
    elif target.is_file():
        files = [{"path": inp.path, "role": scanner.role_of(target)}]
        fmt = inp.format or scanner.fmt_of([target])
    else:
        w = scanner.Walker(reg.paths.models)
        found = [w.file(p) for p in w.all_files(target)]
        files = [{"path": f["path"], "role": f["role"]} for f in found]
        fmt = inp.format or scanner.fmt_of([Path(f["path"]) for f in files])
    if not files:
        raise RegistryError(422, "invalid_request", f"path: no model files in {inp.path}")
    for f in files:
        p = reg.inside(f["path"])
        if p is None:
            raise RegistryError(422, "invalid_request", f"files: {f['path']} leads outside data/models")
        try:
            f["size_bytes"] = p.stat().st_size
        except OSError:
            f["size_bytes"] = None
        f.setdefault("sha256", None)
        f["verified_at"] = None
    known = known_files(reg)
    for f in files:
        other = known.get(f["path"]) or known.get(_real(reg, f["path"]))
        if other:
            raise RegistryError(409, "model_exists", f"{f['path']} is already registered as {other}", {"id": other})
    if inp.id:
        mid = inp.id
        if mid in reg.entries or mid in reg.invalid:
            raise RegistryError(409, "model_exists", f'A model with id "{mid}" already exists', {"id": mid})
    else:
        mid = scanner.unique_id(inp.name, set(reg.entries) | set(reg.invalid))
    source = inp.source
    if cand and cand.source and (source is None or source.model_dump(exclude_none=True) == {"type": "local"}):
        source = Source.model_validate(cand.source)  # the UI sends a bare "local"; the scanner knows better
    try:
        entry = Entry.model_validate({
            "name": inp.name.strip(), "kind": inp.kind, "format": fmt, "path": inp.path, "files": files,
            "services": inp.services, "source": source.model_dump(exclude_none=True) if source else None,
            "added": now_iso(), "tags": inp.tags, "notes": inp.notes,
        })
    except ValidationError as e:
        raise RegistryError(422, "invalid_request", first_error(e)) from None
    if not ID_RE.match(mid):
        raise RegistryError(422, "invalid_request", f"id: {mid!r} must be lowercase letters, digits, '.', '_' or '-' (up to 64)")
    reg.entries[mid] = entry
    reg.save()
    reg.publish(mid)
    if reg.activity:
        await reg.activity.add(f"Added {entry.name} to the registry", route=f"#/models/{mid}")
    reg.changed()
    return reg.view(mid)


def _candidate(reg: Registry, path: str) -> scanner.Candidate | None:
    for c in scanner.candidates(reg.paths.models):
        if c.path == path or c.primary == path:
            return c
    return None
