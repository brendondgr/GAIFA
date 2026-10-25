"""Plan 31.4: while the relay holds a model call in GAIFA's GPU queue, the turn says so.

The model call names its chat (X-GAIFA-Thread); the agent reads the hub's queue (`GET /api/gpu`) and sends
the transient `gpu_wait` `{text, eta_s, ahead}` until the call's turn comes, then an empty one."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent import gpuwait
from agent import llm as llm_mod
from agent.llm import GPU_WAIT, LLM, THREAD, GpuWait, LLMError

HOLDER = {"id": "gl_c", "service": "comfy", "name": "Images & Video", "label": "portrait", "class": "job", "thread": None}


def waiting_body(tid: str, eta: float | None = 360) -> dict:
    return {"queue": True, "holder": {"group": "comfy", "leases": [HOLDER]},
            "waiting": [{"id": "gl_r", "service": "lcpp", "name": "LLMs", "label": "gemma4-26B", "thread": tid,
                         "ahead": [{"id": "gl_c", "service": "comfy", "label": "portrait", "state": "held", "eta_s": eta}],
                         "eta_s": eta}],
            "recent": []}


def test_waiting_text():
    text, extra = gpuwait.waiting_text(waiting_body("t_1"), "t_1")
    assert text == "Waiting for the GPU: Images & Video portrait, about 6 min left"
    assert extra["eta_s"] == 360 and extra["ahead"][0]["service"] == "comfy"
    assert gpuwait.waiting_text(waiting_body("t_1", eta=40), "t_1")[0].endswith("about 40 s left")
    assert gpuwait.waiting_text(waiting_body("t_1", eta=None), "t_1")[0] == "Waiting for the GPU: Images & Video portrait"
    assert gpuwait.waiting_text(waiting_body("t_1"), "t_2") is None
    assert gpuwait.waiting_text({}, "t_1") is None


async def test_the_model_call_names_its_chat():
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-gaifa-thread"))
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                                                      "finish_reason": "stop"}], "usage": {}})

    llm = LLM("http://relay/v1")
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await llm.chat("m", [{"role": "user", "content": "x"}], stream=False)
    token = THREAD.set("t_0123456789ab")
    try:
        await llm.chat("m", [{"role": "user", "content": "x"}], stream=False)
    finally:
        THREAD.reset(token)
    await llm.close()
    assert seen == [None, "t_0123456789ab"]


async def test_watch_shows_then_clears():
    state = {"phase": "waiting"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["phase"] == "waiting":
            return httpx.Response(200, json=waiting_body("t_1"))
        return httpx.Response(200, json={"holder": {"group": "lcpp", "leases": [{"id": "gl_r", "thread": "t_1"}]}, "waiting": []})

    sent: list[dict] = []
    async with httpx.AsyncClient(base_url="http://hub", transport=httpx.MockTransport(handler)) as c:
        task = asyncio.create_task(gpuwait.watch(c, "t_1", sent.append, delay=0.01, every=0.02))
        await asyncio.sleep(0.1)
        assert sent and sent[0]["text"].startswith("Waiting for the GPU: Images & Video")
        state["phase"] = "held"
        await asyncio.wait_for(task, 2)              # its turn came: the watcher ends by itself
    assert sent[-1] == {} and len([s for s in sent if s.get("text")]) == 1


async def test_watch_keeps_the_calls_gpu_wait():
    state = {"phase": "waiting"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["phase"] == "waiting":
            return httpx.Response(200, json=waiting_body("t_1"))
        return httpx.Response(200, json={"holder": {"group": "lcpp", "leases": [{"id": "gl_r", "thread": "t_1"}]}, "waiting": []})

    waiting = GpuWait()
    async with httpx.AsyncClient(base_url="http://hub", transport=httpx.MockTransport(handler)) as c:
        task = asyncio.create_task(gpuwait.watch(c, "t_1", lambda p: None, delay=0.01, every=0.02, waiting=waiting))
        await asyncio.sleep(0.1)
        assert waiting.on
        state["phase"] = "held"
        await asyncio.wait_for(task, 2)
    assert not waiting.on


async def test_the_stall_limit_skips_the_gpu_wait(monkeypatch):
    """The model client's timeout counts silence from the model, not time spent waiting for the GPU slot."""
    monkeypatch.setattr(llm_mod, "CHECK_S", 0.02)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.6)
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                                                      "finish_reason": "stop"}], "usage": {}})

    llm = LLM("http://relay/v1", timeout=0.3)
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(LLMError, match="sent nothing for 0.3 s"):
            await llm.chat("m", [{"role": "user", "content": "x"}], stream=False)
        waiting = GpuWait()
        token = GPU_WAIT.set(waiting)
        try:
            waiting.set(True)                            # behind a job for the first 0.5 s, then generating
            asyncio.get_running_loop().call_later(0.5, waiting.set, False)
            r = await llm.chat("m", [{"role": "user", "content": "x"}], stream=False)
        finally:
            GPU_WAIT.reset(token)
        assert r.text == "hi"
    finally:
        await llm.close()


async def test_watch_gives_up_when_nothing_queues():
    async with httpx.AsyncClient(base_url="http://hub", transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"holder": None, "waiting": []}))) as c:
        sent: list[dict] = []
        await asyncio.wait_for(gpuwait.watch(c, "t_1", sent.append, delay=0.01, every=0.01, give_up=0.05), 2)
    assert sent == []


async def test_watch_survives_a_hub_that_does_not_answer():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(base_url="http://hub", transport=httpx.MockTransport(boom)) as c:
        await asyncio.wait_for(gpuwait.watch(c, "t_1", lambda p: None, delay=0.01, every=0.01, give_up=0.05), 2)


async def test_a_turn_shows_its_gpu_wait(env, monkeypatch):
    real = gpuwait.watch
    monkeypatch.setattr(gpuwait, "watch", lambda c, tid, send, **kw: real(c, tid, send, delay=0.05, every=0.05, give_up=3, **kw))
    tid = await env.thread()
    state = {"phase": "waiting"}

    def gpu() -> dict:
        if state["phase"] == "waiting":
            return waiting_body(tid)
        return {"holder": {"group": "lcpp", "leases": [{"id": "gl_r", "thread": tid}]}, "waiting": []}

    env.hub.app.add_api_route("/api/gpu", gpu, methods=["GET"])
    q = env.agent.live.subscribe(tid)
    env.model.queue({"text": "done", "delay": 0.8})
    await env.send(tid, "hello", wait=False)
    await asyncio.sleep(0.4)
    state["phase"] = "held"
    await env.settle(tid)
    waits = []
    while not q.empty():
        ev = q.get_nowait()
        if ev["type"] == "gpu_wait":
            waits.append(ev["payload"])
    assert waits[0]["text"] == "Waiting for the GPU: Images & Video portrait, about 6 min left"
    assert waits[-1] == {}
    assert json.dumps(waits[0]["ahead"])          # what's ahead goes along, for the UI
