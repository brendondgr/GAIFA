"""Moving a submodule mod forward, pinning and syncing it (plan mod-repos 3.2–3.3).

`update()` is one flow for `gaifa repos update` and the hub's `POST /api/repos/{id}/update`; what
differs between them (how to install, restart and check a mod, whether it's busy) comes in as
`Hooks`. Standard library only.

update: refuse what an update would lose (changed files, unpushed commits, a split history, a folder
that isn't checked out, a busy mod, another update running) → fetch → move the checkout to the
branch's head (fast-forward on the branch, or detached) → install when its dependencies changed →
restart if it was running → `gaifa check` → on any failure, the old commit back (reinstalled and
restarted) → on success the new pin staged in GAIFA (or committed with `commit=True`, tests first).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

if __package__:
    from utils.repos import GitError, fetch, git, repo_state
else:                                    # bin/gaifa runs utils/cli.py as a script: utils/ is on sys.path
    from repos import GitError, fetch, git, repo_state  # type: ignore[no-redef]

REFUSE = ("not_checked_out", "dirty", "unpushed", "diverged", "git_error")
DEP_NAMES = {"uv.lock", "pyproject.toml", "package-lock.json", "package.json", "install.sh", "gaifa-install.sh", "Makefile"}
LOCK_STALE_S = 3600


@dataclass
class Hooks:
    install: Callable[[str], int] = lambda sid: 0                         # the mod's install script; exit code
    running: Callable[[str], bool] = lambda sid: False
    restart: Callable[[str], None] = lambda sid: None
    check: Callable[[str], tuple[bool | None, str]] = lambda sid: (None, "not checked")   # None: couldn't run
    busy: Callable[[str], str | None] = lambda sid: None                  # what it's doing, when it's busy
    progress: Callable[[str], None] = lambda msg: None
    tests: Callable[[], tuple[bool, str]] = lambda: (True, "")


@dataclass
class Result:
    id: str
    ok: bool = False
    old: str | None = None
    new: str | None = None
    commits: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)     # problem codes, or "busy", "locked", "fetch_failed"
    installed: bool = False
    restarted: bool = False
    checked: bool | None = None
    check_detail: str = ""
    rolled_back: bool = False
    staged: bool = False
    committed: str | None = None
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class _Lock:
    """One update at a time: data/state/repos/update.lock, taken over when its process is gone or it's stale."""

    def __init__(self, root: Path) -> None:
        self.path = root / "data" / "state" / "repos" / "update.lock"

    def __enter__(self) -> _Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
                os.close(fd)
                return self
            except FileExistsError:
                if not self._stale():
                    raise GitError("another update is running") from None
                self.path.unlink(missing_ok=True)
        raise GitError("another update is running")

    def _stale(self) -> bool:
        try:
            info = json.loads(self.path.read_text())
            os.kill(int(info["pid"]), 0)
            return time.time() - float(info["ts"]) > LOCK_STALE_S
        except (OSError, ValueError, KeyError):
            return True

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


def _deps_changed(mod: Path, old: str, new: str) -> list[str]:
    names = git(mod, "diff", "--name-only", old, new).stdout.split()
    return [n for n in names if Path(n).name in DEP_NAMES or (Path(n).name.startswith("requirements") and n.endswith(".txt"))]


def _move(mod: Path, target: str, branch: str | None) -> None:
    """The checkout to `target`: a fast-forward of the branch it's on, else detached."""
    if branch:
        git(mod, "merge", "-q", "--ff-only", target)
    else:
        git(mod, "checkout", "-q", "--detach", target)


def _back(mod: Path, old: str, branch: str | None) -> None:
    if branch:
        git(mod, "reset", "-q", "--keep", old)
    else:
        git(mod, "checkout", "-q", "--detach", old)


def stage_pin(root: Path, path: str, sha: str) -> None:
    """The pin in GAIFA's index (what `git add services/<id>` does for a submodule)."""
    git(root, "update-index", "--cacheinfo", f"160000,{sha},{path}")


