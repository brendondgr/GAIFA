"""`python -m evals.meter_check [model]`: the context meter against what the model reports.

Before each turn, the meter's `used` (last usage + estimate of what was added) is compared with the
`prompt_tokens` the model then reports for that turn's first call."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

TURNS = ["Hi! In one sentence: what can you help me with?", "Tell me a two-line poem about foxes.",
         "What's running right now?", "Summarize our chat in one sentence."]


async def main(model: str) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:7000/api/s/agent", timeout=600) as c:
        tid = (await c.post("/v1/threads", json={"title": "meter check", "model": model})).json()["id"]
        rows = []
        for text in TURNS:
            before = (await c.get(f"/v1/threads/{tid}/context")).json()
            n0 = len((await c.get(f"/v1/threads/{tid}/events")).json())
            await c.post(f"/v1/threads/{tid}/messages", json={"text": text})
            for _ in range(600):
                if not (await c.get(f"/v1/threads/{tid}")).json()["running"]:
                    break
                await asyncio.sleep(0.5)
            evs = (await c.get(f"/v1/threads/{tid}/events")).json()[n0:]
            first = next((e["payload"] for e in evs if e["type"] == "usage"), None)
            if first and before.get("used") and not before.get("estimated"):
                predicted = before["used"] + len(text) // 4 + 4
                rows.append({"turn": text, "predicted": predicted, "actual": first["prompt_tokens"],
                             "error_pct": round(100 * (predicted - first["prompt_tokens"]) / first["prompt_tokens"], 1)})
        print(json.dumps(rows, indent=1))
        out = {"model": model, "rows": rows, "ts": time.time()}
        from pathlib import Path
        p = Path(__file__).resolve().parents[3] / "docs" / "report" / "data" / f"meter-{model}.json"
        p.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "skynet"))
