"""structured-memory 2.2: the embed mod's `memory` collection follows every change; proposed facts stay out;
marks wait while the embed mod is away; an empty collection is filled again."""

from __future__ import annotations


async def test_changes_reach_the_collection(env):
    m, idx, texts = env.agent.memory, env.agent.memory_index, env.hub.texts
    await idx.flush()
    g = m.create_entity("project", "AIHub", summary="the local AI hub")
    f = m.add_fact("Mods use ports 5100-5199", about=[g["id"]])
    p = m.add_fact("Likes pastel colors", source="inferred")
    await idx.flush()
    mem = texts["memory"]
    assert mem[f"fact:{f['id']}"] == {"text": "Mods use ports 5100-5199", "title": "projects/AIHub", "meta": {"kind": "fact"}}
    assert mem[f"entity:{g['id']}"]["text"] == "AIHub: the local AI hub" and f"fact:{p['id']}" not in mem
    m.update_entity(g["id"], name="GAIFA")
    await idx.flush()
    assert mem[f"entity:{g['id']}"] == {"text": "GAIFA (also AIHub): the local AI hub", "title": "projects/GAIFA", "meta": {"kind": "entity"}}
    assert mem[f"fact:{f['id']}"]["title"] == "projects/GAIFA"
    new = m.add_fact("Mods use ports 5100-5199 and 4000", about=[g["id"]], replaces=f["id"])
    await idx.flush()
    assert f"fact:{f['id']}" not in mem and f"fact:{new['id']}" in mem
    m.set_fact_state(p["id"], "active")
    await idx.flush()
    assert f"fact:{p['id']}" in mem
    m.forget(p["id"])
    await idx.flush()
    assert f"fact:{p['id']}" not in mem and not m.dirty


async def test_marks_wait_while_embed_is_away_and_an_empty_collection_fills(env):
    m, idx = env.agent.memory, env.agent.memory_index
    await idx.flush()
    env.hub.embed_down = True
    f = m.add_fact("Works late")
    try:
        await idx.flush()
    except Exception:  # noqa: BLE001
        pass
    assert f"fact:{f['id']}" in m.dirty
    env.hub.embed_down = False
    await idx.flush()
    assert f"fact:{f['id']}" in env.hub.texts["memory"]
    env.hub.texts.clear()
    await idx.fill_if_empty()
    await idx.flush()
    assert f"fact:{f['id']}" in env.hub.texts["memory"] and "entity:user" in env.hub.texts["memory"]
    r = await env.client.post("/v1/memory/reindex")
    assert r.status_code == 200 and r.json()["sent"] == len(env.hub.texts["memory"])
