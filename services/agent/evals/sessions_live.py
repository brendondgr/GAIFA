"""`python -m evals.sessions_live STEP`: the Phase 15 check on the real mods, one step at a time.

    save NAME        save what runs and what's loaded now
    switch NAME      dry run (print the plan), then restore, sampling memory every second
    load ID / unload ID / stop-llms

Memory samples go to docs/report/data/session-<name>.json, to show it never passed the limit.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

HUB = "http://127.0.0.1:7000"
OUT = Path(__file__).resolve().parents[3] / "docs" / "report" / "data"


async def sample(c: httpx.AsyncClient, stop: asyncio.Event, out: list) -> None:
    while not stop.is_set():
        m = (await c.get("/api/memory")).json()
        out.append({"t": time.time(), "used_gb": round(m["used_bytes"] / 1e9, 2), "total_gb": round(m["total_bytes"] / 1e9, 2),
                    "by": {s["id"]: round(s["used_bytes"] / 1e9, 1) for s in m["by_service"] if s["used_bytes"] > 2e8}})
        try:
            await asyncio.wait_for(stop.wait(), 1)
        except asyncio.TimeoutError:
            pass


async def main(argv: list[str]) -> None:
    async with httpx.AsyncClient(base_url=HUB, timeout=1800) as c:
        cmd = argv[0]
        if cmd == "save":
            s = (await c.post("/api/sessions", json={"name": argv[1]})).json()
            print(json.dumps({k: s[k] for k in ("id", "name", "summary")}))
        elif cmd == "switch":
            sid = argv[1]
            dry = (await c.post(f"/api/sessions/{sid}/restore?dry_run=1")).json()
            print("PLAN", json.dumps(dry["steps"]), json.dumps(dry["memory"]))
            samples: list = []
            stop = asyncio.Event()
            t = asyncio.create_task(sample(c, stop, samples))
            t0 = time.time()
            r = (await c.post(f"/api/sessions/{sid}/restore")).json()
            await asyncio.sleep(3)
            stop.set()
            await t
            peak = max(x["used_gb"] for x in samples)
            limit = samples[0]["total_gb"] - 12
            print("RESULT ok=", r.get("ok"), "seconds=", round(time.time() - t0, 1), "peak_gb=", peak, "limit_gb=", limit,
                  json.dumps([{k: x.get(k) for k in ("action", "target", "ok", "error")} for x in r.get("results", [])]))
            OUT.mkdir(parents=True, exist_ok=True)
            n = len(list(OUT.glob("session-*.json"))) + 1
            (OUT / f"session-{n}-{sid.replace(' ', '_')}.json").write_text(json.dumps({"plan": dry, "result": r, "samples": samples,
                                                                                   "peak_gb": peak, "limit_gb": limit}, indent=1))
        elif cmd in ("load", "unload"):
            r = await c.post(f"/api/services/{argv[1]}/{cmd}" + ("?make_room=1" if cmd == "load" else ""))
            print(r.status_code, r.text[:200])
            for _ in range(600):
                st = (await c.get(f"/api/services/{argv[1]}")).json()["load"]
                if st in ("loaded", "unloaded"):
                    break
                await asyncio.sleep(1)
            print(argv[1], st)
        elif cmd == "stop-llms":
            r = await c.post("/api/s/lcpp/api/instances/stop-all")
            print(r.status_code, r.text[:200])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
