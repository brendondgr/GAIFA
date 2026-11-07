"""14.4: the loop and threads: a plain reply, a multi-step turn, the step cap, a pause answered
after killing and restarting the agent process, a queued message, cancel, fork, replay."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .conftest import free_port

ROOT = Path(__file__).resolve().parents[1]


async def test_plain_reply_streams_and_records_usage(env):
    env.model.queue({"text": "Hello there.", "thinking": "The user greets me.", "usage": {"prompt_tokens": 321, "completion_tokens": 9}})
    tid = await env.thread()
    await env.send(tid, "hi")
    assert env.types(tid) == ["user", "thinking", "assistant"]
    assert env.payloads(tid, "assistant")[0]["text"] == "Hello there."
    assert env.payloads(tid, "thinking")[0]["text"] == "The user greets me."
    u = env.payloads(tid, "usage")[0]
    assert u["prompt_tokens"] == 321 and u["window"] == 8000 and u["model"] == "main"
    req = env.model.received[0]
    assert "max_tokens" not in req and "max_completion_tokens" not in req and req["stream"] is True
    assert req["messages"][0]["role"] == "system" and req["messages"][-1] == {"role": "user", "content": "hi"}
    assert env.agent.store.thread(tid)["state"] == "idle"
    assert env.agent.store.thread(tid)["title"] in ("hi", "Test title")
    for _ in range(50):
        if env.agent.store.thread(tid)["title"] == "Test title":
            break
        await asyncio.sleep(0.02)
    assert env.agent.store.thread(tid)["title"] == "Test title"


async def test_thinking_is_never_sent_back(env):
    env.model.queue({"text": "A.", "thinking": "SECRET-THOUGHT", "field": "reasoning_content"}, {"text": "B."})
    tid = await env.thread()
    await env.send(tid, "one")
    await env.send(tid, "two")
    assert env.payloads(tid, "thinking")[0]["text"] == "SECRET-THOUGHT"
    assert "SECRET-THOUGHT" not in json.dumps(env.model.received[-1]["messages"])


async def test_multi_step_turn(env):
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "a"}}]},
                    {"tool_calls": [{"name": "hub_list_services", "arguments": {}}]},
                    {"text": "Done: a is fine and fake is ready."})
    tid = await env.thread()
    await env.send(tid, "check a")
    assert env.types(tid) == ["user", "tool_call", "call", "tool_result", "tool_call", "call", "tool_result", "assistant"] or \
        env.types(tid) == ["user", "tool_call", "tool_result", "tool_call", "tool_result", "assistant"]
    # fake_get was deferred: it was loaded automatically and kept loaded
    assert "fake_get" in env.agent.store.thread(tid)["settings"]["loaded"]
    last = env.model.received[-1]["messages"]
    assert [m["role"] for m in last[1:]] == ["user", "assistant", "tool", "assistant", "tool"]
    assert json.loads(last[2]["tool_calls"][0]["function"]["arguments"]) == {"id": "a"}


async def test_step_cap_says_so(env):
    env.agent.cfg.max_steps = 3
    env.model.queue(*[{"tool_calls": [{"name": "hub_list_services", "arguments": {}}]} for _ in range(5)])
    tid = await env.thread()
    await env.send(tid, "loop forever")
    text = env.payloads(tid, "assistant")[-1]["text"]
    assert "step limit (3 steps)" in text
    assert len(env.events(tid, "tool_call")) == 3


async def test_queued_message_is_read_after_the_current_tool_calls(env):
    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "x", "seconds": 0.8}}]},
                    {"text": "Rendered, and noted your extra request.", "match": "also make it blue"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render x", wait=False)
    await asyncio.sleep(0.3)
    r = await env.send(tid, "also make it blue", wait=False, when="now")      # steered (chat-responsive 2.1)
    assert r["payload"].get("queued") is True
    await env.settle(tid)
    msgs = env.model.received[-1]["messages"]
    roles = [m["role"] for m in msgs[1:]]
    assert roles == ["user", "assistant", "tool", "user"], roles     # the tool result stays right after its call
    assert msgs[-1]["content"] == "also make it blue"
    assert env.payloads(tid, "assistant")[-1]["text"].startswith("Rendered")


async def test_cancel_stops_the_tool_call_at_the_hub(env):
    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "slow", "seconds": 30}}]})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render slowly", wait=False)
    for _ in range(100):
        if env.events(tid, "call"):
            break
        await asyncio.sleep(0.05)
    r = await env.client.post(f"/v1/threads/{tid}/cancel")
    assert r.status_code == 200
    assert env.agent.store.thread(tid)["state"] == "idle"
    res = env.payloads(tid, "tool_result")[-1]
    assert res["status"] == "cancelled"
    assert env.hub.cancelled, "the hub's call was cancelled"
    assert env.payloads(tid, "note")[-1]["text"] == "stopped by the user"


async def test_cancel_stops_an_approved_call_at_the_hub(env):
    """A call that went through a card has its call_id on the decision, not a `call` event: Stop
    left ComfyUI working on an approved edit for half an hour."""
    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "slow", "seconds": 30}}]})
    tid = await env.thread(mode="ask")
    await env.send(tid, "render slowly")
    ap = env.payloads(tid, "approval")[-1]
    await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True}, timeout=5)
    for _ in range(100):
        if env.agent.store.thread(tid)["state"] == "running" and env.hub.calls:
            break
        await asyncio.sleep(0.05)
    r = await env.client.post(f"/v1/threads/{tid}/cancel")
    assert r.status_code == 200
    assert env.payloads(tid, "tool_result")[-1]["status"] == "cancelled"
    assert env.hub.cancelled, "the approved call was cancelled at the hub"


async def test_cancel_during_the_model_stream(env):
    env.model.queue({"text": "x" * 4000, "chunk": 4, "gap": 0.01})
    tid = await env.thread()
    await env.send(tid, "long answer", wait=False)
    await asyncio.sleep(0.3)
    await env.client.post(f"/v1/threads/{tid}/cancel")
    assert env.agent.store.thread(tid)["state"] == "idle"
    assert not env.events(tid, "assistant")


async def test_fork_copies_up_to_a_seq_and_leaves_the_original(env):
    env.model.queue({"text": "first answer"}, {"text": "second answer"}, {"text": "branch answer"})
    tid = await env.thread()
    await env.send(tid, "first")
    await env.send(tid, "second")
    first_reply = env.events(tid, "assistant")[0]["seq"]
    before = env.agent.store.events(tid)
    r = await env.client.post(f"/v1/threads/{tid}/fork", json={"seq": first_reply})
    new = r.json()
    assert r.status_code == 201 and new["parent_id"] == tid and new["fork_seq"] == first_reply
    assert [e["type"] for e in env.agent.store.events(new["id"]) if e["type"] in ("user", "assistant")] == ["user", "assistant"]
    await env.send(new["id"], "another way")
    assert env.agent.store.events(tid) == before     # the original is unchanged
    assert env.payloads(new["id"], "assistant")[-1]["text"] == "branch answer"
    msgs = env.model.received[-1]["messages"]
    assert "second" not in json.dumps(msgs)


async def test_replay_after_a_seq(env):
    tid = await env.thread()
    await env.send(tid, "a")
    await env.send(tid, "b")
    evs = (await env.client.get(f"/v1/threads/{tid}/events?after=3")).json()
    assert evs and all(e["seq"] > 3 for e in evs)
    assert [e["seq"] for e in evs] == list(range(4, 4 + len(evs)))


async def test_model_down_uses_the_fallback(env):
    env.model.down.add("main")
    tid = await env.thread()
    await env.send(tid, "hello?")
    notes = env.payloads(tid, "note")
    assert notes and "continuing on backup" in notes[0]["text"]
    assert env.payloads(tid, "assistant")[-1]["model"] == "backup"
    env.model.down.add("backup")
    await env.send(tid, "and now?")
    err = env.payloads(tid, "error")[-1]
    assert err["code"] == "agent_error" and "down" in err["detail"]
    assert env.agent.store.thread(tid)["state"] == "error"


async def test_two_threads_dont_mix(env):
    env.model.queue({"text": "for A", "match": "question A", "delay": 0.3}, {"text": "for B", "match": "question B"})
    a, b = await env.thread(), await env.thread()
    await asyncio.gather(env.send(a, "question A"), env.send(b, "question B"))
    assert env.payloads(a, "assistant")[-1]["text"] == "for A"
    assert env.payloads(b, "assistant")[-1]["text"] == "for B"


async def test_delete_and_archive(env):
    a, b = await env.thread(title="keep"), await env.thread(title="old")
    await env.client.patch(f"/v1/threads/{b}", json={"archived": True})
    ids = [t["id"] for t in (await env.client.get("/v1/threads")).json()]
    assert a in ids and b not in ids
    assert (await env.client.delete(f"/v1/threads/{a}")).status_code == 200
    assert (await env.client.get(f"/v1/threads/{a}")).status_code == 404
    assert env.agent.store.events(a) == []


async def test_pause_survives_killing_the_agent_process(env, tmp_path):
    """A question waits on disk: kill -9 the agent, start it again, answer, and the turn goes on."""
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": {"questions": [
        {"question": "Which animal?", "header": "Animal", "options": [{"label": "Fox"}, {"label": "Owl"}]}]}}]},
        {"text": "A fox it is.", "match": "Fox"})
    port = free_port()
    envv = {**os.environ, "GAIFA_PORT": str(port), "AGENT_DB": str(tmp_path / "proc.db"), "AGENT_DATA": str(tmp_path / "data"),
            "AGENT_LLM_URL": env.llm_url, "GAIFA_URL": env.hub_url, "AGENT_MODEL": "main", "AGENT_FALLBACK_MODEL": ""}

    def start() -> subprocess.Popen:
        p = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "agent"], cwd=ROOT, env=envv,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return p

    async def ready(c: httpx.AsyncClient) -> None:
        for _ in range(200):
            try:
                if (await c.get("/health")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
        raise TimeoutError("agent didn't start")

    async def wait_state(c: httpx.AsyncClient, tid: str, state: str) -> None:
        for _ in range(300):
            if (await c.get(f"/v1/threads/{tid}")).json()["state"] == state:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError(state)

    p = start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as c:
            await ready(c)
            tid = (await c.post("/v1/threads", json={})).json()["id"]
            await c.post(f"/v1/threads/{tid}/messages", json={"text": "make an animal"})
            await wait_state(c, tid, "waiting")
            p.send_signal(signal.SIGKILL)
            p.wait(5)
            p = start()
            await ready(c)
            assert (await c.get(f"/v1/threads/{tid}")).json()["state"] == "waiting"
            evs = (await c.get(f"/v1/threads/{tid}/events")).json()
            q = [e for e in evs if e["type"] == "question"][0]["payload"]
            r = await c.post(f"/v1/threads/{tid}/answer", json={"question_id": q["id"], "answers": {"Which animal?": "Fox"}})
            assert r.status_code == 202
            await wait_state(c, tid, "idle")
            evs = (await c.get(f"/v1/threads/{tid}/events")).json()
            assert [e["payload"]["text"] for e in evs if e["type"] == "assistant"][-1] == "A fox it is."
    finally:
        p.kill()
        p.wait(5)


async def test_status_and_widget(env):
    tid = await env.thread()
    await env.send(tid, "hello")
    st = (await env.client.get("/v1/status")).json()
    assert {s["label"]: s["value"] for s in st["stats"]}["Messages today"] == 1
    w = (await env.client.get("/v1/widgets/messages?range=7d")).json()
    assert len(w["t"]) == 7 and w["series"][0]["values"][-1] == 1
    assert len((await env.client.get("/v1/widgets/messages?range=30d")).json()["t"]) == 30


async def test_concurrent_requests_dont_trip_the_store(env):
    """Many requests at once (FastAPI runs the plain routes on worker threads, all sharing one
    SQLite connection): every answer is right."""
    import asyncio
    import random

    ids = [await env.thread(title=f"t{i}") for i in range(5)]
    for t in ids:
        env.agent.emit(t, "user", {"text": "x"})

    async def one():
        tid = random.choice(ids)
        kind = random.choice(["get", "events", "create"])
        if kind == "get":
            r = await env.client.get(f"/v1/threads/{tid}")
            return r.status_code == 200 and r.json()["id"] == tid
        if kind == "events":
            r = await env.client.get(f"/v1/threads/{tid}/events")
            return r.status_code == 200 and all(e["thread_id"] == tid for e in r.json())
        r = await env.client.post("/v1/threads", json={"title": "race"})
        return r.status_code == 201 and r.json()["title"] == "race"

    results = await asyncio.gather(*(one() for _ in range(300)))
    assert all(results), results.count(False)


async def test_an_empty_reply_is_asked_again_without_streaming(env):
    env.model.queue({"text": ""}, {"tool_calls": [{"name": "hub_list_services", "arguments": {}}]}, {"text": "Here you go."})
    tid = await env.thread()
    await env.send(tid, "hello")
    assert env.model.received[1]["stream"] is False       # the retry
    assert env.payloads(tid, "tool_call")[0]["name"] == "hub_list_services"
    assert env.payloads(tid, "assistant")[-1]["text"] == "Here you go."
    assert "empty" in env.payloads(tid, "note")[0]["text"]


async def test_eval_threads_never_write_memory(env):
    env.model.queue({"tool_calls": [{"name": "remember", "arguments": {"text": "test fact"}}]}, {"text": "ok"})
    tid = await env.thread(settings={"dry_run": True})
    await env.send(tid, "remember a test fact")
    assert not (env.agent.cfg.data / "memory").exists()
    assert env.payloads(tid, "memory")[0]["dry_run"] is True


async def test_a_graceful_restart_resumes_the_turn(env, tmp_path):
    """Stopping the app mid-turn (a restart) is not the user's Stop: the turn stays running, its hub
    call isn't cancelled, and the next start picks it up and finishes it."""
    from agent.server import create_app

    env.model.queue({"tool_calls": [{"name": "fake_render", "arguments": {"prompt": "slow", "seconds": 6}}]}, {"text": "Rendered."})
    tid = await env.thread(mode="auto")
    await env.send(tid, "render", wait=False)
    for _ in range(100):
        if env.events(tid, "call"):
            break
        await asyncio.sleep(0.05)
    env.agent.shutting_down = True
    t = env.agent.tasks[tid]
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    assert env.agent.store.thread(tid)["state"] == "running" and not env.hub.cancelled
    assert not env.payloads(tid, "note")
    app2 = create_app(env.agent.cfg, db=env.agent.store.path, hub_url=env.hub_url, llm_url=env.llm_url)
    async with app2.router.lifespan_context(app2):
        a2 = app2.state.agent
        for _ in range(400):
            if not a2.running(tid) and a2.store.thread(tid)["state"] == "idle":
                break
            await asyncio.sleep(0.05)
        texts = [e["payload"]["text"] for e in a2.store.events(tid) if e["type"] == "assistant"]
        assert texts[-1] == "Rendered." and a2.store.thread(tid)["state"] == "idle"
