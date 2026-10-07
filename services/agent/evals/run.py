"""`python -m evals.run [--model skynet] [--runs 3] [--live] [--all-tools] [--only a,b] [--out file.json]`

Runs the eval tasks against the agent (through the hub's proxy by default) and writes every run,
its checks and a pass^k summary as JSON. `--live` makes real outputs (no dry run).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from .harness import Harness, dump, grade, summary
from .tasks import TASKS


async def main(a: argparse.Namespace) -> int:
    tasks = [t for t in TASKS if not a.only or t.id in a.only.split(",")]
    h = Harness(a.base, a.model, dry_run=not a.live, all_tools=a.all_tools)
    rows: list[dict] = []
    sem = asyncio.Semaphore(a.concurrency)
    started = time.time()

    async def one(t, i):
        async with sem:
            run = await h.run(t)
            row = grade(t, run)
            row["run"] = i
            rows.append(row)
            bad = [c["check"] for c in row["checks"] if not c["ok"]]
            print(f"[{len(rows):3}/{len(tasks) * a.runs}] {t.id:22} run {i} {'PASS' if row['ok'] else 'FAIL'} "
                  f"{row['seconds']:6.1f}s tools={row['tools']}" + (f" failed={bad}" if bad else "")
                  + (f" error={run.error} {run.extra.get('traceback', '')[-400:]}" if run.error else ""), flush=True)

    try:
        await asyncio.gather(*(one(t, i) for i in range(1, a.runs + 1) for t in tasks))
    finally:
        await h.close()
    s = summary(rows, a.runs)
    if h.glitches:
        print(f"{len(h.glitches)} transient HTTP failures were retried, e.g. {h.glitches[:3]}")
    out = {"glitches": h.glitches[:50], "model": a.model, "runs": a.runs, "dry_run": not a.live, "all_tools": a.all_tools, "started": started,
           "seconds": round(time.time() - started, 1), "summary": s, "rows": sorted(rows, key=lambda r: (r["task"], r["run"]))}
    if a.out:
        dump(a.out, out)
    print(json.dumps({k: v for k, v in s.items() if k != "by_task"}, indent=1))
    for t in s["by_task"]:
        print(f"  {t['task']:22} {t['passes']}/{t['runs']} {'' if t['pass_k'] else 'FAILED: ' + ', '.join(t['failed_checks'])}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:7000/api/s/agent")
    p.add_argument("--model", default="skynet")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--live", action="store_true")
    p.add_argument("--all-tools", action="store_true")
    p.add_argument("--only")
    p.add_argument("--out")
    p.add_argument("--concurrency", type=int, default=3)
    raise SystemExit(asyncio.run(main(p.parse_args())))