def commit_pin(root: Path, path: str, sha: str, message: str) -> str:
    """Commit only the pin, built in a private index so nothing else staged in the shared one goes with
    it; `main` moves only if it hasn't moved meanwhile. Returns the commit."""
    for _ in range(3):
        head = git(root, "rev-parse", "HEAD").stdout.strip()
        fd, idx = tempfile.mkstemp(prefix="gaifa-pin-idx-")
        os.close(fd)
        os.unlink(idx)
        env = {"GIT_INDEX_FILE": idx}
        try:
            git(root, "read-tree", head, env=env)
            git(root, "update-index", "--cacheinfo", f"160000,{sha},{path}", env=env)
            tree = git(root, "write-tree", env=env).stdout.strip()
        finally:
            if os.path.exists(idx):
                os.unlink(idx)
        commit = git(root, "commit-tree", tree, "-p", head, input=message).stdout.strip()
        ref = git(root, "symbolic-ref", "HEAD").stdout.strip()
        if git(root, "update-ref", ref, commit, head, check=False).returncode == 0:
            git(root, "reset", "-q", commit, "--", path)
            return commit
    raise GitError("HEAD kept moving while the pin was committed; try again")


def update(root: Path, sid: str, to: str | None = None, dry_run: bool = False, force_busy: bool = False,
           commit: bool = False, hooks: Hooks | None = None) -> Result:
    h = hooks or Hooks()
    res = Result(id=sid)
    try:
        with _Lock(root):
            return _update(root, sid, to, dry_run, force_busy, commit, h, res)
    except GitError as e:
        if not res.message:
            res.message = str(e)
        if str(e) == "another update is running":
            res.refused.append("locked")
        return res


def _update(root: Path, sid: str, to: str | None, dry_run: bool, force_busy: bool, commit: bool, h: Hooks,
            res: Result) -> Result:
    st = repo_state(root, sid)
    res.old = st.head
    res.refused = [p.code for p in st.problems if p.code in REFUSE]
    if not force_busy and (doing := h.busy(sid)):
        res.refused.append("busy")
        res.message = f"{sid} is busy ({doing}); wait for it, or force it"
    if res.refused:
        res.message = res.message or "; ".join(p.title for p in st.problems if p.code in REFUSE)
        return res
    mod = root / st.path
    h.progress(f"fetching {st.url} {st.branch}")
    if (error := fetch(root, sid)) and not to:
        res.refused.append("fetch_failed")
        res.message = f"couldn't fetch {st.url}: {error}"
        return res
    target = git(mod, "rev-parse", "--verify", f"{to or f'origin/{st.branch}'}^{{commit}}").stdout.strip()
    res.new = target
    if target == st.head:
        res.ok = True
        res.message = f"{sid} is up to date at {target[:10]}"
        if st.pinned != target and not dry_run:
            stage_pin(root, st.path, target)
            res.staged = True
        return res
    if not git(mod, "merge-base", "--is-ancestor", st.head or "", target, check=False).returncode == 0 and not to:
        res.refused.append("diverged")
        res.message = f"{st.branch} on {st.url} isn't ahead of {sid}'s checkout (rewritten?)"
        return res
    res.commits = git(mod, "log", "--format=%h %s", f"{st.head}..{target}").stdout.splitlines()
    if dry_run:
        res.ok = True
        res.message = f"{sid} would move {st.head[:10] if st.head else '?'} → {target[:10]} ({len(res.commits)} commits)"
        return res
    deps = _deps_changed(mod, st.head or target, target)
    was_running = h.running(sid)
    branch = st.on_branch if st.on_branch == st.branch and not to else None
    if st.on_branch and not branch:
        branch = None
        git(mod, "checkout", "-q", "--detach")
    h.progress(f"checking out {target[:10]}")
    _move(mod, target, branch)
    failure = ""
    if deps:
        h.progress(f"installing ({', '.join(deps)} changed)")
        res.installed = True
        if (rc := h.install(sid)) != 0:
            failure = f"the install exited {rc}"
    if not failure and was_running:
        h.progress("restarting")
        h.restart(sid)
        res.restarted = True
    if not failure:
        h.progress("checking")
        res.checked, res.check_detail = h.check(sid)
        if res.checked is False:
            failure = f"gaifa check failed: {res.check_detail}"
    if failure:
        h.progress(f"rolling back to {(st.head or '')[:10]}")
        _back(mod, st.head or "", branch)
        if deps:
            h.install(sid)
        if was_running:
            h.restart(sid)
        res.rolled_back = True
        res.message = f"{failure}; {sid} is back at {(st.head or '')[:10]}"
        return res
    if commit:
        h.progress("running GAIFA's tests")
        ok, detail = h.tests()
        if not ok:
            stage_pin(root, st.path, target)
            res.staged = True
            res.ok = True
            res.message = f"{sid} → {target[:10]}; the pin is staged but not committed: the tests failed ({detail})"
            return res
        msg = f"GAIFA (repos): {sid} → {target[:10]} ({len(res.commits)} commit{'s' * (len(res.commits) != 1)})\n\n" + \
              "\n".join(f"- {c}" for c in res.commits) + "\n"
        res.committed = commit_pin(root, st.path, target, msg)
    else:
        stage_pin(root, st.path, target)
        res.staged = True
    res.ok = True
    res.message = f"{sid} → {target[:10]} ({len(res.commits)} commits)" + ("" if res.checked else " (not checked: " + res.check_detail + ")")
    return res


