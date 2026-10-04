"""`aihub models list | show | scan | verify` (plan Phase 3). Standard library only;
loaded by `cli.py` when a models command runs, which sets `cli` to that module."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

cli: Any = None  # utils/cli.py, set by cli._models()

POLL_S = 0.5


def cmd_models(args: argparse.Namespace) -> int:
    return {"list": _list, "show": _show, "scan": _scan, "verify": _verify}[args.action](args)


def _list(args: argparse.Namespace) -> int:
    q = {"kind": args.kind, "status": args.status, "service": args.service, "q": args.q}
    query = "&".join(f"{k}={cli.q(v)}" for k, v in q.items() if v)
    r = cli.call("GET", "/api/models" + (f"?{query}" if query else ""))
    rows = [["ID", "KIND", "STATUS", "SIZE", "USED BY", "NAME"]]
    for m in r["models"]:
        status = m["status"] + (f" {m['progress']:.0%}" if m["status"] == "verifying" else "")
        rows.append([m["id"], m["kind"], status, cli.human_bytes(m["size_bytes"]), ",".join(m["services"]) or "-", m["name"]])
    if len(rows) > 1:
        print(cli.table(rows))
    t, d = r["totals"], r["disk"]
    shown = f"{len(r['models'])} of {t['count']}" if len(r["models"]) != t["count"] else str(t["count"])
    print(f"{shown} models · {cli.human_bytes(t['size_bytes'])} on disk · {cli.human_bytes(d['free_bytes'])} free")
    bad = [m for m in r["models"] if m["problems"]]
    for m in bad[:20] if args.problems else []:
        for p in m["problems"]:
            print(f"  {m['id']}: {p}")
    return 0


def _show(args: argparse.Namespace) -> int:
    if not args.ids:
        print("aihub models show: which model? (aihub models list)", file=sys.stderr)
        return 2
    for mid in args.ids:
        m = cli.call("GET", f"/api/models/{cli.q(mid)}")
        src = m.get("source") or {}
        print(f"{m['name']} ({m['id']})  {m['kind']} · {m['format']} · {m['status']} · {cli.human_bytes(m['size_bytes'])}")
        print(f"  path     data/models/{m['path']}")
        print(f"  used by  {', '.join(m['services']) or '-'}")
        if src:
            print("  source   " + " ".join(f"{k}={v}" for k, v in src.items()))
        rows = [["ROLE", "SIZE", "SHA256", "", "PATH"]]
        for f in m["files"]:
            mark = "verified" if f["verified"] else ("missing" if not f["exists"] else "-")
            rows.append([f["role"], cli.human_bytes(f["size_bytes"] or 0), (f["sha256"] or "-")[:16], mark, f["path"]])
        print("\n".join("  " + line for line in cli.table(rows).splitlines()))
        for p in m["problems"]:
            print(f"  ! {p}")
    return 0


def _scan(args: argparse.Namespace) -> int:
    found = cli.call("POST", "/api/models/scan", timeout=300)["discovered"]
    if not found:
        print("nothing new: every model file in data/models is registered")
        return 0
    rows = [["PATH", "KIND", "SIZE", "FILES", "SUGGESTED ID"]]
    for d in found:
        rows.append([d["path"], d["suggested_kind"], cli.human_bytes(d["size_bytes"]), str(len(d["files"])), d["suggested_id"]])
    print(cli.table(rows))
    if not args.add:
        print(f"{len(found)} not registered. Add them all with `aihub models scan --add`, or one by one on the Models page.")
        return 0
    failed = 0
    for d in found:
        body = {"path": d["path"], "name": d["suggested_name"], "kind": d["suggested_kind"], "id": d["suggested_id"]}
        if d.get("source"):
            body["source"] = d["source"]
        try:
            m = cli.call("POST", "/api/models", body)
            print(f"added {m['id']}")
        except cli.ApiError as e:
            failed += 1
            print(f"skipped {d['path']}: {e.detail}", file=sys.stderr)
    return 1 if failed else 0


def _verify(args: argparse.Namespace) -> int:
    ids = list(args.ids)
    if args.all:
        ids = [m["id"] for m in cli.call("GET", "/api/models")["models"] if any(f["exists"] for f in m["files"])]
    if not ids:
        print("aihub models verify: which model? (an id, or --all)", file=sys.stderr)
        return 2
    started = []
    for mid in ids:
        try:
            cli.call("POST", f"/api/models/{cli.q(mid)}/verify" + ("?reset=1" if args.reset else ""))
            started.append(mid)
        except cli.ApiError as e:
            print(f"{mid}: {e.detail}", file=sys.stderr)
    if args.no_wait or not started:
        if started:
            print(f"verifying {', '.join(started)} in the background")
        return 0 if started else 1
    tty = sys.stdout.isatty()
    pending, results = set(started), {}
    while pending:
        r = {m["id"]: m for m in cli.call("GET", "/api/models")["models"] if m["id"] in pending}
        for mid in list(pending):
            m = r.get(mid)
            if m is None:
                pending.discard(mid)
                results[mid] = {"status": "removed", "problems": []}
            elif m["status"] != "verifying":
                pending.discard(mid)
                results[mid] = m
                if tty:
                    print("\r\033[K", end="")
                print(f"{mid}: {m['status']}")
                for p in m["problems"]:
                    print(f"  {p}")
            elif tty:
                print(f"\r\033[K{mid}: {m['progress']:.0%} of {cli.human_bytes(m['size_bytes'])}", end="", flush=True)
        if pending:
            time.sleep(POLL_S)
    bad = [mid for mid, m in results.items() if m["status"] in ("checksum_mismatch", "partial", "missing")]
    return 1 if bad else 0
