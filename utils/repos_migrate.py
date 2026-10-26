"""Moving the four mods back to their own repositories (plan mod-repos Phases 1–2).

    python -m utils.repos_migrate preflight [<sid>…]   split, fetch, check, write the report (1.2)
    python -m utils.repos_migrate push <sid>            push split/<sid> as a fast-forward (1.3)

Nothing here pushes on its own: `preflight` only reads the remote, and `push` needs a person to have
read the report (the plan's approval point). Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from utils.repos import GitError, git
from utils.repos_split import split

ROOT = Path(__file__).resolve().parents[1]
# The repositories the four mods came from (plan mod-repos §1). After Phase 2, `.gitmodules` says this.
MOD_REPOS: dict[str, tuple[str, str]] = {
    "relay": ("git@github.com:brendondgr/Relay.git", "main"),
    "lcpp": ("git@github.com:brendondgr/LLMs.git", "master"),
    "tts": ("git@github.com:brendondgr/LocalTTS.git", "main"),
    "gen3d": ("git@github.com:brendondgr/3DGenerate.git", "main"),
}
LARGE_BYTES = 50 * 1024 * 1024
SECRETS = [
    ("API key (sk-…)", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("secret assignment", re.compile(r"^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*['\"]?[^\s'\"$]{16,}")),
]
HOME_PATH = re.compile(r"/home/[a-z_][a-z0-9_-]*/")


@dataclass
class Finding:
    kind: str
    file: str
    commit: str
    text: str


@dataclass
class Preflight:
    sid: str
    url: str
    branch: str
    base: str = ""
    head: str = ""
    remote: str | None = None
    fast_forward: bool = False
    commits: list[str] = field(default_factory=list)
    large: list[tuple[str, int]] = field(default_factory=list)
    secrets: list[Finding] = field(default_factory=list)
    home_paths: dict[str, int] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.fast_forward and not self.secrets and not self.large


def mask(s: str) -> str:
    return s[:6] + "…" if len(s) > 6 else "…"


def fetch_remote(root: Path, sid: str, url: str, branch: str) -> str:
    """The remote branch's head, fetched into `refs/repos/<sid>/remote` (not a branch, not a remote)."""
    git(root, "fetch", "--no-tags", "-q", url, f"+refs/heads/{branch}:refs/repos/{sid}/remote", timeout=120)
    return git(root, "rev-parse", f"refs/repos/{sid}/remote").stdout.strip()


