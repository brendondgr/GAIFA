"""Mods that are their own git repositories (plan mod-repos).

Standard library only: `utils/cli.py` imports it. Every git call runs with `-C <folder>`, no prompts
(`GIT_TERMINAL_PROMPT=0`) and a timeout, and none of them changes a working tree.

- `ignore_gap(root, sid)`: files GAIFA ignores under `services/<sid>/` that the mod's own `.gitignore`
  files don't. Once the folder is a submodule only its own rules apply, so each of these would show
  up as untracked there (a venv, a key, a runtime). An ignored folder is checked as a folder: a rule
  for it or for everything in it (`runtime/`, `runtime/*`) covers it, and a `!` rule inside it isn't
  looked into (the folders can hold 100,000 files).
- `submodules(root)`, `repo_state(root, sid)`, `list_states(root)`: each submodule mod's pin, checkout,
  branch, ahead/behind, unpushed commits and its problems (each with a level and the fix), from local
  git only. `fetch(root, sid)` is the one call that contacts the remote; it never raises and keeps its
  result in `data/state/repos/fetch.json`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

GIT_TIMEOUT_S = 30
SKIP_DIRS = {".git", ".venv", "node_modules", "runtime", "__pycache__"}


class GitError(RuntimeError):
    """A git command failed; the message is git's own."""


def git(folder: Path, *args: str, timeout: float = GIT_TIMEOUT_S, check: bool = True, env: dict[str, str] | None = None,
        input: str | None = None) -> subprocess.CompletedProcess[str]:
    full = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASK_YESNO": "false", "LC_ALL": "C", **(env or {})}
    try:
        r = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, env=full, timeout=timeout,
                           input=input)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)}: no answer within {timeout:.0f}s") from e
    if check and r.returncode:
        raise GitError((r.stderr or r.stdout).strip() or f"git {' '.join(args)} exited {r.returncode}")
    return r


def _own_ignore_files(mod: Path) -> list[Path]:
    """The mod's `.gitignore` files (its top one and nested ones), not those inside venvs or runtimes."""
    found = []
    for dirpath, dirnames, filenames in os.walk(mod):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if ".gitignore" in filenames:
            found.append(Path(dirpath) / ".gitignore")
    return found


def ignore_gap(root: Path, sid: str) -> list[str]:
    """Paths (relative to the mod, directories with a trailing `/`) that GAIFA ignores under
    `services/<sid>/` but the mod's own rules don't. Empty when the mod can stand alone."""
    mod = root / "services" / sid
    listed = git(root, "status", "--ignored", "--porcelain=v1", "--", f"services/{sid}").stdout.splitlines()
    prefix = f"services/{sid}/"
    ignored = [line[3:].strip('"')[len(prefix):] for line in listed if line.startswith("!! ")]
    ignored = [p for p in ignored if p and not p.startswith(".git/")]
    if not ignored:
        return []
    with tempfile.TemporaryDirectory(prefix="gaifa-ignore-") as tmp:
        scratch = Path(tmp)
        git(scratch, "init", "-q")
        for f in _own_ignore_files(mod):
            dest = scratch / f.relative_to(mod)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
        r = subprocess.run(["git", "-C", str(scratch), "-c", "core.excludesFile=/dev/null", "check-ignore", "--no-index",
                            "--stdin", "-z", "-v", "-n"], input="\0".join(ignored) + "\0", capture_output=True,
                           text=True, timeout=GIT_TIMEOUT_S)
        # -v -n -z: source, linenum, pattern, path per entry; no source means no rule matched it, and a
        # `!pattern` match means a rule un-ignores it.
        fields = r.stdout.split("\0")
        return [fields[i + 3] for i in range(0, len(fields) - 3, 4)
                if not fields[i] or fields[i + 2].startswith("!")]


# ---- each submodule's state (plan mod-repos 3.1) ---------------------------------------------------

LEVELS = ("info", "warn", "error")
FETCH_TIMEOUT_S = 60


@dataclass
class Problem:
    code: str
    level: str          # info | warn | error
    title: str
    detail: str = ""
    fix: str = ""


