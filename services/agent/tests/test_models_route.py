"""The agent's model list, grouped by server, and a chat's model checked against it (plan llm-servers 2.2)."""

from __future__ import annotations


async def test_models_grouped_with_their_server(env):
    env.model.groups.update(main="cloud", backup="remote")
    body = (await env.client.get("/v1/models")).json()
    ms = {m["id"]: m for m in body["models"]}
    assert [m["group"] for m in body["models"]] == ["local", "remote", "cloud"]       # this machine first
    assert ms["main"]["cloud"] is True and ms["blind"]["cloud"] is False
    assert ms["main"]["server"] == "main" and ms["main"]["provider"] == "openai" and ms["main"]["meta"]["context_length"] == 8000
    assert body["default"] and "fallback" in body


async def test_a_chats_model_must_be_served(env):
    tid = await env.thread()
    r = await env.client.patch(f"/v1/threads/{tid}", json={"model": "mian"})
    assert r.status_code == 400 and "did you mean main" in r.json()["detail"]
    r = await env.client.patch(f"/v1/threads/{tid}", json={"model": "backup"})
    assert r.status_code == 200 and r.json()["model"] == "backup"
    r = await env.client.post("/v1/threads", json={"model": "nope-at-all"})
    assert r.status_code == 400


async def test_relay_unreachable_accepts_any(env, monkeypatch):
    async def none(max_age=60):
        return []
    monkeypatch.setattr(env.agent.llm, "models", none)
    tid = await env.thread()
    assert (await env.client.patch(f"/v1/threads/{tid}", json={"model": "claude/claude-opus-5-5"})).status_code == 200


def test_an_id_listed_twice_is_one_model():
    from agent.server import model_list
    rel = {"endpoint": "smollm2-7071", "alias": "smollm2", "group": "local", "protocol": "openai"}
    assert [m["id"] for m in model_list([{"id": "smollm2", "relay": rel}, {"id": "smollm2", "relay": rel}, {"id": "skynet"}])] == ["smollm2", "skynet"]
