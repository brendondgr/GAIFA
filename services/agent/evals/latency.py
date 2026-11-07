"""`python -m evals.latency [model] [runs]`: how quickly a sent message shows (plan chat-responsive 3.3).

Against the installed hub (through its proxy, as the page talks to the agent), each run:
- **new chat:** `POST /v1/threads` with the first message: until its stored user event comes back (the answer carries
  it), then until the reply's first token on the chat's stream;
- **idle chat:** the same chat once its turn ended, with its stream open: until the user event arrives on the stream,
  and until the first token;
- **queued:** a message sent while the turn streams: until it's held (`{queued}`) and the stream's `queue` event.

Medians over the runs, in milliseconds, printed as a markdown table for docs/agent-eval.md. The chats are learning-off
(`no_learn`) but recall memory as any chat does (recall used to come before the message), and are deleted at the end.
Never part of pytest: it needs the hub, the agent and a model."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time

import httpx

from .cleanup import forget_threads

BASE = "http://127.0.0.1:7000/api/s/agent"
ASK = "[latency check] Reply with just the word ok."


class Watch:
    """A chat's stream, read in the background: when each kind of event first came after `since`."""

    def __init__(self, c: httpx.AsyncClient, tid: str, after: int) -> None:
        self.c, self.tid, self.after, self.seen = c, tid, after, []
        self.task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async with self.c.stream("GET", f"/v1/threads/{self.tid}/stream", params={"after": self.after}, timeout=None) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    self.seen.append((time.monotonic(), json.loads(line[6:])))

    async def first(self, pred, since: float, timeout: float = 300) -> float:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for t, ev in self.seen:
                if t >= since and pred(ev):
                    return (t - since) * 1000
            await asyncio.sleep(0.005)
        raise TimeoutError(f"no matching event in {timeout} s")

    async def close(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def idle(c: httpx.AsyncClient, tid: str) -> int:
    for _ in range(1200):
        t = (await c.get(f"/v1/threads/{tid}")).json()
        if not t["running"] and not (await c.get(f"/v1/threads/{tid}/queue")).json()["items"]:
            break
        await asyncio.sleep(0.25)
    evs = (await c.get(f"/v1/threads/{tid}/events")).json()
    return evs[-1]["seq"] if evs else 0


async def run_once(c: httpx.AsyncClient, model: str | None) -> tuple[dict[str, float], str]:
    out: dict[str, float] = {}
    t0 = time.monotonic()
    r = await c.post("/v1/threads", json={"title": "", "model": model, "settings": {"no_learn": True},
                                          "message": {"text": ASK, "client_id": "latency-1"}})
    r.raise_for_status()
    th = r.json()
    out["new chat: user event"] = (time.monotonic() - t0) * 1000
    w = Watch(c, th["id"], 0)
    try:
        out["new chat: first token"] = await w.first(lambda e: e["type"] == "delta", t0)
    finally:
        await w.close()
    last = await idle(c, th["id"])
    w = Watch(c, th["id"], last)
    try:
        await asyncio.sleep(0.3)                          # the stream is open before the message goes
        t1 = time.monotonic()
        await c.post(f"/v1/threads/{th['id']}/messages", json={"text": ASK, "client_id": "latency-2"})
        out["idle chat: user event on the stream"] = await w.first(lambda e: e["type"] == "user", t1)
        out["idle chat: first token"] = await w.first(lambda e: e["type"] == "delta", t1)
        t2 = time.monotonic()
        q = await c.post(f"/v1/threads/{th['id']}/messages", json={"text": ASK, "client_id": "latency-3"})
        out["queued: held"] = (time.monotonic() - t2) * 1000
        if "queued" in q.json():
            out["queued: queue event on the stream"] = await w.first(lambda e: e["type"] == "queue", t2)
    finally:
        await w.close()
    await idle(c, th["id"])
    return out, th["id"]


async def main(model: str | None, runs: int) -> None:
    rows: dict[str, list[float]] = {}
    made: list[str] = []
    async with httpx.AsyncClient(base_url=BASE, timeout=600) as c:
        try:
            for i in range(runs):
                got, tid = await run_once(c, model)
                made.append(tid)
                for k, v in got.items():
                    rows.setdefault(k, []).append(v)
                print(f"run {i + 1}: " + ", ".join(f"{k} {v:.0f}" for k, v in got.items()), file=sys.stderr)
        finally:
            await forget_threads(made)
    print(f"| Measure ({model or 'the default model'}, {runs} runs) | Median (ms) | Min | Max |\n| --- | --- | --- | --- |")
    for k, v in rows.items():
        print(f"| {k} | {statistics.median(v):.0f} | {min(v):.0f} | {max(v):.0f} |")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None, int(sys.argv[2]) if len(sys.argv) > 2 else 5))
