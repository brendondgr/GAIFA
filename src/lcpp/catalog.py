"""The model catalog (``data/models.json``) and GGUF files on disk.

A model entry names its main GGUF plus optional sidecars (multimodal projector,
speculative draft). Sidecars are first-class fields rather than entries buried
in ``params`` because the UI edits them as files, validates that they exist,
and counts their size toward the memory estimate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lcpp.paths import Paths, write_atomic

SPLIT_RE = re.compile(r"^(?P<prefix>.*-)(?P<index>\d+)-of-(?P<total>\d+)(?P<suffix>\.gguf)$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SPEC_TYPES = {"draft-simple", "draft-eagle3", "draft-mtp", "draft"}
# Sidecar files discovery must not offer as models of their own.
SIDECAR_RE = re.compile(r"^(mmproj|mtp)[-_]", re.IGNORECASE)
QUANT_SUFFIX_RE = re.compile(r"[-_.]?(i\d-)?(Q\d[A-Z0-9_]*|IQ\d[A-Z0-9_]*|BF16|F16|F32)$", re.IGNORECASE)


class CatalogError(ValueError):
    def __init__(self, message: str, code: str = "invalid_param", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class ModelEntry:
    id: str
    path: str
    nicknames: list[str] = field(default_factory=list)
    mmproj: str | None = None
    draft: str | None = None
    spec_type: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, model_id: str, raw: dict[str, Any]) -> "ModelEntry":
        if not isinstance(raw, dict):
            raise CatalogError(f"model {model_id!r} must be an object")
        path = raw.get("path")
        if not path:
            raise CatalogError(f"model {model_id!r} needs a path")
        nicknames = raw.get("nicknames") or []
        if isinstance(nicknames, str):
            nicknames = [nicknames]
        return cls(
            id=model_id, path=str(path), nicknames=[str(n) for n in nicknames],
            mmproj=raw.get("mmproj") or None, draft=raw.get("draft") or None,
            spec_type=raw.get("spec_type") or None, params=dict(raw.get("params") or {}),
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"nicknames": self.nicknames, "path": self.path}
        if self.mmproj:
            out["mmproj"] = self.mmproj
        if self.draft:
            out["draft"] = self.draft
            out["spec_type"] = self.spec_type or "draft-simple"
        if self.params:
            out["params"] = self.params
        return out

    @property
    def names(self) -> list[str]:
        return [self.id, *self.nicknames]

    @property
    def nick(self) -> str:
        return self.nicknames[0] if self.nicknames else self.id


def split_parts(path: Path) -> list[Path] | None:
    """All parts of a split GGUF when ``path`` is part 1, else None."""
    m = SPLIT_RE.match(path.name)
    if not m or int(m.group("index")) != 1 or int(m.group("total")) <= 1:
        return None
    width = len(m.group("index"))
    total = int(m.group("total"))
    return [
        path.with_name(f"{m.group('prefix')}{i:0{width}d}-of-{m.group('total')}{m.group('suffix')}")
        for i in range(1, total + 1)
    ]


def _size(p: Path) -> int | None:
    try:
        return p.stat().st_size
    except OSError:
        return None


class Catalog:
    def __init__(self, paths: Paths, defaults: dict[str, Any], models: dict[str, ModelEntry]):
        self.paths = paths
        self.defaults = defaults
        self.models = models

    # ---- persistence -------------------------------------------------
    @classmethod
    def load(cls, paths: Paths) -> "Catalog":
        if not paths.models_file.exists():
            return cls(paths, {}, {})
        try:
            raw = json.loads(paths.models_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CatalogError(f"{paths.models_file} is not valid JSON: {e}") from e
        defaults = raw.get("defaults") or {}
        models_raw = raw.get("models") or {}
        if not isinstance(defaults, dict) or not isinstance(models_raw, dict):
            raise CatalogError("models.json needs 'defaults' and 'models' objects")
        models = {mid: ModelEntry.from_json(mid, m) for mid, m in models_raw.items()}
        return cls(paths, dict(defaults), models)

    def save(self) -> None:
        doc = {"defaults": self.defaults, "models": {m.id: m.to_json() for m in self.models.values()}}
        write_atomic(self.paths.models_file, json.dumps(doc, indent=2) + "\n")

    # ---- lookup ------------------------------------------------------
    def resolve(self, query: str) -> ModelEntry:
        """Exact id/nickname match (case-insensitive), else a unique partial match."""
        q = query.casefold()
        exact = [m for m in self.models.values() if any(q == n.casefold() for n in m.names)]
        if len(exact) == 1:
            return exact[0]
        partial = exact or [m for m in self.models.values() if any(q in n.casefold() for n in m.names)]
        if len(partial) == 1:
            return partial[0]
        if not partial:
            raise CatalogError(f'Model "{query}" is not in the catalog', "model_not_found", 404)
        ids = ", ".join(sorted(m.id for m in partial))
        raise CatalogError(f'Model "{query}" is ambiguous: {ids}', "model_not_found", 404)

    def get(self, model_id: str) -> ModelEntry | None:
        return self.models.get(model_id)

    # ---- files -------------------------------------------------------
    def files(self, m: ModelEntry) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        main = self.paths.resolve(m.path)
        parts = split_parts(main)
        if parts:
            for i, p in enumerate(parts, 1):
                files.append(self._file("model" if i == 1 else "split", p, f"{i}/{len(parts)}"))
        else:
            files.append(self._file("model", main))
        if m.mmproj:
            files.append(self._file("mmproj", self.paths.resolve(m.mmproj)))
        if m.draft:
            files.append(self._file("draft", self.paths.resolve(m.draft)))
        return files

    def _file(self, role: str, p: Path, part: str | None = None) -> dict[str, Any]:
        size = _size(p)
        f: dict[str, Any] = {"role": role, "path": self.paths.display(p),
                             "size_bytes": size, "exists": size is not None}
        if part:
            f["part"] = part
        return f

    def problems(self, m: ModelEntry, files: list[dict[str, Any]] | None = None) -> list[str]:
        out = []
        for f in files if files is not None else self.files(m):
            if f["exists"]:
                continue
            msg = f"{f['role']}{' ' + f['part'] if 'part' in f else ''} file not found: {f['path']}"
            doubled = self.paths.resolve(f["path"] + ".gguf") if f["path"].endswith(".gguf") else None
            if doubled and doubled.exists():
                msg += f" (found {doubled.name}; rename it)"
            out.append(msg)
        return out

    # ---- params ------------------------------------------------------
    def overrides(self, m: ModelEntry) -> dict[str, Any]:
        """Per-model params including sidecars, in the display form the UI shows."""
        o = dict(m.params)
        if m.mmproj:
            o["mmproj"] = m.mmproj
        if m.draft:
            o["model-draft"] = m.draft
            o["spec-type"] = m.spec_type or "draft-simple"
        return o

    def effective(self, m: ModelEntry, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**self.defaults, **self.overrides(m), **(extra or {})}

    def size_bytes(self, m: ModelEntry) -> int:
        return sum(f["size_bytes"] or 0 for f in self.files(m))

    # ---- views -------------------------------------------------------
    def view(self, m: ModelEntry, running: list[str] | None = None) -> dict[str, Any]:
        files = self.files(m)
        problems = self.problems(m, files)
        main = self.paths.resolve(m.path)
        try:
            main.relative_to(self.paths.root / "models")
            location = "models"
        except ValueError:
            location = "external"
        return {
            "id": m.id, "nicknames": list(m.nicknames), "path": m.path, "location": location,
            "files": files, "size_bytes": sum(f["size_bytes"] or 0 for f in files),
            "ok": not problems, "problems": problems,
            "capabilities": {"vision": bool(m.mmproj), "speculative": bool(m.draft),
                             "split": split_parts(main) is not None},
            "overrides": self.overrides(m), "effective": self.effective(m),
            "running": running or [],
        }

    # ---- editing -----------------------------------------------------
    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Check a ModelInput from the UI. Returns ``{ok, files, errors}``."""
        mid = str(data.get("id") or "")
        errors = self.name_errors(mid, data.get("nicknames") or [])
        spec = data.get("spec_type") or None
        if data.get("draft") and spec and spec not in SPEC_TYPES:
            errors.append(f"spec_type must be one of {', '.join(sorted(SPEC_TYPES))}")
        path = str(data.get("path") or "").strip()
        if not path:
            errors.append("model file path is required")
            files: list[dict[str, Any]] = []
        else:
            probe = ModelEntry(id=mid or "new", path=path, mmproj=data.get("mmproj") or None,
                               draft=data.get("draft") or None)
            files = self.files(probe)
            errors.extend(self.problems(probe, files))
        return {"ok": not errors, "files": files, "errors": errors}

    def name_errors(self, mid: str, nicknames: list[str]) -> list[str]:
        """Problems with an id + nicknames, ignoring the entry ``mid`` itself."""
        errors: list[str] = []
        if not ID_RE.match(mid):
            errors.append("id must be a slug (letters, digits, dots, dashes, underscores)")
        nicks = {str(n).strip().casefold() for n in nicknames if str(n).strip()}
        for other in self.models.values():
            if other.id == mid:
                continue
            clash = nicks & {n.casefold() for n in other.names}
            if clash or mid.casefold() in {n.casefold() for n in other.nicknames}:
                errors.append(f"a name is already used by model {other.id}")
                break
        return errors

    def entry_from_input(self, data: dict[str, Any]) -> ModelEntry:
        check = self.validate_input(data)
        if not check["ok"]:
            raise CatalogError(check["errors"][0])
        params = dict(data.get("overrides") or {})
        # Sidecars travel as their own fields; never store them twice.
        for k in ("mmproj", "model-draft", "spec-type"):
            params.pop(k, None)
        draft = data.get("draft") or None
        return ModelEntry(
            id=str(data["id"]), path=str(data["path"]).strip(),
            nicknames=[str(n).strip() for n in data.get("nicknames") or [] if str(n).strip()],
            mmproj=data.get("mmproj") or None, draft=draft,
            spec_type=(data.get("spec_type") or "draft-simple") if draft else None,
            params={str(k).removeprefix("--"): v for k, v in params.items()},
        )

    def upsert(self, entry: ModelEntry) -> None:
        self.models[entry.id] = entry
        self.save()

    def delete(self, model_id: str) -> None:
        if model_id not in self.models:
            raise CatalogError(f'Model "{model_id}" not found', "model_not_found", 404)
        del self.models[model_id]
        self.save()

    def set_defaults(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise CatalogError("defaults must be an object")
        self.defaults = {str(k).removeprefix("--"): v for k, v in params.items()}
        self.save()
        return self.defaults

    # ---- discovery ---------------------------------------------------
    def discover(self, scan_dirs: list[str]) -> list[dict[str, Any]]:
        """GGUFs under ``scan_dirs`` (two levels deep) that no catalog entry uses.

        Paths are compared after resolving symlinks, so a file linked from
        elsewhere is not offered twice. Split parts after the first, and
        projector/draft sidecars, are never offered as models.
        """
        known: set[Path] = set()
        for m in self.models.values():
            for f in self.files(m):
                known.add(self.paths.resolve(f["path"]).resolve())
        seen: set[Path] = set()
        out: list[dict[str, Any]] = []
        for d in scan_dirs:
            base = self.paths.resolve(d)
            if not base.is_dir():
                continue
            for p in sorted([*base.glob("*.gguf"), *base.glob("*/*.gguf")]):
                if any(part.startswith(".") for part in p.relative_to(base).parts):
                    continue
                real = p.resolve()
                if real in known or real in seen or not real.is_file():
                    continue
                seen.add(real)
                m = SPLIT_RE.match(p.name)
                if (m and int(m.group("index")) != 1) or SIDECAR_RE.match(p.name):
                    continue
                out.append({
                    "path": self.paths.display(p), "size_bytes": _size(real) or 0,
                    "suggested_id": suggest_id(p.name), "dir": self.paths.display(p.parent),
                })
        return out


def suggest_id(filename: str) -> str:
    stem = re.sub(r"\.gguf$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"-\d+-of-\d+$", "", stem)
    stem = QUANT_SUFFIX_RE.sub("", stem)
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", stem).strip("-.").lower()
    return slug or "model"


if __name__ == "__main__":
    paths = Paths.default()
    cat = Catalog.load(paths)
    for model in cat.models.values():
        v = cat.view(model)
        flag = "ok" if v["ok"] else "MISSING: " + "; ".join(v["problems"])
        nicks = f" ({', '.join(model.nicknames)})" if model.nicknames else ""
        print(f"{model.id}{nicks}  {v['size_bytes'] / 1024**3:.1f} GB  {flag}")
