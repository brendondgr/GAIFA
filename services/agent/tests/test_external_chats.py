"""Plan agent-workflows 4.1: GAIFA's chats for other agents (/mcp's agent_chat_*): start, wait, read, send, stop, list;
Bypass refused; the user's cards show as waiting_for_you; only chats started over /mcp (and their sub-agents) are
reachable; GAIFA's own chats don't get these tools."""

from __future__ import annotations

import json

H = {"X-GAIFA-Origin": json.dumps({"service": "mcp", "client": "claude-code"})}
OTHER = {"X-GAIFA-Origin": json.dumps({"service": "mcp", "client": "codex"})}


async def _start(env, headers=H, **body):
    r = await env.client.post("/v1/external/start", json={"prompt": "Say hello.", **body}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_start_wait_read_list(env):
    env.model.queue({"match": "Say hello", "text": "Hello from GAIFA.", "delay": 0.2})
    s = await _start(env, title="Greeting")
    assert s["chat"].startswith("t_") and s["link"] == f"#/chat/{s['chat']}" and "agent_chat_wait" in s["note"]
    assert s["state"] == "running"                                  # its turn started
    th = env.agent.store.thread(s["chat"])
    assert th["settings"]["external"]["client"] == "claude-code" and th["mode"] == "manual" and th["title"] == "Greeting"
    assert env.payloads(s["chat"], "user")[0]["by"] == "mcp"
    r = (await env.client.post("/v1/external/wait", json={"chat": s["chat"], "timeout": 10}, headers=H)).json()
    assert r["state"] == "idle" and not r["running"] and r["answer"] == "Hello from GAIFA."
    assert [m["role"] for m in r["messages"]] == ["user", "assistant"] and r["last_seq"] > 0
    later = (await env.client.post("/v1/external/read", json={"chat": s["chat"], "after": r["last_seq"]}, headers=H)).json()
    assert later["messages"] == []
    mine = (await env.client.post("/v1/external/list", json={}, headers=H)).json()["chats"]
    assert [c["chat"] for c in mine] == [s["chat"]]
    assert (await env.client.post("/v1/external/list", json={}, headers=OTHER)).json()["chats"] == []
    assert s["chat"] in [t["id"] for t in (await env.client.get("/v1/threads")).json()]      # in the user's list


async def test_send_and_stop(env):
    env.model.queue({"match": "Say hello", "text": "Hi."}, {"match": "And goodbye", "text": "Bye.", "delay": 0.2})
    s = await _start(env)
    await env.client.post("/v1/external/wait", json={"chat": s["chat"], "timeout": 10}, headers=H)
    r = await env.client.post("/v1/external/send", json={"chat": s["chat"], "text": "And goodbye."}, headers=H)
    assert r.status_code == 202 and r.json()["sent"] is True
    r = (await env.client.post("/v1/external/wait", json={"chat": s["chat"], "timeout": 10}, headers=H)).json()
    assert r["answer"] == "Bye."
    env.model.queue({"match": "Take your time", "text": "late", "delay": 5})
    await env.client.post("/v1/external/send", json={"chat": s["chat"], "text": "Take your time."}, headers=H)
    r = await env.client.post("/v1/external/stop", json={"chat": s["chat"]}, headers=H)
    assert r.status_code == 200 and r.json()["state"] == "idle"


async def test_refusals(env):
    r = await env.client.post("/v1/external/start", json={"prompt": "x", "mode": "bypass"}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bypass_refused"
    r = await env.client.post("/v1/external/start", json={"prompt": "x", "model": "nope"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unknown_model"
    own = await env.thread()                                       # the user's own chat stays theirs
    for path in ("read", "send", "wait", "stop"):
        body = {"chat": own, **({"text": "x"} if path == "send" else {})}
        assert (await env.client.post(f"/v1/external/{path}", json=body, headers=H)).status_code == 404, path


async def test_waiting_for_you_and_sub_agents(env):
    env.model.queue({"match": "Clean up", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}]})
    s = await _start(env, prompt="Clean up item a.")
    r = (await env.client.post("/v1/external/wait", json={"chat": s["chat"], "timeout": 10}, headers=H)).json()
    assert r["state"] == "waiting" and r["waiting_for_you"] == [{"kind": "approval", "tool": "fake_wipe", "risk": "destructive"}]
    assert "you can't" in r["note"]
    kid = (await env.agent.workflows.spawn(s["chat"], "look", "Looker"))["id"]
    await env.agent.workflows.wait(kid, timeout=10)
    r = (await env.client.post("/v1/external/read", json={"chat": kid}, headers=H)).json()      # its sub-agent: reachable
    assert r["chat"] == kid and r["answer"] == "ok"
    assert (await env.client.post("/v1/external/read", json={"chat": s["chat"]}, headers=H)).json()["sub_agents"][0]["label"] == "Looker"


async def test_gaifa_s_own_chats_don_t_get_these_tools(env):
    from agent.tools import ToolSet
    ts = ToolSet(env.agent.hub, {})
    assert ts.off({"name": "agent_chat_start", "mod": "agent"}) and not ts.off({"name": "agent_memory_save", "mod": "agent"})
