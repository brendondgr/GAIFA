"""chat-responsive 2.1: messages sent during a turn are held, then sent together when it ends and answered by one turn;
edited, moved, removed or sent now; sent at once by Stop; paused by an error; held while a card waits."""

from __future__ import annotations

import asyncio

from agent.queue import Queue
from agent.store import Store
from agent.streams import ready

RENDER = {"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "x", "seconds": 0.6}}]}


async def running(env, tid):
    for _ in range(200):
        if env.events(tid, "tool_call"):
            await asyncio.sleep(0.05)
            return
        await asyncio.sleep(0.02)
    raise TimeoutError("the tool call never started")


async def drained(env, tid, timeout=15):
    """Until the turn and anything the queue sent after it are done."""
    for _ in range(int(timeout / 0.05)):
        await env.settle(tid)
        await asyncio.sleep(0.05)
        if not env.agent.running(tid) and not env.agent._drains:
            return env.agent.store.thread(tid)["state"]
    raise TimeoutError("still running")


async def test_messages_held_during_a_turn_are_answered_together(env):
    env.model.queue(RENDER, {"text": "rendered"}, {"text": "both answered", "match": "and green"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render x", wait=False)
    await running(env, tid)
    a = await env.send(tid, "make it blue", wait=False, client_id="c-a")
    b = await env.send(tid, "and green", wait=False)
    assert a["queued"]["text"] == "make it blue" and b["queued"]["position"] == 1
    assert [p["text"] for p in env.payloads(tid, "user")] == ["render x"]          # nothing in the log yet
    assert [i["text"] for i in (await env.client.get(f"/v1/threads/{tid}/queue")).json()["items"]] == ["make it blue", "and green"]
    assert await drained(env, tid) == "idle"
    users = env.payloads(tid, "user")
    assert [u["text"] for u in users] == ["render x", "make it blue", "and green"] and users[1]["client_id"] == "c-a"
    assert not any(u.get("queued") for u in users)
    assert [p["text"] for p in env.payloads(tid, "assistant")] == ["rendered", "both answered"]
    last = [m for m in env.model.received[-1]["messages"] if m["role"] == "user"]
    assert [m["content"] for m in last[-2:]] == ["make it blue", "and green"]       # one model call read both
    assert len(env.model.received) == 3 and env.agent.queue.state(tid) == {"items": [], "paused": None}


async def test_edit_move_remove_and_clear(env):
    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "x", "seconds": 1.5}}]}, {"text": "done"},
                    {"text": "after"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render", wait=False)
    await running(env, tid)
    ids = [(await env.send(tid, t, wait=False))["queued"]["id"] for t in ("one", "two", "three")]
    q = f"/v1/threads/{tid}/queue"
    r = await env.client.patch(f"{q}/{ids[0]}", json={"text": "one, edited"})
    assert r.status_code == 200 and r.json()["text"] == "one, edited" and r.json()["edited"]
    assert (await env.client.patch(f"{q}/{ids[0]}", json={"text": "  "})).status_code == 422
    await env.client.patch(f"{q}/{ids[2]}", json={"index": 0})
    assert [i["text"] for i in (await env.client.get(q)).json()["items"]] == ["three", "one, edited", "two"]
    r = await env.client.delete(f"{q}/{ids[1]}")
    assert [i["text"] for i in r.json()["items"]] == ["three", "one, edited"]
    assert (await env.client.delete(f"{q}/{ids[1]}")).status_code == 404
    assert (await env.client.delete(q)).json() == {"items": [], "paused": None}
    assert await drained(env, tid) == "idle" and [p["text"] for p in env.payloads(tid, "user")] == ["render"]


async def test_send_now_goes_into_the_running_turn(env):
    env.model.queue(RENDER, {"text": "rendered blue", "match": "make it blue"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render x", wait=False)
    await running(env, tid)
    qid = (await env.send(tid, "make it blue", wait=False))["queued"]["id"]
    r = await env.client.post(f"/v1/threads/{tid}/queue/{qid}/send")
    assert r.status_code == 202 and r.json()["payload"]["steer"] is True
    assert await drained(env, tid) == "idle"
    assert len(env.model.received) == 2 and env.payloads(tid, "assistant")[-1]["text"] == "rendered blue"


async def test_stop_sends_the_queue_and_stop_alone_only_stops(env):
    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "x", "seconds": 30}}]},
                    {"text": "on to the next", "match": "never mind"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render slowly", wait=False)
    await running(env, tid)
    await env.send(tid, "never mind, do this instead", wait=False)
    assert (await env.client.post(f"/v1/threads/{tid}/cancel")).status_code == 200
    assert await drained(env, tid) == "idle"
    assert env.payloads(tid, "user")[-1]["text"] == "never mind, do this instead"
    assert env.payloads(tid, "assistant")[-1]["text"] == "on to the next"
    n = len(env.model.received)
    env.model.queue({"text": "slow", "delay": 1.0})
    other = await env.thread()
    await env.send(other, "hi", wait=False)
    await asyncio.sleep(0.2)
    await env.client.post(f"/v1/threads/{other}/cancel")
    assert await drained(env, other) == "idle" and len(env.model.received) <= n + 1


async def test_an_error_pauses_the_queue_and_resume_sends_it(env):
    env.model.queue(RENDER)
    tid = await env.thread(mode="auto")
    await env.send(tid, "render x", wait=False)
    await running(env, tid)
    await env.send(tid, "then this", wait=False)
    env.model.down.update({"main", "backup"})
    assert await drained(env, tid) == "error"
    st = (await env.client.get(f"/v1/threads/{tid}/queue")).json()
    assert st["paused"] == "error" and [i["text"] for i in st["items"]] == ["then this"]
    env.model.down.clear()
    env.model.queue({"text": "back again"})
    r = await env.client.post(f"/v1/threads/{tid}/queue/resume")
    assert r.status_code == 202 and r.json() == {"items": [], "paused": None}
    assert await drained(env, tid) == "idle" and env.payloads(tid, "assistant")[-1]["text"] == "back again"


async def test_a_waiting_card_holds_the_queue_until_its_turn_ends(env):
    q = {"questions": [{"question": "Which style?", "header": "Style", "options": [{"label": "Photo"}, {"label": "Ink"}]}]}
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": q}], "delay": 0.5}, {"text": "Photo it is."},
                    {"text": "and the held one", "match": "also a cat"})
    tid = await env.thread()
    await env.send(tid, "make me a picture", wait=False)
    await asyncio.sleep(0.2)
    await env.send(tid, "also a cat", wait=False)
    assert await drained(env, tid) == "waiting"
    assert [i["text"] for i in env.agent.queue.items(tid)] == ["also a cat"]
    qid = env.payloads(tid, "question")[-1]["id"]
    await env.client.post(f"/v1/threads/{tid}/answer", json={"question_id": qid, "answers": {"Which style?": "Photo"}})
    assert await drained(env, tid) == "idle"
    assert [p["text"] for p in env.payloads(tid, "assistant")] == ["Photo it is.", "and the held one"]


async def test_the_queue_survives_a_restart_and_a_delete_clears_it(env, tmp_path):
    tid = await env.thread()
    env.agent.queue.add(tid, {"text": "kept", "client_id": "c-1", "attachments": []})
    again = Queue(Store(tmp_path / "agent.db"))
    assert [(i["text"], i["client_id"]) for i in again.items(tid)] == [("kept", "c-1")] and "attachments" not in again.items(tid)[0]
    await env.client.delete(f"/v1/threads/{tid}")
    assert not again.has(tid)


async def test_ready_carries_the_queue(env):
    tid = await env.thread()
    env.agent.queue.add(tid, {"text": "held"})
    env.agent.queue.pause(tid, "error")
    r = ready(env.agent, tid, 4)
    assert (r["type"], r["seq"], r["running"]) == ("ready", 4, False)
    assert r["queue"]["paused"] == "error" and [i["text"] for i in r["queue"]["items"]] == ["held"]
