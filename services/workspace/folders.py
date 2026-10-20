"""Workspace folders, their levels, and the hard limits on paths (plan 27.1).

A folder is `{id, path, level, allow_bypass}`, kept in `$WORKSPACE_STATE/folders.json`. The four
levels, lowest first: `read` · `edit` (files change in place) · `run` (commands in the sandbox) ·
`run_net` (the sandbox with full internet). New folders start at `read`.

**Caps.** The AIHub folder and its `data/models/` never go above `read`, whatever is asked: a
folder inside either is capped, and no write anywhere may land inside them (a folder that
*contains* AIHub keeps its level for its other files).

**Hard limits** (nothing lifts them; `resolve` raises `Refused`):
- a path outside the folder, or through a symlink out of it;
- secret files (`.env`, `*.pem`, `id_*`, `*credential*`, `secrets*`, as any path part) unless
  the user named the file in their message (`named`);
- `.git/` written by anything but the git tools;
- files over 2 MB, unless named (reads); binaries (reads).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import secrets as _secrets
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LEVELS = ("read", "edit", "run", "run_net")
LEVEL_WORD = {"read": "Read", "edit": "Edit", "run": "Run", "run_net": "Run + network"}
SECRET_GLOBS = (".env", "*.pem", "id_*", "*credential*", "secrets*")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             ".tox", ".cache", "dist", "build", ".next", "target"}
MAX_BYTES = 2 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")


class Refused(Exception):
    """A hard limit or the folder's level: `code`, `detail`, `fix` reach the model and the card."""

    def __init__(self, code: str, detail: str, fix: str = "", status: int = 403) -> None:
        super().__init__(detail)
        self.code, self.detail, self.fix, self.status = code, detail, fix, status

    def body(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "fix": self.fix}


