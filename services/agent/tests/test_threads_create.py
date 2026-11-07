"""chat-responsive 1.2: a new thread and its first message in one call."""

from __future__ import annotations


async def test_create_with_a_message_starts_the_turn(env):
    env.model.queue({"text": "hello there"})
    r = await env.client.post("/v1/threads", json={"mode": "auto", "message": {"text": "hi", "client_id": "c-9"}})
    assert r.status_code == 201, r.text
    th = r.json()
    assert th["mode"] == "auto" and th["event"]["type"] == "user" and th["event"]["payload"]["client_id"] == "c-9"
    assert await env.settle(th["id"]) == "idle"
    assert [p["text"] for p in env.payloads(th["id"], "assistant")] == ["hello there"]


async def test_create_without_a_message_is_as_before(env):
    r = await env.client.post("/v1/threads", json={})
    assert r.status_code == 201 and "event" not in r.json() and not env.events(r.json()["id"], "user")


async def test_a_bad_first_message_or_model_makes_no_thread(env):
    before = len((await env.client.get("/v1/threads")).json())
    r = await env.client.post("/v1/threads", json={"message": {"text": "  "}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "empty_message"
    r = await env.client.post("/v1/threads", json={"message": {"text": "x", "quotes": [{"text": "a", "reply": "b", "seq": 3}]}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_quote"
    r = await env.client.post("/v1/threads", json={"model": "nope", "message": {"text": "hi"}})
    assert r.status_code == 400 and "nope" in r.text
    assert len((await env.client.get("/v1/threads")).json()) == before


async def test_a_known_model_is_checked_without_asking_the_relay_again(env):
    await env.client.post("/v1/threads", json={"model": "main"})       # fills the list
    env.agent.llm._models = calls = (1.0, env.agent.llm._models[1])    # an old list: before, a check fetched it again
    r = await env.client.post("/v1/threads", json={"model": "backup"})
    assert r.status_code == 201 and env.agent.llm._models is calls
