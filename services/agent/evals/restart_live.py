"""`python -m evals.restart_live`: plan 14's check that a pending question and a pending approval both
survive restarts of the hub and the agent (live, on the real stack).

1. thread A asks for an image → a parameter card waits (an approval in hub.db)
2. thread B asks for "an image" with no subject → a question card waits
3. `aihub restart` (the hub) and `aihub restart agent`
4. both threads are still waiting; the approval is still pending at the hub
5. approve A and answer B → both finish with an image
6. both chats and their images are deleted
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx

from .cleanup import forget_threads

A = "http://127.0.0.1:7000/api/s/agent"
OUT = Path(__file__).resolve().parents[3] / "docs" / "report" / "data" / "restart-live.json"


async def until(c: httpx.AsyncClient, tid: str, states: tuple[str, ...], timeout: float = 600) -> str:
    end = time.time() + timeout
    while time.time() < end:
        try:
            t = (await c.get(f"/v1/threads/{tid}")).json()
            if t.get("state") in states and not t.get("running"):
                return t["state"]
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(1)
    raise TimeoutError(f"{tid} not in {states}")


async def main() -> None:
    log: dict = {"steps": []}
    async with httpx.AsyncClient(base_url=A, timeout=60) as c:
        a = (await c.post("/v1/threads", json={"title": "restart test: card", "model": "skynet"})).json()["id"]
        b = (await c.post("/v1/threads", json={"title": "restart test: question", "model": "skynet"})).json()["id"]
        await c.post(f"/v1/threads/{a}/messages", json={"text": "Make a 1:1 image of a red lighthouse on a rocky coast."})
        await c.post(f"/v1/threads/{b}/messages", json={"text": "Make me an image. Ask me what of, with a question card."})
        sa, sb = await until(c, a, ("waiting", "idle", "error")), await until(c, b, ("waiting", "idle", "error"))
        evs_a = (await c.get(f"/v1/threads/{a}/events")).json()
        evs_b = (await c.get(f"/v1/threads/{b}/events")).json()
        ap = [e["payload"] for e in evs_a if e["type"] == "approval"]
        q = [e["payload"] for e in evs_b if e["type"] == "question"]
        log["steps"].append({"before_restart": {"a": sa, "b": sb, "approval": bool(ap), "question": bool(q)}})
        if not (ap and q):
            log["ok"] = False
            log["why"] = "the setup didn't produce both a card and a question"
            OUT.write_text(json.dumps(log, indent=1))
            print(json.dumps(log, indent=1))
            await forget_threads([a, b])
            return
    t0 = time.time()
    subprocess.run(["aihub", "restart"], capture_output=True, timeout=120)
    subprocess.run(["aihub", "restart", "agent"], capture_output=True, timeout=120)
    log["restart_seconds"] = round(time.time() - t0, 1)
    async with httpx.AsyncClient(base_url=A, timeout=60) as c:
        for _ in range(60):
            try:
                if (await c.get("/v1/threads?limit=1")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        ta, tb = (await c.get(f"/v1/threads/{a}")).json(), (await c.get(f"/v1/threads/{b}")).json()
        pending = httpx.get("http://127.0.0.1:7000/api/approvals").json()
        log["steps"].append({"after_restart": {"a": ta["state"], "b": tb["state"],
                                               "approval_pending_at_hub": any(x["id"] == ap[0]["approval_id"] for x in pending)}})
        r1 = await c.post(f"/v1/threads/{a}/approval", json={"approval_id": ap[0]["approval_id"], "approve": True})
        r2 = await c.post(f"/v1/threads/{b}/answer", json={"question_id": q[0]["id"],
                                                          "answers": {x["question"]: "A hot air balloon over mountains at dawn" for x in q[0]["questions"]}})
        log["steps"].append({"decided": [r1.status_code, r2.status_code]})
        fa = await until(c, a, ("idle", "error", "waiting"), 900)
        # thread B may show its own card for the image now: approve it too
        for _ in range(3):
            fb = await until(c, b, ("idle", "error", "waiting"), 900)
            if fb != "waiting":
                break
            evs = (await c.get(f"/v1/threads/{b}/events")).json()
            decided = {e["payload"]["approval_id"] for e in evs if e["type"] == "decision"}
            for e in evs:
                if e["type"] == "approval" and e["payload"]["approval_id"] not in decided:
                    await c.post(f"/v1/threads/{b}/approval", json={"approval_id": e["payload"]["approval_id"], "approve": True})
        outs = {}
        for name, tid in (("a", a), ("b", b)):
            evs = (await c.get(f"/v1/threads/{tid}/events")).json()
            outs[name] = [o["kind"] for e in evs if e["type"] == "tool_result" for o in e["payload"].get("outputs") or []]
        log["steps"].append({"finished": {"a": fa, "b": fb, "outputs": outs}})
        log["ok"] = (log["steps"][1]["after_restart"]["a"] == "waiting" and log["steps"][1]["after_restart"]["b"] == "waiting"
                     and log["steps"][1]["after_restart"]["approval_pending_at_hub"] and "image" in outs["a"] and "image" in outs["b"])
        log["threads"] = {"a": a, "b": b}
    OUT.write_text(json.dumps(log, indent=1))
    print(json.dumps(log, indent=1))
    await forget_threads([a, b])                # the chats and their images go; the report keeps the log


if __name__ == "__main__":
    asyncio.run(main())
