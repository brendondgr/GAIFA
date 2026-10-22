"""`python -m evals.compact_live [model]`: compaction on the real model (plan 14's check that compaction
keeps a thread working past 85%). The thread's window is capped at 9,000 tokens so a few turns with
tool results fill it; the last turn asks about the first one, which only the summary still holds.
The chat is deleted afterwards."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from .cleanup import forget_threads

TURNS = ["Hi! My favourite animal is the snow leopard (just for this chat; no need to save it to memory). Now, which mods are running?",
         "How much memory is free right now, and what does each mod hold?",
         "List my saved voices and the Kokoro voices.",
         "Search my outputs for images and list the five newest with their titles.",
         "Which models are on disk? Just the LLMs.",
         "Show me the tools you have for speech, with a one-line description each.",
         "Which mods are running now, and are any of them busy?",
         "What's my favourite animal, which I told you at the start?"]


async def main(model: str) -> None:
    rows = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:7000/api/s/agent", timeout=900) as c:
        tid = (await c.post("/v1/threads", json={"title": "compaction check", "model": model, "settings": {"window": 6000}})).json()["id"]
        for text in TURNS:
            await c.post(f"/v1/threads/{tid}/messages", json={"text": text})
            for _ in range(1200):
                t = (await c.get(f"/v1/threads/{tid}")).json()
                if not t["running"]:
                    break
                await asyncio.sleep(0.5)
            m = (await c.get(f"/v1/threads/{tid}/context")).json()
            evs = (await c.get(f"/v1/threads/{tid}/events")).json()
            rows.append({"turn": text, "state": t["state"], "used": m["used"], "window": m["window"], "percent": m["percent"],
                         "compactions": [e["payload"]["stage"] for e in evs if e["type"] == "compact"],
                         "reply": next((e["payload"]["text"] for e in reversed(evs) if e["type"] == "assistant"), "")[:300]})
            print(json.dumps(rows[-1]), flush=True)
        # then /compact by hand: the model writes the summary, and the first turn now lives only in it
        before = (await c.get(f"/v1/threads/{tid}/context")).json()
        after = (await c.post(f"/v1/threads/{tid}/compact")).json()
        await c.post(f"/v1/threads/{tid}/messages", json={"text": "Remind me: what's my favourite animal?"})
        for _ in range(1200):
            if not (await c.get(f"/v1/threads/{tid}")).json()["running"]:
                break
            await asyncio.sleep(0.5)
        evs = (await c.get(f"/v1/threads/{tid}/events")).json()
        final = next((e["payload"]["text"] for e in reversed(evs) if e["type"] == "assistant"), "")
        rows.append({"turn": "/compact, then: Remind me: what's my favourite animal?", "used_before": before["used"],
                     "used_after": after["used"], "window": after["window"], "reply": final[:300],
                     "compactions": [e["payload"]["stage"] for e in evs if e["type"] == "compact"]})
        print(json.dumps(rows[-1]), flush=True)
        summ = [e["payload"].get("summary") for e in evs if e["type"] == "compact" and e["payload"].get("stage") == "summary"]
    clears = rows[-2]["compactions"].count("clear")
    out = {"model": model, "thread": tid, "rows": rows, "summary": summ[-1] if summ else None, "clears": clears,
           "ok": bool(summ) and clears > 0 and "leopard" in final.lower() and "leopard" in rows[-2]["reply"].lower()}
    p = Path(__file__).resolve().parents[3] / "docs" / "report" / "data" / "compact-live.json"
    p.write_text(json.dumps(out, indent=1))
    print("ok", out["ok"])
    await forget_threads([tid])                 # the chat and its outputs go; the report keeps the numbers


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "skynet"))
