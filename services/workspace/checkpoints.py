"""Checkpoints and undo (plan 27.3).

Before any change to a file, its previous bytes (or "didn't exist") are saved under
`$WORKSPACE_STATE/checkpoints/<thread>/<turn>/`: `entries.json` lists the changes in order, each
with the file's hash after the change; `NNN.bin` holds the bytes before it and `NNN.after` the
bytes the agent left (for the diff when a file changed since). Undo restores a
whole turn, newest change first, and refuses (with a diff) when a file has changed since outside
the agent. Kept 14 days or 2 GB in all, oldest turns first.
"""

from __future__ import annotations

import difflib
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from folders import Refused, inside

KEEP_S = 14 * 86400
KEEP_BYTES = 2 * 1024 ** 3
SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def sha(p: Path) -> str | None:
    """The file's hash, or None when it doesn't exist."""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return "dir"


def write_atomic(p: Path, data: bytes, mode: int | None = None, root: Path | None = None) -> None:
    """Write `p` through a temp file and a rename. `root` (a folder's real path): `p` must stay inside
    it, so the write goes through `parent_fd` (see there)."""
    if root is None:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".aihub")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            if mode is not None:
                os.chmod(tmp, mode)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return
    d = parent_fd(root, p, create=True)
    tmp = f".{p.name}.{secrets.token_hex(4)}.aihub"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=d)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                if mode is not None:
                    os.fchmod(f.fileno(), mode)
            os.replace(tmp, p.name, src_dir_fd=d, dst_dir_fd=d)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=d)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(d)


def unlink_in(root: Path, p: Path) -> None:
    """Delete `p` (a symlink itself, never what it points at) inside `root`, as `write_atomic`."""
    d = parent_fd(root, p, create=False)
    try:
        os.unlink(p.name, dir_fd=d)
    finally:
        os.close(d)


def parent_fd(root: Path, p: Path, create: bool) -> int:
    """`p`'s folder, opened from `root` down one folder at a time without following a symlink: a folder
    swapped for a symlink after the path was checked (a sandbox run at the same time, or since a
    checkpoint) can't send a write outside `root`. `create`: make missing folders on the way."""
    try:
        parts = p.parent.relative_to(root).parts
    except ValueError:
        raise _outside(p, root) from None
    d = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, dir_fd=d)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=d)
            os.close(d)
            d = nxt
    except OSError as e:
        os.close(d)
        if e.errno in (errno.ELOOP, errno.ENOTDIR) and _has_link(root, parts):
            raise _outside(p, root) from None
        raise
    return d


def _has_link(root: Path, parts: tuple[str, ...]) -> bool:
    return any(os.path.islink(root.joinpath(*parts[:i + 1])) for i in range(len(parts)))


def _outside(p: Path, root: Path) -> Refused:
    return Refused("symlink_out", f"{p} now leads outside the folder {root} (a folder on the way became a symlink)",
                   "only files inside the folder can be changed")


def diff(before: str, after: str, rel: str, rel_after: str | None = None, context: int = 3) -> str:
    a = before.splitlines(keepends=True)
    b = after.splitlines(keepends=True)
    out = "".join(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel_after or rel}", n=context))
    return out if out.endswith("\n") or not out else out + "\n\\ No newline at end of file\n"


