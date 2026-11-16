"""capability-enablement 6.1: the agent on a direct OpenAI-compatible endpoint: a key sent as a bearer token, safe
defaults without the relay's facts, a chat turn through it, its status (`llm`) when it answers, wants a key or is down."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent.llm import LLM
from agent.loop import Config
from agent.server import create_app

from .conftest import serve
from .fakehub import FakeHub


def plain_server(key: str | None):
    """A plain OpenAI-compatible server: /v1/models without `relay` or `meta`, a chat answer, a key when given."""
    app, seen = FastAPI(), []

    def ok(request: Request) -> bool:
        return key is None or request.headers.get("authorization") == f"Bearer {key}"

    @app.get("/v1/models")
    def models(request: Request):
        if not ok(request):
            return JSONResponse({"error": "no key"}, status_code=401)
        return {"object": "list", "data": [{"id": "llama-3.3", "object": "model"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        seen.append({"auth": request.headers.get("authorization"), "body": await request.json()})
        if not ok(request):
            return JSONResponse({"error": "no key"}, status_code=401)
        return {"id": "x", "object": "chat.completion", "model": "llama-3.3",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi from llama."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    return app, seen


async def test_status_meta_and_the_key():
    app, seen = plain_server("sk-test")
    s, t, port = await serve(app)
    try:
        url = f"http://127.0.0.1:{port}/v1"
        llm = LLM(url, key="sk-test", direct_window=8192)
        st = await llm.status(max_age=0)
        assert st["url"] == url and st["kind"] == "direct" and st["answers"] is True and st["models"] == ["llama-3.3"]
        assert "a window of 8,192 tokens" in st["detail"]
        assert await llm.meta("llama-3.3") == {"context_length": 8192, "tools": True, "vision": False, "assumed": True}
        nokey = await LLM(url).status(max_age=0)
        assert nokey["answers"] is False and "AGENT_LLM_KEY" in nokey["detail"]
        await llm.close()
    finally:
        s.should_exit = True
        await asyncio.gather(t, return_exceptions=True)
    down = await LLM("http://127.0.0.1:9/v1").status(max_age=0)
    assert down["answers"] is False and down["detail"].startswith("nothing answers at http://127.0.0.1:9/v1")


async def test_a_chat_turn_through_it(tmp_path, monkeypatch):
    app, seen = plain_server("sk-test")
    ms, mt, mport = await serve(app)
    hub = FakeHub()
    hs, ht, hport = await serve(hub.app)
    monkeypatch.setenv("AGENT_LLM_KEY", "sk-test")
    cfg = Config(model="llama-3.3", max_steps=3, data=tmp_path / "data" / "agent", default_window=8192)
    agent = create_app(cfg, db=tmp_path / "agent.db", hub_url=f"http://127.0.0.1:{hport}", llm_url=f"http://127.0.0.1:{mport}/v1")
    hub.agent_app = agent
    try:
        async with agent.router.lifespan_context(agent):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent), base_url="http://agent", timeout=30) as c:
                st = (await c.get("/v1/status")).json()
                assert st["llm"]["kind"] == "direct" and st["llm"]["answers"] is True
                tid = (await c.post("/v1/threads", json={"model": "llama-3.3"})).json()["id"]
                await c.post(f"/v1/threads/{tid}/messages", json={"text": "hello"})
                for _ in range(100):
                    if (await c.get(f"/v1/threads/{tid}")).json().get("state") != "running":
                        break
                    await asyncio.sleep(0.05)
                evs = (await c.get(f"/v1/threads/{tid}/events")).json()
                assert any(e["type"] == "assistant" and "Hi from llama" in (e["payload"].get("text") or "") for e in evs)
                assert seen and all(x["auth"] == "Bearer sk-test" for x in seen)
                r = await c.post("/v1/threads", json={"model": "gpt-nope"})
                assert r.status_code == 400 and f"http://127.0.0.1:{mport}/v1 doesn't serve 'gpt-nope'" in r.text
    finally:
        for s in (ms, hs):
            s.should_exit = True
        await asyncio.gather(mt, ht, return_exceptions=True)
