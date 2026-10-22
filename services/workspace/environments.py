"""Environments (plan Phase 34): named sets of folders a chat works in, after Claude's.

`$WORKSPACE_STATE/environments.json` holds `{"environments": [{id, name, folders, created, updated}]}`.
Each folder is `{id, path, level, allow_bypass, name}` as in Phase 27, and its level belongs to that
environment: a folder can be Read in one and Edit in another. The first environment is **Default**
(`id = "default"`), which can be renamed but not deleted; a chat without an environment, or with one
that was deleted, uses it. **None** (`id = "none"`, plan 42.5) is built in and never stored: no folders, listed first, and it
can't be renamed, deleted or given folders; a chat in it reads only the folders allowed in it (each asked for).

**Migration.** On first load, the Phase 27 `folders.json` becomes Default (ids and levels kept); the
old file is left as it was.

**Ids.** A folder's id is unique across environments, and one path has one id everywhere (adding a
folder that another environment has reuses its id), so a checkpoint's folder id finds its folder
whichever environment the chat used.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from folders import ID_RE, LEVEL_WORD, LEVELS, Caps, Folder, Refused, at_least, check_folder, new_id

DEFAULT = "default"
NONE = "none"           # built in: no folders (plan 42.5)
NONE_REFUSED = ("none", "None has no folders, so it can't be renamed, deleted or given folders",
                "make an environment for that (New environment)", 422)
ENV_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
FOLDER_KEYS = ("id", "path", "level", "allow_bypass", "name")


@dataclass
class Env:
    id: str
    name: str
    folders: list[Folder] = field(default_factory=list)
    created: float = 0.0
    updated: float = 0.0

    def public(self, caps: Caps) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "default": self.id == DEFAULT, "none": self.id == NONE, "created": self.created,
                "updated": self.updated, "folders": [f.public(caps) for f in self.folders]}

    def raw(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "created": self.created, "updated": self.updated,
                "folders": [{k: getattr(f, k) for k in FOLDER_KEYS} for f in self.folders]}


def _folder(d: dict[str, Any]) -> Folder | None:
    try:
        return Folder(**{k: d[k] for k in FOLDER_KEYS if k in d})
    except TypeError:
        return None


class Environments:
    """environments.json, read on every call (the page, the tools and the preflight see the same sets)."""

    def __init__(self, state: Path, caps: Caps) -> None:
        self.file = state / "environments.json"
        self.legacy = state / "folders.json"
        self.caps = caps
        self._lock = threading.RLock()

    # ---- the file ----------------------------------------------------------------------------

    def _load(self) -> list[Env]:
        try:
            raw = json.loads(self.file.read_text())
        except FileNotFoundError:
            return self._migrate()
        except (OSError, ValueError):
            raw = {}
        envs = []
        for e in raw.get("environments", []) if isinstance(raw, dict) else []:
            if not isinstance(e, dict) or not ENV_ID.match(str(e.get("id") or "")):
                continue
            fs = [f for f in (_folder(x) for x in e.get("folders") or [] if isinstance(x, dict)) if f is not None]
            envs.append(Env(e["id"], str(e.get("name") or e["id"])[:64], fs, float(e.get("created") or 0), float(e.get("updated") or 0)))
        if not any(e.id == DEFAULT for e in envs):
            envs.insert(0, Env(DEFAULT, "Default", [], time.time(), time.time()))
        return envs

    def _migrate(self) -> list[Env]:
        """Phase 27's folders.json becomes Default (written once, so the ids stay)."""
        folders: list[Folder] = []
        try:
            raw = json.loads(self.legacy.read_text())
            folders = [f for f in (_folder(x) for x in raw.get("folders", []) if isinstance(x, dict)) if f is not None]
        except (OSError, ValueError, AttributeError):
            pass
        now = time.time()
        envs = [Env(DEFAULT, "Default", folders, now, now)]
        if folders:
            with self._lock:
                if not self.file.exists():
                    self._save(envs)
        return envs

    def _save(self, envs: list[Env]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.file.parent, prefix=".environments.")
        with os.fdopen(fd, "w") as f:
            json.dump({"environments": [e.raw() for e in envs]}, f, indent=2)
        os.replace(tmp, self.file)

    # ---- environments ------------------------------------------------------------------------

    def all(self) -> list[Env]:
        """None first, then the stored ones."""
        return [_none(), *self._load()]

    def get(self, eid: str | None) -> Env:
        """An environment by id; unknown → 404."""
        for e in self.all():
            if e.id == eid:
                return e
        raise Refused("unknown_environment", f"there is no environment {eid!r}", "pick one on the Workspace page", 404)

    def of(self, eid: str | None) -> Env:
        """The chat's environment: its id, or Default when it has none or it was deleted."""
        if eid == NONE:
            return _none()
        envs = self._load()
        return next((e for e in envs if eid and e.id == eid), None) or next(e for e in envs if e.id == DEFAULT)

    def create(self, name: str, eid: str | None = None) -> Env:
        name = _name(name)
        with self._lock:
            envs = self._load()
            if any(e.name.lower() == name.lower() for e in envs) or name.lower() == NONE:
                raise Refused("exists", f"there is already an environment called {name!r}", "pick another name", 409)
            eid = eid or _slug(name, {e.id for e in envs} | {NONE})
            if not ENV_ID.match(eid) or eid == NONE or any(e.id == eid for e in envs):
                raise Refused("bad_id", f"{eid!r} is taken or isn't a valid id", "use lowercase letters, digits, . _ -", 422)
            now = time.time()
            env = Env(eid, name, [], now, now)
            envs.append(env)
            self._save(envs)
            return env

    def rename(self, eid: str, name: str) -> Env:
        name = _name(name)
        with self._lock:
            envs = self._load()
            env = _find(envs, eid)
            if any(e.name.lower() == name.lower() and e.id != eid for e in envs) or name.lower() == NONE:
                raise Refused("exists", f"there is already an environment called {name!r}", "pick another name", 409)
            env.name, env.updated = name, time.time()
            self._save(envs)
            return env

    def delete(self, eid: str) -> None:
        if eid == NONE:
            raise Refused(*NONE_REFUSED)
        if eid == DEFAULT:
            raise Refused("default", "Default can't be deleted (chats without an environment use it)", "rename it instead", 422)
        with self._lock:
            envs = self._load()
            _find(envs, eid)
            self._save([e for e in envs if e.id != eid])

    # ---- folders in an environment -----------------------------------------------------------

    def ids(self, envs: list[Env] | None = None) -> dict[str, str]:
        """Every folder id → its real path, across environments."""
        return {f.id: os.path.realpath(f.path) for e in (envs or self._load()) for f in e.folders}

    def add_folder(self, eid: str, path: str, level: str = "read", allow_bypass: bool = False, fid: str | None = None,
                   name: str = "") -> Folder:
        real = check_folder(path)
        if level not in LEVELS:
            raise Refused("bad_level", f"level must be one of {', '.join(LEVELS)}", "", 422)
        cap, why = self.caps.cap_of(real)
        if not at_least(cap, level):
            raise Refused("capped", f"{real} can't go above {LEVEL_WORD[cap]}: {why}", "", 422)
        with self._lock:
            envs = self._load()
            env = _find(envs, eid)
            if any(os.path.realpath(f.path) == str(real) for f in env.folders):
                raise Refused("exists", f"{real} is already in {env.name}", "change its level instead", 409)
            ids = self.ids(envs)
            same = next((i for i, p in ids.items() if p == str(real)), None)       # one path, one id everywhere
            if same is not None and fid not in (None, same):
                raise Refused("bad_id", f"{real} is {same!r} in another environment", f"use {same!r}", 422)
            fid = same or fid or new_id(real.name, set(ids))
            if not ID_RE.match(fid) or (same is None and fid in ids):
                raise Refused("bad_id", f"{fid!r} is taken or isn't a valid id", "use lowercase letters, digits, . _ -", 422)
            f = Folder(fid, str(real), level, bool(allow_bypass) and level != "read", name.strip()[:64])
            env.folders.append(f)
            env.updated = time.time()
            self._save(envs)
            return f

    def update_folder(self, eid: str, fid: str, level: str | None = None, allow_bypass: bool | None = None,
                      name: str | None = None) -> Folder:
        with self._lock:
            envs = self._load()
            env = _find(envs, eid)
            f = next((x for x in env.folders if x.id == fid), None)
            if f is None:
                raise Refused("unknown_folder", f"there is no folder {fid!r} in {env.name}", "", 404)
            if level is not None:
                if level not in LEVELS:
                    raise Refused("bad_level", f"level must be one of {', '.join(LEVELS)}", "", 422)
                cap, why = self.caps.cap_of(Path(f.path))
                if not at_least(cap, level):
                    raise Refused("capped", f"{f.path} can't go above {LEVEL_WORD[cap]}: {why}", "", 422)
                f.level = level
            if allow_bypass is not None:
                f.allow_bypass = bool(allow_bypass)
            if name is not None:
                f.name = name.strip()[:64]
            env.updated = time.time()
            self._save(envs)
            return f

    def remove_folder(self, eid: str, fid: str) -> bool:
        with self._lock:
            envs = self._load()
            env = _find(envs, eid)
            kept = [f for f in env.folders if f.id != fid]
            if len(kept) == len(env.folders):
                return False
            env.folders, env.updated = kept, time.time()
            self._save(envs)
            return True


def _none() -> Env:
    return Env(NONE, "None", [], 0.0, 0.0)


def _find(envs: list[Env], eid: str) -> Env:
    if eid == NONE:
        raise Refused(*NONE_REFUSED)
    env = next((e for e in envs if e.id == eid), None)
    if env is None:
        raise Refused("unknown_environment", f"there is no environment {eid!r}", "pick one on the Workspace page", 404)
    return env


def _name(name: str) -> str:
    name = " ".join(str(name or "").split())[:64]
    if not name:
        raise Refused("bad_name", "an environment needs a name", "", 422)
    return name


def _slug(name: str, taken: set[str]) -> str:
    return new_id(name, taken)
