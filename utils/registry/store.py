"""The models registry (architecture §8): `data/models/registry.json`, read and written here.

- **Storage:** loaded at startup and again whenever the file changes on disk (a
  `git pull`, a hand edit). Saved atomically with sorted keys and a 2-space indent.
  An entry that fails validation is kept as it is and reported, never dropped;
  an unreadable file makes the registry read-only until it is fixed, so a save
  can never overwrite it.
- **Status** is computed on every read from the files on disk (`stat`) and the
  stored checksums, never stored: `ok`, `missing`, `partial`, `unverified`,
  `checksum_mismatch` or `verifying` (brief §6.4 `Model`).
- **Deleting files** only touches the model's recorded files inside `data/models`,
  then removes the folders that became empty.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat as stat_mod
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from utils.paths import Paths, write_atomic
from utils.registry.model import ID_RE, VERSION, Entry, FileEntry, Patch, RegistryError, first_error, iso_ts

if TYPE_CHECKING:
    from utils.events import ActivityLog, Alerts, EventBus
    from utils.services import Service, ServiceManager

log = logging.getLogger("aihub.registry")

RUNNING = ("starting", "ready", "degraded", "stopping")
HOLDING = ("loading", "loaded", "unloading")


class Registry:
    def __init__(
        self,
        paths: Paths,
        bus: EventBus | None = None,
        activity: ActivityLog | None = None,
        alerts: Alerts | None = None,
    ) -> None:
        self.paths = paths
        self.bus, self.activity, self.alerts = bus, activity, alerts
        self.services: ServiceManager | None = None  # set by the lifespan: "used by" and the in-use rule
        self.entries: dict[str, Entry] = {}
        self.invalid: dict[str, Any] = {}  # entries that failed validation, saved back unchanged
        self.errors: list[str] = []  # why entries (or the whole file) were not loaded
        self.readonly: str | None = None  # set when registry.json can't be read: saves are refused
        self.progress: dict[str, float] = {}  # id → 0..1 while queued or being verified (verify.py)
        self._stamp: tuple[int, int] | None = None

    # ---- storage -------------------------------------------------------------

    @property
    def file(self) -> Path:
        return self.paths.registry

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            st = self.file.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def load(self) -> None:
        self.entries, self.invalid, self.errors, self.readonly = {}, {}, [], None
        self._stamp = self._file_stamp()
        if self._stamp is None:
            return  # no file yet: an empty registry
        try:
            doc = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self._refuse(f"registry.json can't be read ({e}); fix it or restore it from git")
            return
        if not isinstance(doc, dict) or not isinstance(doc.get("models", {}), dict):
            self._refuse('registry.json must be {"version": 1, "models": {...}}')
            return
        if doc.get("version", VERSION) != VERSION:
            self._refuse(f"registry.json is version {doc.get('version')!r}; this hub reads version {VERSION}")
            return
        for mid, raw in doc.get("models", {}).items():
            if not ID_RE.match(mid):
                self.invalid[mid] = raw
                self.errors.append(f"{mid}: not a valid model id (lowercase letters, digits, '.', '_' and '-')")
                continue
            try:
                self.entries[mid] = Entry.model_validate(raw)
            except ValidationError as e:
                self.invalid[mid] = raw
                self.errors.append(f"{mid}: {first_error(e)}")
        for err in self.errors:
            log.warning("registry.json: %s", err)

    def _refuse(self, why: str) -> None:
        self.readonly = why
        self.errors = [why]
        log.error("%s", why)

    def refresh(self) -> None:
        """Reload when registry.json changed on disk since it was last read or written."""
        if self._file_stamp() != self._stamp:
            self.load()

    def save(self) -> None:
        if self.readonly:
            raise RegistryError(409, "registry_invalid", self.readonly)
        models = {mid: e.dump() for mid, e in self.entries.items()}
        models.update(self.invalid)
        doc = {"version": VERSION, "models": models}
        write_atomic(self.file, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        self._stamp = self._file_stamp()

    def entry(self, model_id: str) -> Entry:
        self.refresh()
        e = self.entries.get(model_id)
        if e is None:
            raise RegistryError(404, "model_not_found", f'No model "{model_id}" in the registry')
        return e

    # ---- paths ---------------------------------------------------------------

    def abs(self, rel: str) -> Path:
        return self.paths.models / rel

    def inside(self, rel: str) -> Path | None:
        """`data/models/<rel>`, or None when a folder on the way leads out of data/models (a symlink)."""
        p = self.abs(rel)
        try:
            parent = p.parent.resolve()
        except OSError:
            return None
        root = self.paths.models.resolve()
        return p if parent == root or parent.is_relative_to(root) else None

    # ---- the Model view (brief §6.4) -----------------------------------------

    def view(self, model_id: str, e: Entry | None = None) -> dict[str, Any]:
        e = e or self.entry(model_id)
        files, problems = [], []
        size = 0
        n_exist = n_missing = n_partial = n_mismatch = n_verified = 0
        for f in e.files:
            fv, prob, state = self._file(f)
            files.append(fv)
            if prob:
                problems.append(prob)
            size += fv["size_bytes"] or 0
            if fv["exists"]:
                n_exist += 1
            if state == "missing":
                n_missing += 1
            elif state == "partial":
                n_partial += 1
            elif state == "mismatch":
                n_mismatch += 1
            elif state == "verified":
                n_verified += 1
        if not e.files:
            problems.append("No files are listed for this model")
        if model_id in self.progress:
            status = "verifying"
        elif n_exist == 0 and n_partial == 0:
            status = "missing"
        elif n_missing or n_partial:
            status = "partial"
        elif n_mismatch:
            status = "checksum_mismatch"
        elif n_verified == len(e.files):
            status = "ok"
        else:
            status = "unverified"
        out: dict[str, Any] = {
            "id": model_id,
            "name": e.name,
            "kind": e.kind,
            "format": e.format,
            "services": self.users(e),
            "path": e.path,
            "files": files,
            "size_bytes": size,
            "status": status,
            "problems": problems,
            "source": e.source.model_dump(exclude_none=True) if e.source else None,
            "added_ts": iso_ts(e.added) or 0,
            "tags": e.tags,
            "notes": e.notes,
        }
        if status == "verifying":
            out["progress"] = round(self.progress[model_id], 4)
        return out

    def _file(self, f: FileEntry) -> tuple[dict[str, Any], str | None, str]:
        """(the file's view, a problem or None, missing | partial | mismatch | verified | unverified)."""
        p = self.abs(f.path)
        try:
            st = p.stat()  # follows symlinks (hf-cache snapshots link to blobs)
            exists = stat_mod.S_ISREG(st.st_mode)
        except OSError:
            st, exists = None, False
        out = {"path": f.path, "role": f.role, "size_bytes": f.size_bytes, "exists": exists, "sha256": f.sha256, "verified": False}
        if not exists or st is None:
            part = p.with_name(p.name + ".part")
            if part.is_file():
                got = part.stat().st_size
                of = f" of {_gb(f.size_bytes)}" if f.size_bytes else ""
                return out, f"Downloading: {f.path} ({_gb(got)}{of} so far)", "partial"
            if p.exists():
                return out, f"Not a file: {f.path}", "missing"
            return out, f"File not found: {f.path}", "missing"
        out["size_bytes"] = st.st_size
        if f.size_bytes is not None and st.st_size != f.size_bytes:
            if st.st_size < f.size_bytes:
                return out, f"Incomplete: {f.path} is {_gb(st.st_size)} of {_gb(f.size_bytes)}", "partial"
            return out, f"Changed size: {f.path} was {_gb(f.size_bytes)}, now {_gb(st.st_size)}", "partial"
        if f.actual_sha256:
            return out, f"Checksum mismatch: sha256 of {f.path} is {f.actual_sha256[:12]}…, expected {(f.sha256 or '')[:12]}…", "mismatch"
        verified_ts = iso_ts(f.verified_at)
        if f.sha256 and verified_ts is not None:
            if st.st_mtime > verified_ts + 1:
                return out, f"Changed since it was verified: {f.path}", "unverified"
            out["verified"] = True
            return out, None, "verified"
        return out, None, "unverified"

    def list(self, kind: str | None = None, service: str | None = None, status: str | None = None, q: str | None = None) -> dict[str, Any]:
        self.refresh()
        views = [self.view(mid, e) for mid, e in sorted(self.entries.items())]
        by_kind: dict[str, dict[str, int]] = {}
        for v in views:
            k = by_kind.setdefault(v["kind"], {"count": 0, "size_bytes": 0})
            k["count"] += 1
            k["size_bytes"] += _on_disk(v)
        totals = {"count": len(views), "size_bytes": sum(_on_disk(v) for v in views), "by_kind": by_kind}
        kinds = {k for k in (kind or "").split(",") if k}
        needle = (q or "").strip().lower()
        shown = [
            v for v in views
            if (not kinds or v["kind"] in kinds)
            and (not service or service in v["services"])
            and (not status or v["status"] == status)
            and (not needle or needle in " ".join([v["id"], v["name"], v["path"], *v["tags"]]).lower())
        ]
        try:
            du = shutil.disk_usage(self.paths.models)
            disk = {"free_bytes": du.free, "total_bytes": du.total}
        except OSError:
            disk = {"free_bytes": 0, "total_bytes": 0}
        return {"models": shown, "totals": totals, "disk": disk}

    # ---- used by, in use -------------------------------------------------------

    def users(self, e: Entry) -> list[str]:
        """The mods that use this model: its explicit `services` list."""
        return list(e.services)

    def blocking(self, e: Entry) -> list[Service]:
        """Mods using the model that may have its files open: loading, loaded, unloading or busy
        (a running mod without a [memory] section counts as loaded)."""
        mgr = self.services
        if mgr is None:
            return []
        out = []
        for sid in self.users(e):
            svc = mgr.services.get(sid)
            if svc is None or svc.state not in RUNNING:
                continue
            if svc.load in HOLDING or svc.busy or svc.in_flight or svc.load == "n/a":
                out.append(svc)
        return out

    # ---- changes -------------------------------------------------------------

    def publish(self, model_id: str) -> None:
        if self.bus and model_id in self.entries:
            self.bus.publish({"type": "model", "model": self.view(model_id)})

    async def update(self, model_id: str, patch: Patch) -> dict[str, Any]:
        e = self.entry(model_id)
        data = e.dump()
        data.update(patch.model_dump(exclude_unset=True))
        try:
            new = Entry.model_validate(data)
        except ValidationError as x:
            raise RegistryError(422, "invalid_request", first_error(x)) from None
        self.entries[model_id] = new
        self.save()
        self.publish(model_id)
        return self.view(model_id)

    async def delete(self, model_id: str, files: bool = False) -> None:
        e = self.entry(model_id)
        if files:
            users = self.blocking(e)
            if users:
                names = ", ".join(s.mod.name for s in users)
                verb = "is" if len(users) == 1 else "are"
                raise RegistryError(409, "model_in_use", f"{names} {verb} running and {'uses' if len(users) == 1 else 'use'} {e.name}. Stop or unload it first.", {"services": [s.id for s in users]})
        if self.readonly:
            raise RegistryError(409, "registry_invalid", self.readonly)
        self.on_delete(model_id)
        failed: list[str] = []
        if files:
            failed = self._delete_files(e)
        if failed:
            self.publish(model_id)
            raise RegistryError(500, "hub_error", f"Couldn't delete every file of {e.name}: " + "; ".join(failed), {"failed": failed})
        del self.entries[model_id]
        self.save()
        if self.bus:
            self.bus.publish({"type": "model_deleted", "id": model_id})
        if self.activity:
            await self.activity.add(f"Removed {e.name} from the registry" + (" and deleted its files" if files else ""), route="#/models")
        self.changed()

    def on_delete(self, model_id: str) -> None:
        """Hook: verify.py cancels a pending or running verification."""

    def changed(self) -> None:
        """Hook: alerts.py recomputes the registry alerts."""

    def _delete_files(self, e: Entry) -> list[str]:
        """Delete the recorded files (a symlink's target too, when it lies inside the model's own
        folder, e.g. hf-cache blobs), then the folders left empty. Returns what failed."""
        root = self.paths.models.resolve()
        own = self.abs(e.path)
        own_real = own.resolve() if own.is_dir() else None
        failed: list[str] = []
        parents: set[Path] = set()
        for f in e.files:
            p = self.inside(f.path)
            if p is None:
                failed.append(f"{f.path}: leads outside data/models")
                continue
            try:
                if p.is_symlink():
                    target = p.resolve()
                    p.unlink()
                    if own_real and target.is_file() and target.is_relative_to(own_real) and target.is_relative_to(root):
                        target.unlink()
                        parents.add(target.parent)
                elif p.is_file():
                    p.unlink()
                elif p.exists():
                    failed.append(f"{f.path}: not a file")
            except OSError as x:
                failed.append(f"{f.path}: {x.strerror or x}")
            parents.add(p.parent)
        if own_real and not own.is_symlink() and own_real.is_relative_to(root):
            for d in _dirs_bottom_up(own_real):
                _rmdir(d)
            parents.add(own_real)
        for d in parents:
            _prune_up(d, root)
        return failed


def _dirs_bottom_up(top: Path) -> Iterator[Path]:
    for dirpath, _dirs, _files in os.walk(top, topdown=False):
        yield Path(dirpath)


def _rmdir(d: Path) -> bool:
    try:
        d.rmdir()  # only succeeds when empty
        return True
    except OSError:
        return False


def _prune_up(d: Path, root: Path) -> None:
    """Remove `d` and its parents while they are empty, stopping at data/models."""
    try:
        d = d.resolve()
    except OSError:
        return
    while d != root and d.is_relative_to(root):
        if d.exists() and not _rmdir(d):
            return
        d = d.parent


def _on_disk(v: dict[str, Any]) -> int:
    return sum(f["size_bytes"] or 0 for f in v["files"] if f["exists"])


def _gb(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n} B"
