"""The agent's server-sent event streams: one thread's (`/v1/threads/{tid}/stream`, plan 14.2), and several threads'
on one connection (`/v1/streams`, plan chat-split 3.1), so the Chat page can show any number of chats side by side
without running out of the browser's connections to the hub (about six per host over HTTP/1.1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

MAX_THREADS = 64
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(ev: dict[str, Any]) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


def parse_threads(spec: str) -> list[tuple[str, int]]:
    """`t_a:12,t_b,t_c:0` → [(t_a, 12), (t_b, 0), (t_c, 0)]; repeats keep the first; at most MAX_THREADS."""
    out: dict[str, int] = {}
    for part in (spec or "").split(","):
        tid, _, after = part.strip().partition(":")
        if not tid or tid in out:
            continue
        try:
            out[tid] = max(0, int(after or 0))
        except ValueError:
            raise HTTPException(422, f"bad seq for {tid!r}: {after!r}") from None
    if len(out) > MAX_THREADS:
        raise HTTPException(422, f"at most {MAX_THREADS} threads per stream")
    return list(out.items())


def ready(agent: Any, tid: str, seq: int) -> dict[str, Any]:
    """A stream's `ready` for one thread: replayed up to `seq`, whether a turn runs, and its queue (chat-responsive 2.1)."""
    return {"type": "ready", "thread_id": tid, "seq": seq, "running": agent.running(tid), "queue": agent.queue.state(tid)}


def add_stream_routes(app: FastAPI, A: Callable[[Request], Any], thread_or_404: Callable[[Any, str], Any], ping_s: float) -> None:
    @app.get("/v1/threads/{tid}/stream", summary="Server-sent events: the events after `after`, then live events and deltas")
    async def stream(tid: str, request: Request, after: int = 0) -> StreamingResponse:
        agent = A(request)
        thread_or_404(agent, tid)
        q = agent.live.subscribe(tid)

        async def gen():
            last = after
            try:
                yield "retry: 2000\n\n"
                for ev in agent.store.events(tid, after):
                    last = ev["seq"]
                    yield sse(ev)
                yield sse(ready(agent, tid, last))
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=ping_s)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if ev.get("seq") is not None:
                        if ev["seq"] <= last:
                            continue
                        last = ev["seq"]
                    yield sse(ev)
            finally:
                agent.live.unsubscribe(tid, q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers=HEADERS)

    @app.get("/v1/streams", summary="Server-sent events for several threads on one connection: each thread's events after its "
                                    "seq and a `ready` for it, then live events and deltas of all of them (each has `thread_id`); "
                                    "an unknown thread gets `{type: 'gone', thread_id}`")
    async def streams(request: Request, threads: str = "") -> StreamingResponse:
        agent = A(request)
        wanted = parse_threads(threads)
        known = [(tid, after) for tid, after in wanted if agent.store.thread(tid) is not None]
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(4000)
        for tid, _ in known:                       # before the replay, so nothing that happens meanwhile is missed
            agent.live.subscribe(tid, q)

        async def gen():
            last = dict(known)
            try:
                yield "retry: 2000\n\n"
                for tid, after in wanted:
                    if tid not in last:
                        yield sse({"type": "gone", "thread_id": tid})
                        continue
                    for ev in agent.store.events(tid, after):
                        last[tid] = ev["seq"]
                        yield sse(ev)
                    yield sse(ready(agent, tid, last[tid]))
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=ping_s)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    tid = ev.get("thread_id")
                    if tid not in last:
                        continue
                    if ev.get("seq") is not None:
                        if ev["seq"] <= last[tid]:
                            continue
                        last[tid] = ev["seq"]
                    yield sse(ev)
            finally:
                for tid, _ in known:
                    agent.live.unsubscribe(tid, q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers=HEADERS)