def at_least(level: str, need: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(need)


def inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def is_secret(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(part.lower(), g) for part in Path(rel).parts for g in SECRET_GLOBS)


def is_binary(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return False


def was_named(rel: str, named: list[str] | tuple[str, ...] | None) -> bool:
    """The user's message named this file (its path relative to the folder, or its name)."""
    if not named:
        return False
    rel = rel.strip("/")
    names = [n.strip().strip("/").removeprefix("./") for n in named if n and n.strip()]
    return any(n in (rel, Path(rel).name) or rel.endswith("/" + n) for n in names)


@dataclass
class Folder:
    id: str
    path: str
    level: str = "read"
    allow_bypass: bool = False
    name: str = ""

    def public(self, caps: Caps) -> dict[str, Any]:
        cap, why = caps.cap_of(Path(self.path))
        level = self.level if at_least(cap, self.level) else cap
        return {**asdict(self), "name": self.name or Path(self.path).name, "level": level, "max_level": cap,
                "capped": why, "level_word": LEVEL_WORD[level], "exists": Path(self.path).is_dir(),
                "allow_bypass": self.allow_bypass and level != "read"}


class Caps:
    """The AIHub folder and its models, which stay at Read."""

    def __init__(self, aihub_root: Path | None, models: Path | None) -> None:
        self.roots: list[tuple[Path, str]] = []
        for p, why in ((models, "the models folder (data/models/) stays at Read"),
                       (aihub_root, "the AIHub folder stays at Read: the agent may read and explain it, never change it")):
            if p is not None:
                self.roots.append((Path(os.path.realpath(p)), why))

    def cap_of(self, folder: Path) -> tuple[str, str | None]:
        real = Path(os.path.realpath(folder))
        for root, why in self.roots:
            if inside(real, root):
                return "read", why
        return "run_net", None

    def protected(self, target: Path) -> str | None:
        """Why a write to `target` (resolved) is refused, or None."""
        for root, why in self.roots:
            if inside(target, root):
                return why
        return None


class Folders:
    """folders.json, read on every call (the page and the tools see the same list)."""

    def __init__(self, state: Path, caps: Caps) -> None:
        self.file = state / "folders.json"
        self.caps = caps
        self._lock = threading.Lock()

    def _load(self) -> list[Folder]:
        try:
            raw = json.loads(self.file.read_text())
        except (OSError, ValueError):
            return []
        out = []
        for f in raw.get("folders", []):
            try:
                out.append(Folder(**{k: f[k] for k in ("id", "path", "level", "allow_bypass", "name") if k in f}))
            except TypeError:
                continue
        return out

    def _save(self, folders: list[Folder]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.file.parent, prefix=".folders.")
        with os.fdopen(fd, "w") as f:
            json.dump({"folders": [asdict(x) for x in folders]}, f, indent=2)
        os.replace(tmp, self.file)

    def list(self) -> list[Folder]:
        return self._load()

    def public(self) -> list[dict[str, Any]]:
        return [f.public(self.caps) for f in self._load()]

    def get(self, ref: str) -> Folder:
        """A folder by id, name or path (as the model may pass any of them)."""
        ref = (ref or "").strip()
        folders = self._load()
        for f in folders:
            if ref == f.id:
                return f
        real = os.path.realpath(os.path.expanduser(ref)) if ref.startswith(("/", "~")) else None
        for f in folders:
            if real and real == os.path.realpath(f.path):
                return f
        for f in folders:
            if ref.lower() == (f.name or Path(f.path).name).lower():
                return f
        known = ", ".join(f.id for f in folders) or "none yet"
        raise Refused("unknown_folder", f"there is no workspace folder {ref!r} (folders: {known})",
                      "call workspace_folders to see them; the user adds folders on the Workspace page", 404)

    def level(self, f: Folder) -> str:
        cap, _ = self.caps.cap_of(Path(f.path))
        return f.level if at_least(cap, f.level) else cap

    def add(self, path: str, level: str = "read", allow_bypass: bool = False, fid: str | None = None,
            name: str = "") -> Folder:
        real = Path(os.path.realpath(os.path.expanduser(path)))
        if not real.is_dir():
            raise Refused("not_a_folder", f"{path} isn't a folder", "give the full path of an existing folder", 422)
        if real == Path("/") or real == Path.home():
            raise Refused("too_broad", f"{real} is too broad for a workspace", "add a project folder instead", 422)
        with self._lock:
            folders = self._load()
            if any(os.path.realpath(f.path) == str(real) for f in folders):
                raise Refused("exists", f"{real} is already a workspace", "change its level instead", 409)
            fid = fid or self._new_id(real.name, folders)
            if not ID_RE.match(fid) or any(f.id == fid for f in folders):
                raise Refused("bad_id", f"{fid!r} is taken or isn't a valid id", "use lowercase letters, digits, . _ -", 422)
            f = Folder(fid, str(real), "read", False, name)
            folders.append(f)
            self._save(folders)
        if level != "read" or allow_bypass:
            f = self.update(fid, level=level, allow_bypass=allow_bypass)
        return f

    def update(self, fid: str, level: str | None = None, allow_bypass: bool | None = None,
               name: str | None = None) -> Folder:
        with self._lock:
            folders = self._load()
            f = next((x for x in folders if x.id == fid), None)
            if f is None:
                raise Refused("unknown_folder", f"there is no workspace folder {fid!r}", "", 404)
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
            self._save(folders)
            return f

    def remove(self, fid: str) -> bool:
        with self._lock:
            folders = self._load()
            kept = [f for f in folders if f.id != fid]
            if len(kept) == len(folders):
                return False
            self._save(kept)
            return True

    @staticmethod
    def _new_id(base: str, folders: list[Folder]) -> str:
        slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-.") or "folder"
        slug = slug[:40]
        taken = {f.id for f in folders}
        if slug not in taken:
            return slug
        for i in range(2, 100):
            if f"{slug}-{i}" not in taken:
                return f"{slug}-{i}"
        return f"{slug}-{_secrets.token_hex(3)}"

    # ---- paths -----------------------------------------------------------------------------

    def resolve(self, f: Folder, rel: str | None, *, write: bool = False, named: list[str] | None = None,
                git: bool = False, read_file: bool = False) -> tuple[Path, str]:
        """(absolute path, path relative to the folder) for `rel`, or Refused (the hard limits).

        `write`: the call changes it (`.git/`, AIHub and the models are refused); `git`: the git tools
        (which may write `.git/`); `read_file`: its bytes are read (size and binary rules)."""
        root = Path(os.path.realpath(f.path))
        if not root.is_dir():
            raise Refused("folder_missing", f"the folder {f.path} no longer exists", "ask the user to fix it on the Workspace page", 404)
        raw = (rel or ".").strip()
        if "\0" in raw:
            raise Refused("bad_path", "the path has a NUL byte", "", 422)
        p = Path(os.path.expanduser(raw))
        lexical = Path(os.path.normpath(p if p.is_absolute() else root / p))
        if not inside(lexical, root) and not inside(lexical, Path(f.path)):
            raise Refused("outside_folder", f"{raw} is outside the folder {f.path}",
                          "use a path inside the folder, relative to it")
        target = Path(os.path.realpath(lexical))
        if not inside(target, root):
            raise Refused("symlink_out", f"{raw} leads outside the folder through a symlink ({target})",
                          "only files inside the folder can be used")
        relp = "." if target == root else str(target.relative_to(root))
        if is_secret(relp) and not was_named(relp, named):
            raise Refused("secret_file", f"{relp} looks like a secret (keys, credentials, .env); it isn't read or changed "
                          "unless the user names it in their message", "ask the user to name the file if they want it used")
        parts = Path(relp).parts
        if write and ".git" in parts and not git:
            raise Refused("git_dir", f"{relp} is inside .git/; only the git tools change it", "use workspace_git_commit")
        if write:
            why = self.caps.protected(target)
            if why:
                raise Refused("protected", f"{relp}: {why}", "")
        if read_file and target.is_file():
            if target.stat().st_size > MAX_BYTES and not was_named(relp, named):
                raise Refused("too_large", f"{relp} is {target.stat().st_size // 1024} KB (the limit is 2 MB unless the user names it)",
                              "read a part with workspace_search, or ask the user to name the file", 413)
            if is_binary(target):
                raise Refused("binary", f"{relp} is a binary file", "it can't be read as text", 415)
        return target, relp

    def need(self, f: Folder, level: str, what: str) -> None:
        """The folder's level caps what can happen at all (plan 27, the decision order's step 2)."""
        have = self.level(f)
        if not at_least(have, level):
            cap, why = self.caps.cap_of(Path(f.path))
            fix = (why if not at_least(cap, level) else
                   f"ask the user to raise {f.id} to {LEVEL_WORD[level]} on the Workspace page")
            raise Refused("level", f"{what} needs the folder at {LEVEL_WORD[level]}; {f.id} is at {LEVEL_WORD[have]}", fix)


def skipped(name: str, is_dir: bool) -> bool:
    return is_dir and name in SKIP_DIRS
