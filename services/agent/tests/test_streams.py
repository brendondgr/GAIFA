"""chat-split 3.1: `/v1/streams` sends several threads' events on one connection: each thread's stored events
after its seq and a `ready`, then live events of all of them; an unknown thread gets `gone`. The agent is served
over real HTTP (ASGI transports don't stream)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent.streams import parse_threads

from .conftest import serve


async def read_events(url: str, until, timeout: float = 10) -> list[dict]:
    """The stream's events until `until(events)` is true."""
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("GET", url) as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            async def go():
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        out.append(json.loads(line[6:]))
                        if until(out):
                            return
            await asyncio.wait_for(go(), timeout)
    return out


def test_parse_threads():
    assert parse_threads("t_a:12, t_b,t_c:0,t_a:3") == [("t_a", 12), ("t_b", 0), ("t_c", 0)]
    assert parse_threads("") == []
    with pytest.raises(Exception):
        parse_threads("t_a:x")
    with pytest.raises(Exception):
        parse_threads(",".join(f"t_{i}" for i in range(65)))


async def test_two_threads_replay_ready_and_gone(env):
    env.model.queue({"text": "A1."}, {"text": "B1."})
    a, b = await env.thread(), await env.thread()
    await env.send(a, "one")
    await env.send(b, "two")
    server, task, port = await serve(env.app)
    try:
        last_a = env.events(a)[0]["seq"]               # a from after its first event; b from the start
        evs = await read_events(f"http://127.0.0.1:{port}/v1/streams?threads={a}:{last_a},{b},t_nope",
                                lambda e: sum(x["type"] in ("ready", "gone") for x in e) == 3)
    finally:
        server.should_exit = True
        await task
    readies = {e["thread_id"]: e for e in evs if e["type"] == "ready"}
    assert set(readies) == {a, b} and not readies[a]["running"]
    assert [e["thread_id"] for e in evs if e["type"] == "gone"] == ["t_nope"]
    stored = lambda t: [e for e in evs if e.get("thread_id") == t and e["type"] not in ("ready", "gone") and e.get("seq")]
    got_a, got_b = stored(a), stored(b)
    assert got_a and all(e["seq"] > last_a for e in got_a), "a's events after its seq only"
    assert [e["seq"] for e in got_b] == [e["seq"] for e in env.agent.store.events(b)], "b's every event, in order"
    assert readies[b]["seq"] == env.events(b)[-1]["seq"]


async def test_live_events_of_both_threads(env):
    a, b = await env.thread(), await env.thread()
    server, task, port = await serve(env.app)
    try:
        url = f"http://127.0.0.1:{port}/v1/streams?threads={a},{b}"
        reader = asyncio.create_task(read_events(url, lambda e: {x.get("thread_id") for x in e if x["type"] == "assistant"} == {a, b}, timeout=20))
        await asyncio.sleep(0.3)                       # connected and subscribed
        env.model.queue({"text": "Reply A."})
        await env.send(a, "hello a")
        env.model.queue({"text": "Reply B."})
        await env.send(b, "hello b")
        evs = await reader
    finally:
        server.should_exit = True
        await task
    texts = {e["thread_id"]: e["payload"]["text"] for e in evs if e["type"] == "assistant"}
    assert texts == {a: "Reply A.", b: "Reply B."}
    seqs = [e["seq"] for e in evs if e.get("thread_id") == a and e["type"] != "ready" and e.get("seq")]
    assert seqs == sorted(set(seqs)), "no repeats, in order"
    assert not env.agent.live.subs.get(a) and not env.agent.live.subs.get(b), "unsubscribed when the client left"