def scan(root: Path, since: str, head: str) -> tuple[list[Finding], dict[str, int]]:
    """Secrets and home paths in the lines the commits since..head add."""
    log = subprocess.run(["git", "-C", str(root), "log", "-p", "--no-color", "--no-ext-diff", "--format=@@commit %h",
                          f"{since}..{head}"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    secrets: list[Finding] = []
    homes: dict[str, int] = {}
    commit = file = ""
    for line in log.splitlines():
        if line.startswith("@@commit "):
            commit = line[9:]
        elif line.startswith("+++ "):
            file = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            added = line[1:]
            for kind, rx in SECRETS:
                if m := rx.search(added):
                    secrets.append(Finding(kind, file, commit, mask(m.group(0).strip())))
            if HOME_PATH.search(added):
                homes[file] = homes.get(file, 0) + 1
    return secrets, homes


def preflight(root: Path, sid: str, url: str | None = None, branch: str | None = None) -> Preflight:
    url, branch = url or MOD_REPOS[sid][0], branch or MOD_REPOS[sid][1]
    pf = Preflight(sid, url, branch)
    try:
        s = split(root, sid)
        pf.base, pf.head = s.base, s.head
        pf.remote = fetch_remote(root, sid, url, branch)
        pf.fast_forward = git(root, "merge-base", "--is-ancestor", pf.remote, pf.head, check=False).returncode == 0
        since = pf.remote if pf.fast_forward else pf.base
        pf.commits = git(root, "log", "--format=%h %as %s", f"{since}..{pf.head}").stdout.splitlines()
        for row in git(root, "ls-tree", "-r", "-l", pf.head).stdout.splitlines():
            meta, _, path = row.partition("\t")
            size = meta.split()[3]
            if size.isdigit() and int(size) > LARGE_BYTES:
                pf.large.append((path, int(size)))
        pf.secrets, pf.home_paths = scan(root, since, pf.head)
    except GitError as e:
        pf.error = str(e)
    return pf


def report(results: list[Preflight]) -> str:
    out = [f"# Preflight: the mods back to their own repositories ({time.strftime('%Y-%m-%d %H:%M')})", "",
           "Plan mod-repos 1.2. Nothing has been pushed. Each mod's GAIFA-era commits (split from `services/<sid>`) "
           "would go to its repository's branch as a fast-forward.", "",
           "| Mod | Repository | Branch | Commits to push | Fast-forward | Secrets | Large files | Home paths |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        out.append(f"| `{r.sid}` | `{r.url}` | `{r.branch}` | {len(r.commits)} | {'yes' if r.fast_forward else 'NO'} | "
                   f"{len(r.secrets) or 'none'} | {len(r.large) or 'none'} | {sum(r.home_paths.values()) or 'none'} |")
    for r in results:
        out += ["", f"## `{r.sid}` → `{r.url}` `{r.branch}`", ""]
        if r.error:
            out += [f"**Error:** {r.error}"]
            continue
        out += [f"- Remote head `{(r.remote or '')[:10]}`, split head `{r.head[:10]}` (refs/heads/split/{r.sid}), "
                f"added from `{r.base[:10]}`.",
                f"- {'A fast-forward.' if r.fast_forward else '**Not a fast-forward**: the remote has commits the split lacks. Stop and ask.'}"]
        out += ["", "**Secrets:** none found." if not r.secrets else "**Secrets (fix in GAIFA, then run preflight again):**"]
        out += [f"- {f.kind} in `{f.file}` ({f.commit}): `{f.text}`" for f in r.secrets]
        if r.large:
            out += ["", "**Files over 50 MB:**"] + [f"- `{p}` ({n / 1e6:.0f} MB)" for p, n in r.large]
        if r.home_paths:
            out += ["", "**Absolute home paths in added lines** (they become public with a public repository):"]
            out += [f"- `{f}`: {n}" for f, n in sorted(r.home_paths.items(), key=lambda kv: -kv[1])]
        out += ["", f"**Commits ({len(r.commits)}):**", ""] + [f"- {c}" for c in r.commits]
    return "\n".join(out) + "\n"


def push(root: Path, sid: str, url: str | None = None, branch: str | None = None) -> str:
    """Push split/<sid> to its branch, never forced, and confirm the remote head."""
    url, branch = url or MOD_REPOS[sid][0], branch or MOD_REPOS[sid][1]
    head = git(root, "rev-parse", f"refs/heads/split/{sid}").stdout.strip()
    git(root, "push", "-q", url, f"refs/heads/split/{sid}:refs/heads/{branch}", timeout=300)
    remote = git(root, "ls-remote", url, f"refs/heads/{branch}", timeout=60).stdout.split()
    if not remote or remote[0] != head:
        raise GitError(f"{url} {branch} is at {remote[0][:10] if remote else '?'}, not {head[:10]}")
    return head


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m utils.repos_migrate")
    sub = p.add_subparsers(dest="cmd", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("sids", nargs="*")
    pu = sub.add_parser("push")
    pu.add_argument("sid", choices=sorted(MOD_REPOS))
    a = p.parse_args(argv)
    if a.cmd == "preflight":
        results = [preflight(ROOT, sid) for sid in (a.sids or list(MOD_REPOS))]
        dest = ROOT / "data" / "state" / "repos" / f"preflight-{time.strftime('%Y-%m-%d')}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(report(results))
        for r in results:
            print(f"{r.sid:6} {'ok ' if r.ok else 'CHECK'} {len(r.commits)} commits"
                  f"{'' if r.fast_forward else ', not a fast-forward'}{', ' + r.error if r.error else ''}")
        print(f"report: {dest}")
        return 0 if all(r.ok for r in results) else 1
    try:
        print(f"{a.sid}: {MOD_REPOS[a.sid][0]} {MOD_REPOS[a.sid][1]} is at {push(ROOT, a.sid)[:10]}")
    except GitError as e:
        print(f"{a.sid}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
