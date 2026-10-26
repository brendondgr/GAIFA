"""`gaifa repos`: mods that are their own repositories (plan mod-repos 3.2). Standard library only,
loaded on demand by `cli.py`.

    gaifa repos [status] [--json]        each submodule: pin, checkout, branch, ahead/behind, problems
    gaifa repos fetch [<id>|all]         ask GitHub what's new (the only command that reads the network
                                         besides update and sync)
    gaifa repos update <id>|all [--to REV] [--dry-run] [--commit] [--force-busy]
    gaifa repos pin <id> [--commit]      record the checkout as GAIFA's pin
    gaifa repos sync [<id>|all]          check out GAIFA's pins (after a clone or a pull)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__:
    from utils import repos, repos_update
else:                                    # bin/gaifa runs utils/cli.py as a script, next to these files
    import repos  # type: ignore[no-redef]
    import repos_update  # type: ignore[no-redef]

cli: Any = None                          # utils/cli.py sets it (call, q, ROOT, HubDown, ApiError)
MARK = {None: "ok   ", "info": "info ", "warn": "WARN ", "error": "ERROR"}


def _root() -> Path:
    return Path(cli.ROOT)


def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = time.time() - ts
    return f"{int(s // 60)}m ago" if s < 3600 else f"{int(s // 3600)}h ago" if s < 172800 else f"{int(s // 86400)}d ago"


def cmd_status(args: argparse.Namespace) -> int:
    states = repos.list_states(_root())
    if args.json:
        print(json.dumps([s.to_dict() for s in states], indent=1))
        return 1 if any(s.level in ("warn", "error") for s in states) else 0
    if not states:
        print("no mods are submodules (.gitmodules lists none)")
        return 0
    for s in states:
        pin = (s.pinned or "?")[:10]
        where = "not checked out" if not s.initialized else \
            f"{(s.head or '?')[:10]} on {s.on_branch}" if s.on_branch else f"{(s.head or '?')[:10]} detached"
        extra = []
        if s.behind:
            extra.append(f"{s.behind} new on {s.branch}")
        if s.staged_pin:
            extra.append(f"pin staged → {s.staged_pin[:10]}")
        print(f"{MARK[s.level]} {s.id:<8} pinned {pin}  checkout {where}  {s.url} {s.branch}"
              + (f"  ({', '.join(extra)})" if extra else "") + f"  fetched {_ago(s.last_fetch_ts)}")
        for p in s.problems:
            print(f"        {p.level}: {p.title}" + (f"\n          {p.detail}" if p.detail else "") + (f"\n          fix: {p.fix}" if p.fix else ""))
    return 1 if any(s.level in ("warn", "error") for s in states) else 0


def _ids(which: str | None) -> list[str]:
    known = [s[0] for s in repos.submodules(_root())]
    if not which or which == "all":
        return known
    if which not in known:
        raise SystemExit(f"gaifa repos: {which} isn't a submodule (these are: {', '.join(known) or 'none'})")
    return [which]


def cmd_fetch(args: argparse.Namespace) -> int:
    bad = 0
    for sid in _ids(args.id):
        error = repos.fetch(_root(), sid)
        st = repos.repo_state(_root(), sid)
        print(f"{sid}: " + (f"couldn't fetch: {error}" if error else f"{st.behind} new commit(s) on {st.branch}" if st.behind else "up to date"))
        bad += bool(error)
    return 1 if bad else 0


# ---- hooks: the running hub over HTTP ---------------------------------------------------------------

def _service(sid: str) -> dict | None:
    try:
        return cli.call("GET", f"/api/services/{cli.q(sid)}")
    except (cli.HubDown, cli.ApiError):
        return None


def hooks() -> repos_update.Hooks:
    def install(sid: str) -> int:
        return cli._mods().run_install(_root() / "services" / sid)

    def running(sid: str) -> bool:
        s = _service(sid)
        return bool(s) and s.get("state") in ("ready", "starting", "unhealthy")

    def restart(sid: str) -> None:
        cli.call("POST", f"/api/services/{cli.q(sid)}/restart?wait=1", timeout=cli.WAIT_S)

    def check(sid: str) -> tuple[bool | None, str]:
        try:
            r = cli.call("GET", f"/api/services/{cli.q(sid)}/check", timeout=cli.WAIT_S)
        except cli.HubDown:
            return None, "the hub isn't running"
        except cli.ApiError as e:
            return False, e.detail
        failed = [f"{c['name']}: {c['detail']}" for c in r["checks"] if c["status"] == "fail"]
        return (not failed), "; ".join(failed) or "all checks passed"

    def busy(sid: str) -> str | None:
        s = _service(sid) or {}
        jobs = [j for j in s.get("jobs") or [] if j.get("state") in ("queued", "running")]
        return f"{len(jobs)} job(s): " + ", ".join(j.get("label", "?") for j in jobs[:3]) if jobs else None

    def tests() -> tuple[bool, str]:
        r = subprocess.run(["uv", "run", "pytest", "-q", "-x"], cwd=_root(), capture_output=True, text=True, timeout=1800)
        tail = (r.stdout.strip().splitlines() or [""])[-1]
        return r.returncode == 0, tail

    return repos_update.Hooks(install=install, running=running, restart=restart, check=check, busy=busy,
                              progress=lambda m: print(f"  … {m}"), tests=tests)


def _print(r: repos_update.Result) -> int:
    for c in r.commits[:20]:
        print(f"    {c}")
    if len(r.commits) > 20:
        print(f"    … and {len(r.commits) - 20} more")
    print(f"{r.id}: {r.message}" + (f"  [refused: {', '.join(r.refused)}]" if r.refused else ""))
    if r.staged:
        print(f"  the pin is staged: run the tests (uv run pytest) and commit GAIFA, or `gaifa repos update {r.id} --commit` next time")
    if r.committed:
        print(f"  committed {r.committed[:10]}")
    return 0 if r.ok else 1


def cmd_update(args: argparse.Namespace) -> int:
    if args.to and (not args.id or args.id == "all"):
        raise SystemExit("gaifa repos: --to needs one mod")
    rc = 0
    for sid in _ids(args.id):
        rc |= _print(repos_update.update(_root(), sid, to=args.to, dry_run=args.dry_run, force_busy=args.force_busy,
                                         commit=args.commit, hooks=hooks()))
    return rc


def cmd_pin(args: argparse.Namespace) -> int:
    return _print(repos_update.pin(_root(), args.id, commit=args.commit))


def cmd_sync(args: argparse.Namespace) -> int:
    rc = 0
    for sid in _ids(args.id):
        rc |= _print(repos_update.sync(_root(), sid))
    return rc


def cmd_repos(args: argparse.Namespace) -> int:
    fn = {"status": cmd_status, "fetch": cmd_fetch, "update": cmd_update, "pin": cmd_pin, "sync": cmd_sync}[args.repos_cmd or "status"]
    if args.repos_cmd is None:
        args.json = False
    return fn(args)


def add_parser(sub: Any) -> None:
    p = sub.add_parser("repos", help="mods that are their own repositories: status | fetch | update | pin | sync")
    rs = p.add_subparsers(dest="repos_cmd", metavar="action")
    s = rs.add_parser("status", help="each submodule's pin, checkout and problems (exit 1 on a warning or error)")
    s.add_argument("--json", action="store_true")
    f = rs.add_parser("fetch", help="ask GitHub what's new")
    f.add_argument("id", nargs="?")
    u = rs.add_parser("update", help="move a mod to its branch's head: install, restart, check, roll back on failure")
    u.add_argument("id")
    u.add_argument("--to", help="a commit, tag or branch instead of the branch's head")
    u.add_argument("--dry-run", action="store_true", help="show the commits it would bring in")
    u.add_argument("--commit", action="store_true", help="run GAIFA's tests and commit the pin")
    u.add_argument("--force-busy", action="store_true", help="update even while the mod runs jobs")
    pn = rs.add_parser("pin", help="record the mod's checkout as GAIFA's pin")
    pn.add_argument("id")
    pn.add_argument("--commit", action="store_true", help="commit the pin (only it)")
    sy = rs.add_parser("sync", help="check out GAIFA's pins (git submodule update --init)")
    sy.add_argument("id", nargs="?")
    p.set_defaults(fn=lambda a: cmd_repos(a))


if __name__ == "__main__":
    sys.exit("run it as `gaifa repos`")
