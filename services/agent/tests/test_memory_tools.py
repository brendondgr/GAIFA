"""structured-memory 3.2: remember and the agent's memory tools, through the hub's call path."""

from __future__ import annotations

import json


async def approve_all(env, tid):
    for _ in range(6):
        aps = [a for a in env.payloads(tid, "approval") if not any(d["approval_id"] == a["approval_id"] for d in env.payloads(tid, "decision"))]
        if not aps:
            return
        await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": aps[-1]["approval_id"], "approve": True})
        await env.settle(tid)


async def test_remember_about_a_project_then_rename_keeps_its_facts(env):
    env.model.queue({"tool_calls": [{"name": "remember", "arguments": {"text": "GAIFA's mods use ports 5100-5199", "about": ["projects/AIHub"]}}]},
                    {"tool_calls": [{"name": "load_tools", "arguments": {"names": ["agent_memory_entity"]}}]},
                    {"tool_calls": [{"name": "agent_memory_entity", "arguments": {"entity": "AIHub", "rename": "GAIFA"}}]},
                    {"text": "done"})
    tid = await env.thread()
    await env.send(tid, "remember the ports, and we renamed AIHub to GAIFA")
    await approve_all(env, tid)
    m = env.agent.memory
    g = m.resolve("GAIFA")
    assert g and g["kind"] == "project" and m.resolve("AIHub")["id"] == g["id"]
    assert [f["text"] for f in m.facts_of(g["id"])] == ["GAIFA's mods use ports 5100-5199"]
    assert env.payloads(tid, "memory")[0]["about"] == ["projects/AIHub"]


async def test_replaces_retires_the_old_fact_and_related_facts_are_offered(env):
    m = env.agent.memory
    old = m.add_fact("Prefers 16:9 images", kind="preference")
    env.model.queue({"tool_calls": [{"name": "remember", "arguments": {"text": "Prefers 4:3 images", "kind": "preference"}}]},
                    {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "I prefer 4:3 now")
    await approve_all(env, tid)
    res = env.payloads(tid, "tool_result")[-1]
    assert f"{old['id']}: Prefers 16:9 images" in res["content"] and "replaces=" in res["content"]
    new = next(f for f in m.facts(current=True) if f["text"] == "Prefers 4:3 images")
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"names": ["agent_memory_save"]}}]},
                    {"tool_calls": [{"name": "agent_memory_save", "arguments": {"text": "Prefers 4:3 images", "kind": "preference",
                                                                                "replaces": old["id"]}}]}, {"text": "fixed"})
    await env.send(tid, "and it replaces the old one")
    await approve_all(env, tid)
    o = m.fact_public(m.need_fact(old["id"]))
    assert o["state"] == "retired" and o["replaced_by"] == new["id"]
    assert [f["text"] for f in m.facts(current=True)] == ["Prefers 4:3 images"]


async def test_forget_and_plan_mode(env):
    m = env.agent.memory
    f = m.add_fact("Lives in Tallahassee")
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"names": ["agent_memory_forget"]}}]},
                    {"tool_calls": [{"name": "agent_memory_forget", "arguments": {"fact": f["id"]}}]}, {"text": "forgotten"})
    tid = await env.thread()
    await env.send(tid, "forget where I live")
    await approve_all(env, tid)
    assert m.fact_row(f["id"]) is None
    env.model.queue({"tool_calls": [{"name": "remember", "arguments": {"text": "Likes jazz"}}]}, {"text": "no"})
    tid2 = await env.thread(mode="plan")
    await env.send(tid2, "remember I like jazz")
    r = env.payloads(tid2, "tool_result")[-1]
    assert r["status"] in ("denied", "error") and not any(x["text"] == "Likes jazz" for x in m.facts())
