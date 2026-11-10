"""Plan calendar 8.1: GET /v1/history: per day, the chats with a message of yours, from their first to their last event;
a chat across two days is on both; archived chats too; a range that's too long is refused."""

from __future__ import annotations

import time

from agent.api_history import history


async def test_days_and_chats(env):
    tid = await env.thread()
    env.model.queue({"text": "hi"})
    await env.send(tid, "hello")
    now = time.time()
    r = (await env.client.get("/v1/history", params={"from": now - 3600, "to": now + 60})).json()
    row = next(c for c in r["chats"] if c["thread_id"] == tid)
    assert row["turns"] == 1 and row["first"] <= row["last"] and row["day"] == time.strftime("%Y-%m-%d")
    await env.client.patch(f"/v1/threads/{tid}", json={"archived": True})
    assert any(c["thread_id"] == tid for c in (await env.client.get("/v1/history", params={"from": now - 3600, "to": now + 60})).json()["chats"])
    assert (await env.client.get("/v1/history", params={"from": now, "to": now + 90 * 86400})).status_code == 422


async def test_across_two_days(env):
    tid = await env.thread()
    st = env.agent.store
    day1 = time.mktime((2026, 11, 9, 23, 50, 0, 0, 0, -1))
    with st._lock:
        for i, (ts, kind) in enumerate([(day1, "user"), (day1 + 300, "text"), (day1 + 1200, "user"), (day1 + 1500, "text")], start=900):
            st._c.execute("INSERT INTO events (thread_id, seq, ts, type, payload) VALUES (?, ?, ?, ?, '{}')", (tid, i, ts, kind))
    rows = [r for r in history(st, day1 - 60, day1 + 3600) if r["thread_id"] == tid]
    assert [(r["day"], r["turns"]) for r in rows] == [("2026-11-09", 1), ("2026-11-10", 1)]
