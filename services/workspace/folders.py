"""Workspace folders, their levels, and the hard limits on paths (plan 27.1, 33).

A folder is `{id, path, level, allow_bypass}`, kept in an environment (`environments.py`, plan 34;
Phase 27 kept one list in `folders.json`, now Default). The four levels, lowest first: `read` ·
`edit` (files change in place) · `run` (commands in the sandbox) · `run_net` (the sandbox with full
internet). New folders start at `read`. A call sees the folders of its chat's environment plus those
the user allowed in that chat (`Folders.view(origin)`). A project chat's call names several environments
(`origin.environments`, primary first; plan projects 2.1) and sees all their folders, each at the highest
level any of them gives it.

**Caps.** The GAIFA folder and its `data/models/` never go above `read`, whatever is asked: a
folder inside either is capped, and no write anywhere may land inside them (a folder that
*contains* GAIFA keeps its level for its other files).

**Hard limits** (nothing lifts them; `resolve` raises `Refused`):
- a path outside the folder, or through a symlink out of it;
- secret files (`.env`, `*.pem`, `id_*`, `*credential*`, `secrets*`, as any path part) unless
  the user named the file in their message (`named`);
- `.git/` written by anything but the git tools;
- files over 2 MB, unless named (reads); binaries (reads).
"""

from __future__ import annotations

import fnmatch
import os
import re
import secrets as _secrets
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
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
    granted: bool = False      # allowed in this chat only (plan 34), not a folder of the environment

    def public(self, caps: Caps) -> dict[str, Any]:
        cap, why = caps.cap_of(Path(self.path))
        if self.granted:
            cap, why = "read", why or "allowed in this chat only, at Read: add it to the environment for more"
        level = self.level if at_least(cap, self.level) else cap
        return {**asdict(self), "name": self.name or Path(self.path).name, "level": level, "max_level": cap,
                "capped": why, "level_word": LEVEL_WORD[level], "exists": Path(self.path).is_dir(),
                "allow_bypass": self.allow_bypass and level != "read"}


class Caps:
    """The GAIFA folder and its models, which stay at Read."""

    def __init__(self, gaifa_root: Path | None, models: Path | None) -> None:
        self.roots: list[tuple[Path, str]] = []
        for p, why in ((models, "the models folder (data/models/) stays at Read"),
                       (gaifa_root, "the GAIFA folder stays at Read: the agent may read and explain it, never change it")):
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


def check_folder(path: str) -> Path:
    """A folder the user adds on the Workspace page: an existing folder, not `/`, the home folder or above it."""
    real = Path(os.path.realpath(os.path.expanduser(path)))
    if not real.is_dir():
        raise Refused("not_a_folder", f"{path} isn't a folder", "give the full path of an existing folder", 422)
    home = Path(os.path.realpath(Path.home()))
    if real == Path("/") or real == home or inside(home, real):
        raise Refused("too_broad", f"{real} is too broad for a workspace", "add a project folder instead", 422)
    return real


def grant_roots() -> list[Path]:
    """Where a folder the agent asks for may be (plan 34): the user's home, and mounted drives."""
    user = os.environ.get("USER") or Path.home().name
    return [Path(os.path.realpath(p)) for p in (Path.home(), Path("/mnt"), Path("/media") / user, Path("/run/media") / user)]


def grantable(path: str) -> Path:
    """A folder the agent may ask the user for (plan 34), or Refused: the Workspace page's checks, and it must be
    in the user's home (or a mounted drive), with no hidden or secret-looking folder on the way (~/.ssh,
    ~/.config, a `secrets` folder). Symlinks are followed first, so one can't lead out."""
    raw = os.path.expanduser(path.strip())
    if not raw.startswith("/") or "\0" in raw:
        raise Refused("bad_path", f"{path} isn't a full path", "pass the folder's full path (/home/… or ~/…)", 422)
    real = Path(os.path.realpath(raw))
    if not real.exists():
        raise Refused("not_found", f"{path} doesn't exist", "check the path with the user", 404)
    if not real.is_dir():
        raise Refused("not_a_folder", f"{path} is a file, not a folder",
                      "ask for the folder it is in, then read the file with path=", 422)
    check_folder(str(real))
    root = next((r for r in grant_roots() if inside(real, r) and real != r), None)
    if root is None:
        raise Refused("not_grantable", f"{real} is outside your home folder; the agent only asks for folders in it",
                      "the user can add it on the Workspace page")
    rel = real.relative_to(root)
    if any(p.startswith(".") for p in rel.parts) or is_secret(str(rel)):
        raise Refused("not_grantable", f"{real} is a hidden or secret-looking folder; the agent doesn't ask for those",
                      "the user can add it on the Workspace page")
    return real


