"""Turn a mod folder into a submodule of its own repository, in place (plan mod-repos 2.1).

The folder's files never change: its venv, `runtime/`, `.env` and `data/` stay where they are, so a
running mod keeps running. A snapshot (path, size, mtime of every file, ignored ones too) is taken
before and compared after: a missing file is an error, and new or changed ones (a running mod's
logs) are listed in `adopt-<sid>-diff.txt`.

GAIFA's commit is built in a private index (read-tree HEAD, the folder's files out, the gitlink and
`.gitmodules` in), so the shared index, which another session may be using, only ever sees the
finished change for these two paths. `main` moves only if it still points where the commit was built.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from utils.repos import GitError, git

SNAPSHOT_SKIP = {".git"}


def snapshot(folder: Path) -> dict[str, list[int]]:
    """{relative path: [size, mtime_ns]} for every file and symlink under `folder`, `.git` aside."""
    out: dict[str, list[int]] = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        if Path(dirpath) == folder:
            dirnames[:] = [d for d in dirnames if d not in SNAPSHOT_SKIP]
        for name in filenames:
            p = Path(dirpath) / name
            if p == folder / ".git":
                continue
            st = p.lstat()
            out[str(p.relative_to(folder))] = [st.st_size, st.st_mtime_ns]
    return out


def diff_snapshots(before: dict[str, list[int]], after: dict[str, list[int]]) -> list[str]:
    lines = [f"gone: {p}" for p in sorted(before.keys() - after.keys())]
    lines += [f"new: {p}" for p in sorted(after.keys() - before.keys())]
    lines += [f"changed: {p}" for p in sorted(before.keys() & after.keys()) if before[p] != after[p]]
    return lines


def _gitmodules(text: str, sid: str, url: str, branch: str) -> str:
    entry = f'[submodule "services/{sid}"]\n\tpath = services/{sid}\n\turl = {url}\n\tbranch = {branch}\n'
    return (text.rstrip("\n") + "\n" if text.strip() else "") + entry


def _commit(root: Path, sid: str, gitlink: str, url: str, branch: str, message: str) -> str:
    """GAIFA's commit: services/<sid>'s files replaced by the gitlink, .gitmodules gaining its entry."""
    for _ in range(3):
        head = git(root, "rev-parse", "HEAD").stdout.strip()
        fd, idx = tempfile.mkstemp(prefix="gaifa-adopt-idx-")
        os.close(fd)
        os.unlink(idx)
        env = {"GIT_INDEX_FILE": idx}
        try:
            git(root, "read-tree", head, env=env)
            files = git(root, "ls-files", "-z", "--", f"services/{sid}", env=env).stdout.split("\0")
            for f in filter(None, files):
                git(root, "update-index", "--force-remove", "--", f, env=env)
            git(root, "update-index", "--add", "--cacheinfo", f"160000,{gitlink},services/{sid}", env=env)
            old = git(root, "show", f"{head}:.gitmodules", check=False).stdout
            blob = git(root, "hash-object", "-w", "--stdin", input=_gitmodules(old, sid, url, branch)).stdout.strip()
            git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},.gitmodules", env=env)
            tree = git(root, "write-tree", env=env).stdout.strip()
        finally:
            if os.path.exists(idx):
                os.unlink(idx)
        commit = git(root, "commit-tree", tree, "-p", head, input=message).stdout.strip()
        branch_ref = git(root, "symbolic-ref", "HEAD").stdout.strip()
        if git(root, "update-ref", branch_ref, commit, head, check=False).returncode == 0:
            git(root, "reset", "-q", commit, "--", f"services/{sid}")
            git(root, "checkout", "-q", commit, "--", ".gitmodules")
            return commit
    raise GitError("HEAD kept moving while the commit was built; try again")


def adopt(root: Path, sid: str, url: str, branch: str, message: str, state_dir: Path | None = None) -> str:
    """Make services/<sid> a submodule at its repository's `branch` head; returns GAIFA's new commit."""
    mod = root / "services" / sid
    if not mod.is_dir():
        raise GitError(f"services/{sid} doesn't exist")
    if (mod / ".git").exists():
        raise GitError(f"services/{sid} is already a repository (adopted before?)")
    dirty = git(root, "status", "--porcelain", "--", f"services/{sid}").stdout.strip()
    if dirty:
        raise GitError(f"services/{sid} has changes GAIFA hasn't committed:\n{dirty}")
    if git(root, "ls-files", "--", f"services/{sid}").stdout.strip() == "":
        raise GitError(f"GAIFA tracks nothing in services/{sid}")
    ours = git(root, "rev-parse", f"HEAD:services/{sid}").stdout.strip()
    state = state_dir or root / "data" / "state" / "repos"
    state.mkdir(parents=True, exist_ok=True)
    before = snapshot(mod)
    (state / f"adopt-{sid}-before.json").write_text(json.dumps(before))

    git(mod, "init", "-q", "-b", branch)
    try:
        git(mod, "remote", "add", "origin", url)
        git(mod, "fetch", "-q", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=300)
        head = git(mod, "rev-parse", f"origin/{branch}").stdout.strip()
        theirs = git(mod, "rev-parse", f"{head}^{{tree}}").stdout.strip()
        if theirs != ours:
            raise GitError(f"{url} {branch} ({head[:10]}) doesn't hold what GAIFA has in services/{sid}; "
                           "push the split first (preflight, push)")
        git(mod, "reset", "-q", "--mixed", head)
        git(mod, "branch", "-q", f"--set-upstream-to=origin/{branch}")
        loose = git(mod, "status", "--porcelain").stdout.strip()
        if loose:
            raise GitError(f"services/{sid} isn't clean as its own repository (an ignore rule missing?):\n{loose}")
    except Exception:
        shutil.rmtree(mod / ".git", ignore_errors=True)
        raise

    commit = _commit(root, sid, head, url, branch, message)
    git(root, "submodule", "init", "--", f"services/{sid}")
    git(root, "submodule", "absorbgitdirs", "--", f"services/{sid}")
    after = snapshot(mod)
    (state / f"adopt-{sid}-after.json").write_text(json.dumps(after))
    # The adoption only writes `.git`; a running mod may still write its logs and state meanwhile, so
    # new and changed files are listed (adopt-<sid>-diff.txt) and only a missing file is an error.
    changed = diff_snapshots(before, after)
    (state / f"adopt-{sid}-diff.txt").write_text("\n".join(changed) + "\n")
    gone = [c for c in changed if c.startswith("gone: ")]
    if gone:
        raise GitError(f"services/{sid} lost files during the adoption ({len(gone)}):\n" + "\n".join(gone[:40]))
    return commit

