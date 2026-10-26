"""structured-memory 2.3: memory_search by an old name, by meaning, and without the embed mod."""

from __future__ import annotations

import json

from agent.memory.search import search


async def seed(env):
    m = env.agent.memory
    g = m.create_entity("project", "AIHub")
    a = m.create_entity("topic", "agent", parent=g["id"])
    f1 = m.add_fact("Mods use ports 5100-5199", about=[g["id"]])
    f2 = m.add_fact("The chat agent runs its own loop", about=[a["id"]])
    f3 = m.add_fact("Prefers 16:9 images", kind="preference")
    old = m.add_fact("The hub used port 8000", about=[g["id"]])
    m.add_fact("The hub uses port 7000", about=[g["id"]], replaces=old["id"])
    m.update_entity(g["id"], name="GAIFA")
    await env.agent.memory_index.flush()
    return g, f1, f2, f3, old


async def test_an_old_name_finds_the_project_and_its_facts(env):
    g, f1, f2, f3, old = await seed(env)
    r = await search(env.agent.memory, env.agent.hub, "what do I know about AIHub?")
    ids = [f["id"] for f in r["facts"]]
    assert f1["id"] in ids and f2["id"] in ids and old["id"] not in ids and f3["id"] not in ids
    assert r["entities"][0]["path"] == "projects/GAIFA" and r["entities"][0]["aliases"] == ["AIHub"]
    assert next(f for f in r["facts"] if f["id"] == f1["id"])["about"] == ["projects/GAIFA"]
    h = await search(env.agent.memory, env.agent.hub, "AIHub port", history=True)
    assert any(f["id"] == old["id"] and f["current"] is False and f["replaced_by"] for f in h["facts"])


async def test_meaning_only_and_without_embed(env):
    g, f1, f2, f3, old = await seed(env)
    env.hub.synonyms = [("widescreen", "16"), ("pictures", "images")]
    r = await search(env.agent.memory, env.agent.hub, "widescreen pictures")
    assert r["facts"][0]["id"] == f3["id"] and r["meaning"]
    env.hub.embed_down = True
    r = await search(env.agent.memory, env.agent.hub, "loop")                          # keywords still answer
    assert [f["id"] for f in r["facts"]] == [f2["id"]] and r["meaning"] is False
    only = await search(env.agent.memory, env.agent.hub, "port", entity="projects/GAIFA/agent")
    assert only["facts"] == []


async def test_the_tool(env):
    await seed(env)
    env.model.queue({"tool_calls": [{"name": "memory_search", "arguments": {"query": "AIHub ports"}},
                                    {"name": "memory_search", "arguments": {"query": "zebra"}}]}, {"text": "found"})
    tid = await env.thread()
    await env.send(tid, "what ports do my mods use?")
    a, b = (json.loads(r["content"]) for r in env.payloads(tid, "tool_result"))
    assert a["facts"][0]["text"] == "Mods use ports 5100-5199"
    assert b["facts"] == [] and "nothing in memory matches" in b["note"]
    assert env.agent.memory.need_fact(a["facts"][0]["id"])["last_used"] is not None