def new_id(base: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-.") or "folder"
    slug = slug[:40]
    if slug not in taken:
        return slug
    for i in range(2, 100):
        if f"{slug}-{i}" not in taken:
            return f"{slug}-{i}"
    return f"{slug}-{_secrets.token_hex(3)}"


class Folders:
    """The folders one call may use (plan 34): those of the chat's environment (`origin.environment`,
    else Default) plus the folders the user allowed in this chat (`origin.folders`, which only the hub
    sets, from the chat's folder grants; always Read here). `view(origin)` makes one per call; the
    instance the server keeps is Default's view, which the Phase 27 `/v1/folders` routes use."""

    def __init__(self, state: Path | None, caps: Caps, envs: Any = None, env: str | None = None,
                 granted: list[Any] | tuple[Any, ...] = (), env_ids: list[str] | None = None) -> None:
        from environments import Environments
        self.caps = caps
        self.envs = envs if envs is not None else Environments(state or Path("."), caps)
        self.env_id = env
        self.env_ids = list(env_ids or [])      # several environments, primary first (plan projects 2.1)
        self.granted_raw = list(granted) if isinstance(granted, (list, tuple)) else []
        self._lock = threading.Lock()

    def view(self, origin: dict[str, Any] | None) -> Folders:
        """The call's folders: `origin.environments` (ids, primary first: a project chat's, plan projects 2.1) wins over
        `origin.environment`; then the folders allowed in the chat."""
        o = origin if isinstance(origin, dict) else {}
        many = o.get("environments")
        ids = list(dict.fromkeys(str(e) for e in many if isinstance(e, str) and e))[:16] if isinstance(many, list) else []
        if ids:
            return Folders(None, self.caps, self.envs, ids[0], o.get("folders") or [], env_ids=ids)
        env = o.get("environment")
        return Folders(None, self.caps, self.envs, str(env) if isinstance(env, str) and env else None, o.get("folders") or [])

    @property
    def environment(self) -> Any:
        """The primary environment (the only one, unless the origin named several)."""
        return self.envs.of(self.env_id)

    @property
    def environments(self) -> list[Any]:
        """Every environment the call uses, primary first; ids that name none are skipped (all unknown: the primary's
        fallback, Default, as for one)."""
        if len(self.env_ids) < 2:
            return [self.environment]
        known = {e.id: e for e in self.envs.all()}
        found = [known[i] for i in self.env_ids if i in known]
        return found or [self.environment]

    def _env_folders(self) -> list[Folder]:
        """The union of the environments' folders; a folder in more than one gets the highest level any of them gives it
        (one path has one id everywhere, environments.py)."""
        envs = self.environments
        if len(envs) == 1:
            return list(envs[0].folders)
        best: dict[str, Folder] = {}
        for e in envs:
            for f in e.folders:
                cur = best.get(f.id)
                if cur is None or LEVELS.index(f.level) > LEVELS.index(cur.level):
                    best[f.id] = f
        return list(best.values())

    @property
    def named(self) -> Any:
        """What messages call the call's environment: the primary one, or all of them by name."""
        envs = self.environments
        if len(envs) == 1:
            return envs[0]
        return SimpleNamespace(id=envs[0].id, name=" + ".join(e.name for e in envs))

    def _granted(self, env_folders: list[Folder]) -> list[Folder]:
        """The chat's folders from the origin, checked again (grantable, not already in the environment), at Read."""
        out: list[Folder] = []
        ids = self.envs.ids()
        mine = {os.path.realpath(f.path) for f in env_folders}
        taken = set(ids) | {f.id for f in env_folders}
        for g in self.granted_raw[:50]:
            path = g.get("path") if isinstance(g, dict) else g
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            try:
                real = grantable(path)
            except Refused:
                continue
            if str(real) in mine:
                continue
            fid = next((i for i, p in ids.items() if p == str(real)), None) or new_id(real.name, taken)
            taken.add(fid)
            mine.add(str(real))
            out.append(Folder(fid, str(real), "read", False, "", granted=True))
        return out

    def _load(self) -> list[Folder]:
        env = self._env_folders()
        return [*env, *self._granted(env)]

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
        if real:
            for f in folders:
                if inside(Path(real), Path(os.path.realpath(f.path))):
                    rel = os.path.relpath(real, os.path.realpath(f.path))
                    raise Refused("inside_folder", f"{ref} is inside the folder {f.id} ({f.path})",
                                  f"pass folder={f.id!r} and path={rel!r}", 404)
        known = ", ".join(f.id for f in folders) or "none yet"
        env = self.named
        fix = ("pass its full path as `folder` to workspace_tree or workspace_read: the user is asked to let this chat "
               "read it (editing or running there needs it in the environment at a higher level, on the Workspace page)"
               if real else "call workspace_folders to see them; the user adds folders on the Workspace page")
        raise Refused("unknown_folder", f"{ref!r} isn't one of this chat's folders (environment {env.name}: {known})", fix, 404)

    def ask_for(self, ref: str) -> dict[str, Any] | None:
        """A path the model named that isn't one of this chat's folders: what the card asks for (plan 34),
        or None when `ref` isn't a path. Refused when the folder can never be asked for."""
        ref = (ref or "").strip()
        if not ref.startswith(("/", "~")):
            return None
        real = grantable(ref)
        cap, why = self.caps.cap_of(real)
        env = self.environment
        return {"path": str(real), "level": "read", "max_level": cap, **({"capped": why} if why else {}),
                "environment": {"id": env.id, "name": env.name}}

    def level(self, f: Folder) -> str:
        cap, _ = self.caps.cap_of(Path(f.path))
        return f.level if at_least(cap, f.level) else cap

    def add(self, path: str, level: str = "read", allow_bypass: bool = False, fid: str | None = None,
            name: str = "") -> Folder:
        return self.envs.add_folder(self.environment.id, path, level, allow_bypass, fid, name)

    def update(self, fid: str, level: str | None = None, allow_bypass: bool | None = None,
               name: str | None = None) -> Folder:
        return self.envs.update_folder(self.environment.id, fid, level, allow_bypass, name)

    def remove(self, fid: str) -> bool:
        return self.envs.remove_folder(self.environment.id, fid)

    def root_of(self, fid: str) -> str | None:
        """A folder id's real path in any environment (checkpoints record the id)."""
        return self.envs.ids().get(fid)

    # ---- paths -----------------------------------------------------------------------------

    def resolve(self, f: Folder, rel: str | None, *, write: bool = False, named: list[str] | None = None,
                git: bool = False, read_file: bool = False) -> tuple[Path, str]:
        """(absolute path, path relative to the folder) for `rel`, or Refused (the hard limits).

        `write`: the call changes it (`.git/`, GAIFA and the models are refused); `git`: the git tools
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