def text_of(p: Path) -> str:
    try:
        return p.read_bytes().decode("utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return ""


def key(thread: str | None, turn: Any, call: str | None) -> tuple[str, str]:
    """(thread, turn) as folder names. A call without a chat is its own turn."""
    t = SAFE.sub("_", str(thread))[:64] if thread else "_direct"
    u = SAFE.sub("_", str(turn))[:64] if turn not in (None, "") else SAFE.sub("_", str(call or time.strftime("%Y%m%d-%H%M%S")))[:64]
    return t, u


class Checkpoints:
    def __init__(self, state: Path) -> None:
        self.root = state / "checkpoints"
        self._lock = threading.Lock()

    def _dir(self, thread: str, turn: str) -> Path:
        return self.root / thread / turn

    def entries(self, thread: str, turn: str) -> list[dict[str, Any]]:
        try:
            return json.loads((self._dir(thread, turn) / "entries.json").read_text())["entries"]
        except (OSError, ValueError, KeyError):
            return []

    def meta(self, thread: str, turn: str) -> dict[str, Any]:
        try:
            return json.loads((self._dir(thread, turn) / "entries.json").read_text())
        except (OSError, ValueError):
            return {"entries": []}

    def _save(self, thread: str, turn: str, meta: dict[str, Any]) -> None:
        write_atomic(self._dir(thread, turn) / "entries.json", json.dumps(meta, indent=1).encode())

    def touched(self, thread: str, folder: str) -> bool:
        """Has this chat changed anything in this folder before?"""
        d = self.root / thread
        if thread == "_direct" or not d.is_dir():
            return False
        return any(e.get("folder") == folder for t in d.iterdir() if t.is_dir() for e in self.entries(thread, t.name))

    def before(self, thread: str, turn: str, folder: str, path: Path, rel: str, tool: str) -> int:
        """Save `path` as it is now; returns the entry's index (finish it with `after`)."""
        with self._lock:
            d = self._dir(thread, turn)
            d.mkdir(parents=True, exist_ok=True)
            meta = self.meta(thread, turn)
            entries = meta.setdefault("entries", [])
            n = len(entries)
            existed = path.is_file()
            blob = None
            if existed:
                blob = f"{n:03d}.bin"
                shutil.copyfile(path, d / blob)
            entries.append({"n": n, "folder": folder, "path": str(path), "rel": rel, "tool": tool, "ts": time.time(),
                            "existed": existed, "blob": blob, "mode": path.stat().st_mode & 0o7777 if existed else None,
                            "sha_before": sha(path) if existed else None, "sha_after": None, "size": path.stat().st_size if existed else 0})
            meta.update({"thread": thread, "turn": turn, "updated_ts": time.time()})
            meta.setdefault("created_ts", time.time())
            self._save(thread, turn, meta)
        self.prune()
        return n

    def after(self, thread: str, turn: str, n: int, path: Path) -> None:
        with self._lock:
            meta = self.meta(thread, turn)
            meta["entries"][n]["sha_after"] = sha(path)
            if path.is_file():
                shutil.copyfile(path, self._dir(thread, turn) / f"{n:03d}.after")
            self._save(thread, turn, meta)

    def drop(self, thread: str, turn: str, n: int) -> None:
        """The change failed: forget its entry."""
        with self._lock:
            meta = self.meta(thread, turn)
            e = meta["entries"].pop(n)
            for f in (e.get("blob"), f"{n:03d}.after"):
                if f:
                    (self._dir(thread, turn) / f).unlink(missing_ok=True)
            self._save(thread, turn, meta)

    # ---- undo -------------------------------------------------------------------------------

    def undo(self, thread: str, turn: str, root_of: Callable[[str], Path | None]) -> dict[str, Any]:
        """Restore a turn, newest change first. Refuses (with diffs) when a file changed since, or when a
        file now leads outside its folder (`root_of(folder id)`: the folder's real path, None when gone)."""
        with self._lock:
            meta = self.meta(thread, turn)
            entries = meta.get("entries") or []
            if not entries:
                return {"status": "empty", "restored": [], "detail": "nothing to undo in this turn"}
            if meta.get("undone_ts"):
                return {"status": "already", "restored": [], "detail": "this turn was already undone"}
            latest: dict[str, str | None] = {}
            for e in entries:                       # the state the agent left each file in
                latest[e["path"]] = e["sha_after"]
            roots = {e["folder"]: root_of(e["folder"]) for e in entries}
            conflicts = []
            for path, want in latest.items():
                e = next(x for x in reversed(entries) if x["path"] == path)
                root = roots[e["folder"]]
                if root is None or not inside(Path(os.path.realpath(path)), root):
                    conflicts.append({"rel": e["rel"], "folder": e["folder"], "diff": "",
                                      "detail": "its folder is gone" if root is None else "it now leads outside its folder"})
                    continue
                now = sha(Path(path))
                if now != want:
                    conflicts.append({"rel": e["rel"], "folder": e["folder"],
                                      "detail": "deleted since" if now is None else "changed since the agent's edit",
                                      "diff": self._conflict_diff(thread, turn, entries, path)})
            if conflicts:
                return {"status": "conflict", "restored": [], "conflicts": conflicts,
                        "detail": f"{len(conflicts)} file(s) changed outside the agent since this turn; nothing was restored"}
            d = self._dir(thread, turn)
            restored, skipped = [], []
            for e in reversed(entries):
                p, root = Path(e["path"]), roots[e["folder"]]
                assert root is not None
                try:
                    if e["existed"]:
                        write_atomic(p, (d / e["blob"]).read_bytes(), e.get("mode"), root=root)
                    elif p.is_file() or p.is_symlink():
                        unlink_in(root, p)
                except Refused as r:                # a folder became a symlink while undoing
                    skipped.append({"rel": e["rel"], "folder": e["folder"], "detail": r.detail})
                    continue
                restored.append({"rel": e["rel"], "folder": e["folder"], "existed": e["existed"]})
            meta["undone_ts"] = time.time()
            self._save(thread, turn, meta)
        seen, out = set(), []
        for r in restored:
            if (r["folder"], r["rel"]) not in seen:
                seen.add((r["folder"], r["rel"]))
                out.append(r)
        res = {"status": "undone", "restored": out, "detail": f"restored {len(out)} file(s) as they were before this turn"}
        if skipped:
            res.update({"skipped": skipped, "detail": res["detail"] + f"; {len(skipped)} skipped (they lead outside their folder now)"})
        return res

    def _conflict_diff(self, thread: str, turn: str, entries: list[dict[str, Any]], path: str) -> str:
        """What changed since the agent left the file: its state after the turn vs now."""
        last = [e for e in entries if e["path"] == path][-1]
        kept = self._dir(thread, turn) / f"{last['n']:03d}.after"
        mine = kept.read_text(errors="replace") if kept.is_file() else ""
        return diff(mine, text_of(Path(path)), last["rel"])[:6000]

    # ---- listing and pruning ------------------------------------------------------------------

    def turns(self, thread: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        out = []
        threads = [self.root / thread] if thread else (list(self.root.iterdir()) if self.root.is_dir() else [])
        for td in threads:
            if not td.is_dir():
                continue
            for d in td.iterdir():
                meta = self.meta(td.name, d.name)
                es = meta.get("entries") or []
                if not es:
                    continue
                files = sorted({(e["folder"], e["rel"]) for e in es})
                out.append({"thread": td.name, "turn": d.name, "created_ts": meta.get("created_ts"), "updated_ts": meta.get("updated_ts"),
                            "undone_ts": meta.get("undone_ts"), "changes": len(es),
                            "files": [{"folder": f, "rel": r} for f, r in files], "tools": sorted({e["tool"] for e in es}),
                            "bytes": sum(e.get("size") or 0 for e in es),
                            "undo": f"/api/s/workspace/v1/checkpoints/{td.name}/{d.name}/undo"})
        out.sort(key=lambda t: t.get("updated_ts") or 0, reverse=True)
        return out[:limit]

    def usage(self) -> dict[str, Any]:
        n, size = 0, 0
        if self.root.is_dir():
            for d, _, files in os.walk(self.root):
                for f in files:
                    try:
                        size += (Path(d) / f).stat().st_size
                    except OSError:
                        pass
            n = sum(1 for td in self.root.iterdir() if td.is_dir() for _ in td.iterdir())
        return {"turns": n, "bytes": size, "keep_days": KEEP_S // 86400, "keep_bytes": KEEP_BYTES}

    def prune(self, now: float | None = None, keep_s: float = KEEP_S, keep_bytes: int = KEEP_BYTES) -> int:
        """Drop turns older than 14 days, then the oldest until the rest fit in 2 GB."""
        if not self.root.is_dir():
            return 0
        now = now or time.time()
        turns = []
        for td in self.root.iterdir():
            if not td.is_dir():
                continue
            for d in td.iterdir():
                if not d.is_dir():
                    continue
                size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
                turns.append((self.meta(td.name, d.name).get("updated_ts") or d.stat().st_mtime, size, d))
        turns.sort()
        total = sum(t[1] for t in turns)
        gone = 0
        for ts, size, d in turns:
            if now - ts > keep_s or total > keep_bytes:
                shutil.rmtree(d, ignore_errors=True)
                total -= size
                gone += 1
                if not any(d.parent.iterdir()):
                    d.parent.rmdir()
        return gone
