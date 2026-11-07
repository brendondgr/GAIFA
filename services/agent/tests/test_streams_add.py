"""chat-responsive 3.1: chats added to an open `/v1/streams` connection (replayed after their seq, then live) or removed
from it, without a reconnect; an ended or unknown stream is a 404. Served over real HTTP (ASGI transports don't stream)."""

from __future__ import annotations

import asyncio
import json

import httpx

from .conftest import serve


async def test_add_and_remove_on_an_open_stream(env):
    env.model.queue({"text": "A1."}, {"text": "B1."})
    a, b = await env.thread(), await env.thread()
    await env.send(a, "one")
    await env.send(b, "two")
    server, task, port = await serve(env.app)
    base, evs = f"http://127.0.0.1:{port}", []

    async def until(pred, timeout=10):
        for _ in range(int(timeout / 0.02)):
            if pred(evs):
                return
            await asyncio.sleep(0.02)
        raise TimeoutError([e.get("type") for e in evs])

    async with httpx.AsyncClient(timeout=20) as c:
        async def read():
            async with c.stream("GET", f"{base}/v1/streams?threads={a}:0") as r:
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        evs.append(json.loads(line[6:]))
        reader = asyncio.create_task(read())
        try:
            await until(lambda e: any(x["type"] == "ready" for x in e))
            sid = evs[0]["id"]
            assert evs[0]["type"] == "stream" and sid.startswith("s_")
            r = await c.post(f"{base}/v1/streams/{sid}/threads", json={"add": [[b, 0], ["t_nope", 0]]})
            assert r.status_code == 200 and r.json()["threads"] == sorted([a, b])
            await until(lambda e: any(x["type"] == "ready" and x["thread_id"] == b for x in e))
            got_b = [x["payload"].get("text") for x in evs if x.get("thread_id") == b and x["type"] in ("user", "assistant")]
            assert got_b == ["two", "B1."]                                   # its replay, on the same connection
            assert any(x["type"] == "gone" and x["thread_id"] == "t_nope" for x in evs)
            await c.post(f"{base}/v1/streams/{sid}/threads", json={"remove": [a]})
            env.model.queue({"text": "A2."}, {"text": "B2."})
            await env.send(a, "again")
            await env.send(b, "again")
            await until(lambda e: any(x.get("thread_id") == b and x["type"] == "assistant" and x["payload"]["text"] == "B2." for x in e))
            assert not any(x.get("thread_id") == a and x["type"] == "assistant" and x["payload"]["text"] == "A2." for x in evs)
            assert (await c.post(f"{base}/v1/streams/s_unknown/threads", json={"add": [[a, 0]]})).status_code == 404
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            server.should_exit = True
            await task
