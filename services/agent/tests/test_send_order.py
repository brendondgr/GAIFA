"""chat-responsive 1.1: the user event is written before recall, the turn's model call still sees what was recalled,
and a message sent as a turn ends is never left unanswered."""

from __future__ import annotations

import asyncio
import time


async def test_the_user_event_comes_before_a_slow_recall(env):
    m = env.agent.memory
    f = m.add_fact("The hub listens on port 7000", about=[{"name": "GAIFA", "kind": "project"}])
    await env.agent.memory_index.flush()
    env.hub.search_delay = 1.5
    tid = await env.thread()
    t0 = time.monotonic()
    r = await env.send(tid, "which port does GAIFA use?", wait=False, client_id="c-1")
    assert time.monotonic() - t0 < 1.0                          # answered before the search came back
    assert r["payload"]["client_id"] == "c-1" and env.payloads(tid, "user")[-1]["client_id"] == "c-1"
    assert not env.payloads(tid, "recall") and not env.model.received
    await env.settle(tid)
    rec = env.payloads(tid, "recall")
    assert [x["id"] for x in rec[0]["memory"]] == [f["id"]] and rec[0]["for"] == env.events(tid, "user")[-1]["seq"]
    sent = [x for x in env.model.received[-1]["messages"] if x["role"] == "user"][-1]["content"]
    assert "- The hub listens on port 7000" in sent               # the model call waited for it


async def test_a_message_sent_while_the_last_reply_streams_is_answered(env):
    env.model.queue({"text": "a long answer " * 40, "gap": 0.02, "chunk": 4}, {"text": "about the second"})
    tid = await env.thread()
    await env.send(tid, "first", wait=False)
    for _ in range(200):                                          # the reply has begun streaming
        if env.model.received:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)
    r = await env.send(tid, "second", wait=False)
    assert r["payload"].get("queued") is True
    assert await env.settle(tid) == "idle"
    assert len(env.model.received) == 2 and env.payloads(tid, "assistant")[-1]["text"] == "about the second"


async def test_a_message_sent_during_the_turn_end_hooks_starts_a_turn(env):
    gate = asyncio.Event()

    async def slow_hook(tid: str) -> None:
        await gate.wait()

    env.agent.on_turn_end.append(slow_hook)
    env.model.queue({"text": "one"}, {"text": "two"})
    tid = await env.thread()
    await env.send(tid, "first", wait=False)
    for _ in range(300):
        if env.agent.store.thread(tid)["state"] == "idle" and env.payloads(tid, "assistant"):
            break
        await asyncio.sleep(0.01)
    assert env.agent.running(tid) and not env.agent.busy(tid)     # in its hooks
    r = await env.send(tid, "second", wait=False)
    assert "queued" not in r["payload"]
    gate.set()
    await env.settle(tid)
    assert [p["text"] for p in env.payloads(tid, "assistant")] == ["one", "two"]


async def test_stop_stays_stopped_with_an_unread_message(env):
    env.model.queue({"text": "slow", "delay": 1.0}, {"text": "never"})
    tid = await env.thread()
    await env.send(tid, "first", wait=False)
    await asyncio.sleep(0.2)
    await env.client.post(f"/v1/threads/{tid}/cancel")
    assert await env.settle(tid) == "idle" and len(env.model.received) <= 1
