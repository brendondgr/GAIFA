"""Split a mod folder's history back out of GAIFA (plan mod-repos 1.2), like `git subtree split`.

The four mods came in with `git subtree add` (no squash): a merge whose second parent U is the mod
repository's own commit and whose `services/<sid>` tree equals U's tree. From there, every GAIFA
commit that changed `services/<sid>` becomes one commit whose tree is that folder, with the original
author, committer, dates and message, on top of U. So the result fast-forwards the repository's
branch, and splitting again gives the same commit ids (nothing depends on the clock).

Standard library only, plumbing only (`rev-list`, `cat-file`, `commit-tree`); it writes objects and
one ref, `refs/heads/split/<sid>`, and never touches a working tree or the index.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.repos import GitError, git

IDENT = re.compile(r"^(?P<name>.*) <(?P<email>[^>]*)> (?P<date>\d+ [+-]\d{4})$")


@dataclass
class Split:
    sid: str
    add: str        # GAIFA's "Add 'services/<sid>/' from commit …" merge
    base: str       # the mod repository's commit it added (the merge's second parent)
    head: str       # the split's last commit
    commits: int    # commits made on top of base


def find_add(root: Path, sid: str) -> tuple[str, str]:
    """The subtree add merge for `services/<sid>/` and the mod commit it brought in."""
    out = git(root, "log", "--format=%H", "-F", f"--grep=Add 'services/{sid}/' from commit", "HEAD").stdout.split()
    if not out:
        raise GitError(f"no \"Add 'services/{sid}/' from commit\" merge in this history")
    add = out[-1]
    parents = git(root, "rev-list", "--parents", "-n1", add).stdout.split()[1:]
    if len(parents) != 2:
        raise GitError(f"{add[:10]} isn't a merge of two commits")
    base = parents[1]
    if _tree(root, f"{add}:services/{sid}") != _tree(root, f"{base}^{{tree}}"):
        raise GitError(f"{add[:10]}:services/{sid} isn't the tree of {base[:10]}")
    return add, base


def _tree(root: Path, rev: str) -> str | None:
    r = git(root, "rev-parse", "--verify", "-q", rev, check=False)
    return r.stdout.strip() or None


def _trees(root: Path, commits: list[str], prefix: str) -> dict[str, str | None]:
    """Each commit's `prefix` tree in one `cat-file --batch-check` call (None where it's missing)."""
    r = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                       input="".join(f"{c}:{prefix}\n" for c in commits), capture_output=True, text=True, check=True)
    out = {}
    for c, line in zip(commits, r.stdout.splitlines()):
        sha, _, kind = line.partition(" ")
        out[c] = sha if kind == "tree" else None
    return out


def _meta(root: Path, commit: str) -> tuple[dict[str, str], bytes]:
    """The environment that recreates the commit's author and committer, and its raw message."""
    raw = subprocess.run(["git", "-C", str(root), "cat-file", "commit", commit], capture_output=True, check=True).stdout
    head, _, message = raw.partition(b"\n\n")
    env: dict[str, str] = {}
    for line in head.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(" ")
        if key in ("author", "committer") and (m := IDENT.match(value)):
            who = "AUTHOR" if key == "author" else "COMMITTER"
            env |= {f"GIT_{who}_NAME": m["name"], f"GIT_{who}_EMAIL": m["email"], f"GIT_{who}_DATE": m["date"]}
    return env, message


def _ancestor(root: Path, a: str, b: str) -> bool:
    return git(root, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def split(root: Path, sid: str, rev: str = "HEAD", ref: bool = True) -> Split:
    """Split `services/<sid>` out of `rev`'s history; with `ref`, point `refs/heads/split/<sid>` at it."""
    add, base = find_add(root, sid)
    lines = git(root, "rev-list", "--topo-order", "--reverse", "--parents", f"{add}..{rev}").stdout.splitlines()
    order = [line.split() for line in lines]
    trees = _trees(root, [c[0] for c in order], f"services/{sid}")
    mapped: dict[str, str | None] = {add: base}
    made = 0
    for commit, *parents in order:
        tree = trees[commit]
        news: list[str] = []
        for p in parents:
            m = mapped.get(p)
            if m and m not in news:
                news.append(m)
        # A parent that's an ancestor of another adds nothing (both sides of a merge came from one line).
        news = [p for p in news if not any(o != p and _ancestor(root, p, o) for o in news)]
        if tree is None:
            mapped[commit] = news[0] if news else None
            continue
        if len(news) == 1 and _tree(root, f"{news[0]}^{{tree}}") == tree:
            mapped[commit] = news[0]
            continue
        env, message = _meta(root, commit)
        args = ["git", "-C", str(root), "commit-tree", tree]
        for p in news:
            args += ["-p", p]
        r = subprocess.run(args, input=message, capture_output=True, env={**os.environ, **env})
        if r.returncode:
            raise GitError(r.stderr.decode().strip())
        mapped[commit] = r.stdout.decode().strip()
        made += 1
    head = mapped.get(git(root, "rev-parse", rev).stdout.strip()) or base
    if ref:
        git(root, "update-ref", f"refs/heads/split/{sid}", head)
    return Split(sid=sid, add=add, base=base, head=head, commits=made)