def pin(root: Path, sid: str, commit: bool = False, message: str | None = None) -> Result:
    """Record the checkout as GAIFA's pin (after committing and pushing in the mod)."""
    st = repo_state(root, sid)
    res = Result(id=sid, old=st.pinned, new=st.head)
    res.refused = [p.code for p in st.problems if p.code in ("not_checked_out", "dirty", "unpushed", "git_error")]
    if res.refused:
        res.message = "; ".join(p.title for p in st.problems if p.code in res.refused)
        return res
    if st.head == st.pinned:
        res.ok, res.message = True, f"{sid} is already pinned at {(st.head or '')[:10]}"
        return res
    mod = root / st.path
    if st.pinned and git(mod, "cat-file", "-t", st.pinned, check=False).stdout.strip() == "commit":
        res.commits = git(mod, "log", "--format=%h %s", f"{st.pinned}..{st.head}").stdout.splitlines()
    if commit:
        res.committed = commit_pin(root, st.path, st.head or "", message or f"GAIFA (repos): {sid} → {(st.head or '')[:10]}\n")
    else:
        stage_pin(root, st.path, st.head or "")
        res.staged = True
    res.ok = True
    res.message = f"{sid} pinned at {(st.head or '')[:10]}" + (" (staged)" if res.staged else "")
    return res


def sync(root: Path, sid: str) -> Result:
    """Check out GAIFA's pin: after a clone without submodules, or a pull of GAIFA that moved the pin."""
    st = repo_state(root, sid)
    res = Result(id=sid, old=st.head, new=st.pinned)
    if st.initialized and st.checkout_vs_pin == "same":
        res.ok, res.message = True, f"{sid} is at its pin"
        return res
    if st.dirty:
        res.refused, res.message = ["dirty"], f"{sid} has changed files; commit or discard them first"
        return res
    if st.initialized and st.checkout_vs_pin in ("ahead", "diverged"):
        res.refused = [st.checkout_vs_pin]
        res.message = f"{sid}'s checkout is {st.checkout_vs_pin} of the pin; pin it (gaifa repos pin {sid}) or check the pin out by hand"
        return res
    r = subprocess.run(["git", "-C", str(root), "submodule", "update", "--init", "--", st.path],
                       capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=600)
    if r.returncode:
        res.message = (r.stderr or r.stdout).strip()
        return res
    res.ok = True
    res.message = f"{sid} checked out at {(st.pinned or '')[:10]}"
    return res