@dataclass
class RepoState:
    id: str
    path: str                       # services/<id>
    url: str
    branch: str
    initialized: bool = False
    pinned: str | None = None       # the gitlink in GAIFA's HEAD
    staged_pin: str | None = None   # the gitlink in GAIFA's index, when it differs
    head: str | None = None
    on_branch: str | None = None    # None when detached
    dirty: int = 0                  # tracked files changed
    untracked: int = 0
    ahead: int = 0                  # commits on head not on origin/<branch> (after the last fetch)
    behind: int = 0                 # commits on origin/<branch> the pin doesn't have
    unpushed: int = 0               # commits on head on no remote branch
    pinned_on_remote: bool | None = None
    checkout_vs_pin: str = "same"   # same | ahead | behind | diverged | unknown
    remote_url: str | None = None
    last_fetch_ts: float | None = None
    fetch_error: str | None = None
    problems: list[Problem] = field(default_factory=list)

    @property
    def level(self) -> str | None:
        """The worst problem's level, or None."""
        return max((p.level for p in self.problems), key=LEVELS.index, default=None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level"] = self.level
        return d


def submodules(root: Path) -> list[tuple[str, str, str, str]]:
    """(id, path, url, branch) for every submodule under services/ in `.gitmodules`; [] without one."""
    if not (root / ".gitmodules").is_file():
        return []
    r = git(root, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url|branch)$", check=False)
    by_name: dict[str, dict[str, str]] = {}
    for line in r.stdout.splitlines():
        key, _, value = line.partition(" ")
        name, _, attr = key[len("submodule."):].rpartition(".")
        by_name.setdefault(name, {})[attr] = value
    out = []
    for v in by_name.values():
        path = v.get("path", "")
        if path.startswith("services/") and path.count("/") == 1:
            out.append((path.split("/", 1)[1], path, v.get("url", ""), v.get("branch", "main")))
    return sorted(out)


def _fetch_log(root: Path) -> Path:
    return root / "data" / "state" / "repos" / "fetch.json"


def _read_fetch_log(root: Path) -> dict[str, dict]:
    try:
        return json.loads(_fetch_log(root).read_text())
    except (OSError, ValueError):
        return {}


def fetch(root: Path, sid: str, timeout: float = FETCH_TIMEOUT_S) -> str | None:
    """Fetch the mod's branch from origin; returns git's message when it failed (offline, no access, a
    renamed branch), never raises. The result is kept in data/state/repos/fetch.json."""
    subs = {s[0]: s for s in submodules(root)}
    if sid not in subs:
        return f"{sid} isn't a submodule"
    _, path, _, branch = subs[sid]
    mod = root / path
    error: str | None = None
    if not (mod / ".git").exists():
        error = "not checked out"
    else:
        try:
            git(mod, "fetch", "-q", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=timeout)
        except GitError as e:
            lines = [x.strip() for x in str(e).splitlines() if x.strip()]
            first = next((x for x in lines if x.startswith(("fatal:", "error:", "ERROR:"))), lines[0] if lines else "fetch failed")
            error = first.split(":", 1)[1].strip() if first.startswith(("fatal:", "error:")) else first
    log = _read_fetch_log(root)
    log[sid] = {"ts": time.time(), "error": error}
    _fetch_log(root).parent.mkdir(parents=True, exist_ok=True)
    tmp = _fetch_log(root).with_suffix(".tmp")
    tmp.write_text(json.dumps(log, indent=1))
    os.replace(tmp, _fetch_log(root))
    return error


def _out(folder: Path, *args: str) -> str:
    return git(folder, *args, check=False).stdout.strip()


def _ancestor(folder: Path, a: str, b: str) -> bool:
    return git(folder, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def repo_state(root: Path, sid: str) -> RepoState:
    subs = {s[0]: s for s in submodules(root)}
    if sid not in subs:
        raise GitError(f"{sid} isn't a submodule in .gitmodules")
    _, path, url, branch = subs[sid]
    st = RepoState(id=sid, path=path, url=url, branch=branch)
    mod = root / path
    tree = _out(root, "ls-tree", "HEAD", "--", path).split()
    st.pinned = tree[2] if len(tree) >= 3 and tree[0] == "160000" else None
    staged = _out(root, "ls-files", "-s", "--", path).split()
    if staged and staged[0] == "160000" and staged[1] != st.pinned:
        st.staged_pin = staged[1]
    log = _read_fetch_log(root).get(sid) or {}
    st.last_fetch_ts, st.fetch_error = log.get("ts"), log.get("error")
    st.initialized = (mod / ".git").exists() and (mod / "service.toml").is_file()
    st.problems = []
    if not st.initialized:
        st.checkout_vs_pin = "unknown"
        st.problems.append(Problem("not_checked_out", "error", f"{sid} isn't checked out",
                                   f"{path} is empty: GAIFA was cloned or pulled without its submodules.",
                                   f"gaifa repos sync {sid}  (git submodule update --init {path})"))
        return st
    st.head = _out(mod, "rev-parse", "HEAD") or None
    st.on_branch = _out(mod, "symbolic-ref", "-q", "--short", "HEAD") or None
    status = git(mod, "status", "--porcelain").stdout.splitlines()
    st.untracked = sum(1 for line in status if line.startswith("??"))
    st.dirty = len(status) - st.untracked
    st.remote_url = _out(mod, "remote", "get-url", "origin") or None
    remote = f"refs/remotes/origin/{branch}"
    has_remote = bool(_out(mod, "rev-parse", "-q", "--verify", remote))
    if has_remote and st.head:
        st.ahead = int(_out(mod, "rev-list", "--count", f"{remote}..{st.head}") or 0)
        base = st.pinned if st.pinned and _out(mod, "cat-file", "-t", st.pinned) == "commit" else st.head
        st.behind = int(_out(mod, "rev-list", "--count", f"{base}..{remote}") or 0)
    if st.head:
        st.unpushed = int(_out(mod, "rev-list", "--count", st.head, "--not", "--remotes") or 0)
    pin_known = bool(st.pinned) and _out(mod, "cat-file", "-t", st.pinned or "") == "commit"
    if st.pinned and pin_known:
        st.pinned_on_remote = _out(mod, "rev-list", "-n1", st.pinned, "--not", "--remotes") == ""
    if not st.pinned or not st.head:
        st.checkout_vs_pin = "unknown"
    elif st.head == st.pinned:
        st.checkout_vs_pin = "same"
    elif not pin_known:
        st.checkout_vs_pin = "behind"      # GAIFA pins a commit this checkout hasn't fetched yet
    elif _ancestor(mod, st.head, st.pinned):
        st.checkout_vs_pin = "behind"
    elif _ancestor(mod, st.pinned, st.head):
        st.checkout_vs_pin = "ahead"
    else:
        st.checkout_vs_pin = "diverged"
    st.problems = _problems(st)
    return st


def _problems(st: RepoState) -> list[Problem]:
    sid, path = st.id, st.path
    out: list[Problem] = []
    if st.dirty:
        out.append(Problem("dirty", "warn", f"{sid} has {st.dirty} changed file{'s' * (st.dirty != 1)} not committed",
                           f"Changes in {path} belong to its own repository ({st.url}).",
                           f"commit them in {path} (git -C {path} commit) and push, or discard them"))
    if st.untracked:
        out.append(Problem("untracked", "warn", f"{sid} has {st.untracked} untracked file{'s' * (st.untracked != 1)}",
                           "New files, or files a missing ignore rule should hide (a venv, a key, a runtime).",
                           f"add them to {path}/.gitignore, or commit them in {path}"))
    if st.unpushed:
        out.append(Problem("unpushed", "warn", f"{sid} has {st.unpushed} commit{'s' * (st.unpushed != 1)} not pushed",
                           f"They're only on this machine, not on {st.url}.",
                           f"git -C {path} push" if st.on_branch else f"put them on a branch in {path} and push it"))
    if st.pinned and st.pinned_on_remote is False:
        out.append(Problem("pin_not_on_remote", "warn", f"GAIFA pins {sid} at {st.pinned[:10]}, which isn't on GitHub",
                           "A clone of GAIFA couldn't check that commit out.",
                           f"push it from {path}, or pin a pushed commit (gaifa repos pin {sid})"))
    if st.checkout_vs_pin == "behind":
        out.append(Problem("checkout_behind_pin", "warn", f"{sid}'s checkout is older than GAIFA's pin",
                           f"{path} is at {(st.head or '')[:10]}; GAIFA wants {(st.pinned or '')[:10]} (a pull of GAIFA moved it).",
                           f"gaifa repos sync {sid}"))
    elif st.checkout_vs_pin == "ahead":
        out.append(Problem("checkout_ahead_of_pin", "info", f"{sid} has commits GAIFA doesn't pin yet",
                           f"{path} is at {(st.head or '')[:10]}, ahead of the pin {(st.pinned or '')[:10]}.",
                           f"push them, then gaifa repos pin {sid} and commit GAIFA"))
    elif st.checkout_vs_pin == "diverged":
        out.append(Problem("diverged", "error", f"{sid}'s checkout and GAIFA's pin have split",
                           f"{path} at {(st.head or '')[:10]} and the pin {(st.pinned or '')[:10]} are on different lines.",
                           f"check out the pin (gaifa repos sync {sid}) or pin the checkout (gaifa repos pin {sid})"))
    if st.behind:
        out.append(Problem("updates_available", "info", f"{sid}: {st.behind} new commit{'s' * (st.behind != 1)} on {st.branch}",
                           f"{st.url} {st.branch} is ahead of the pin.", f"gaifa repos update {sid}"))
    if st.fetch_error:
        out.append(Problem("fetch_failed", "info", f"{sid}: couldn't check {st.url}", st.fetch_error,
                           "check the network, an SSH key with access, or the repository's name"))
    if st.remote_url and st.url and st.remote_url != st.url:
        out.append(Problem("wrong_remote", "warn", f"{sid}'s origin isn't the repository GAIFA names",
                           f"origin is {st.remote_url}; .gitmodules says {st.url}.",
                           f"git -C {path} remote set-url origin {st.url}"))
    return out


def list_states(root: Path) -> list[RepoState]:
    out = []
    for sid, *_ in submodules(root):
        try:
            out.append(repo_state(root, sid))
        except GitError as e:
            _, path, url, branch = next(s for s in submodules(root) if s[0] == sid)
            out.append(RepoState(id=sid, path=path, url=url, branch=branch, checkout_vs_pin="unknown",
                                 problems=[Problem("git_error", "error", f"{sid}: git failed", str(e))]))
    return out
