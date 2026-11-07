"""memory-auto-learning 3.1–3.3: when each fact was said, the interest kind, old interests fading into "Earlier
interests" and retired by the nightly tidy (never a stated one), the past found by memory_search's history, and
the facts learned from one chat."""

from __future__ import annotations

import time

from agent.memory import profile, tidy
from agent.memory.search import search

DAY = 86400


def learned(m, text, kind="interest", said=None, about=None, thread="t_x"):
    f = m.add_fact(text, about=about, kind=kind, source="inferred", by="learner",
                   evidence=[{"thread": thread, "seq": 1, **({"ts": said} if said else {})}],
                   valid_from=time.strftime("%Y-%m-%d", time.localtime(said)) if said else None)
    return m.set_fact_state(f["id"], "active", by="learner", op="fact_auto")


async def test_the_profile_dates_facts_and_moves_old_interests_down(env):
    m, now = env.agent.memory, time.time()
    m.add_fact("The user prefers short answers.", kind="preference", valid_from="2026-03-02")
    learned(m, "The user is learning Rust.", said=now - 3 * DAY)
    learned(m, "The user is into Godot.", said=now - 200 * DAY)
    text, shown = profile.build(m)
    lines = text.split("\n")
    assert lines[1] == "- The user prefers short answers. (since 2026-03)"
    assert lines[2] == f"- The user is learning Rust. (since {time.strftime('%Y-%m', time.localtime(now - 3 * DAY))})"
    assert lines[3].startswith("- Earlier interests: is into Godot. (since ") and len(shown) == 3


async def test_a_replaced_interest_keeps_its_span(env):
    m, now = env.agent.memory, time.time()
    old = learned(m, "The user is into Blender.", said=now - 60 * DAY, about=["you", "tools/Blender"])
    new = m.add_fact("The user is into Unity.", about=["you", "tools/Unity"], kind="interest", replaces=old["id"],
                     valid_from=time.strftime("%Y-%m-%d"))
    o = m.fact_public(m.need_fact(old["id"]))
    assert not o["current"] and o["valid_until"] == new["valid_from"] and o["replaced_by"] == new["id"]
    text, _ = profile.build(m)
    assert "- The user is into Unity. (since" in text
    assert f"Earlier interests: is into Blender. ({o['valid_from'][:7]} – {new['valid_from'][:7]})" in text
    r = await search(m, None, "what tools was I using before?", history=True)
    assert "The user is into Blender." in [f["text"] for f in r["facts"]]
    r = await search(m, None, "what tools was I using before?")
    assert "The user is into Blender." not in [f["text"] for f in r["facts"]]       # history only


async def test_tidy_retires_old_learned_interests_never_stated_ones(env):
    m, now = env.agent.memory, time.time()
    stale = learned(m, "The user is into Godot.", said=now - 120 * DAY)
    fresh = learned(m, "The user is learning Rust.", said=now - 10 * DAY)
    used = learned(m, "The user is into chess.", said=now - 120 * DAY)
    m.touch([used["id"]])
    stated = m.add_fact("The user is into jazz.", kind="interest")
    with m.lock:
        m.c.execute("UPDATE mem_facts SET recorded = ? WHERE id = ?", (now - 400 * DAY, stated["id"]))
    assert tidy.old_interests(m, 90) == 1
    assert m.need_fact(stale["id"])["state"] == "retired"
    assert {m.need_fact(x["id"])["state"] for x in (fresh, used, stated)} == {"active"}
    entry = next(e for e in m.log(stale["id"], 10) if e["op"] == "fact_retired")
    assert entry["by"] == "tidy"
    m.undo(entry["id"])
    assert m.need_fact(stale["id"])["state"] == "active"
    out = await tidy.run(env.agent)
    assert out["interests"] == 1


async def test_interests_over_http_and_facts_learned_from_a_chat(env):
    m, c = env.agent.memory, env.client
    r = await c.post("/v1/memory/facts", json={"text": "The user is learning Rust.", "kind": "interest"})
    assert r.status_code == 201 and r.json()["kind"] == "interest"
    learned(m, "The user prefers tea.", kind="preference", thread="t_a_b")
    learned(m, "The user prefers coffee.", kind="preference", thread="t_aXb")             # "_" isn't a wildcard
    got = (await c.get("/v1/memory/facts", params={"thread": "t_a_b", "source": "inferred"})).json()
    assert [f["text"] for f in got] == ["The user prefers tea."]
    s = (await c.put("/v1/settings", json={"memory_settings": {"interest_days": 30}})).json()["memory_settings"]
    assert s["interest_days"] == 30


async def test_a_learned_interest_is_filed_under_the_user_too(env):
    import json
    m, ml = env.agent.memory, env.agent.memory_learner
    env.model.queue({"text": "noted"})
    tid = await env.thread()
    await env.send(tid, "These days I'm into Blender")
    env.model.queue({"text": json.dumps({"facts": [{"text": "The user is into Blender.", "about": ["tools/Blender"], "kind": "interest",
                                                   "quote": "I'm into Blender", "confidence": 0.9}]}), "match": "lasting facts"})
    await ml.learn(tid)
    [f] = m.facts(state="active")
    assert {e["path"] for e in f["entities"]} == {"you", "tools/Blender"} and f["valid_from"] == time.strftime("%Y-%m-%d")
    assert "- The user is into Blender. (since" in profile.build(m)[0]


def test_what_a_fact_says_ended():
    from agent.memory.learn import ends_of
    assert ends_of({"text": "The user is into Unity now, no longer Blender."}) == ["Blender"]
    assert ends_of({"text": "The user is into Unity.", "quote": "Unity now, not Blender anymore"}) == ["Blender"]
    assert ends_of({"text": "The user uses Neovim instead of VS Code", "ends": ["vscode"]}) == ["vscode", "VS"]
    assert ends_of({"text": "The user is no longer using it."}) == [] and ends_of({"text": "The user likes tea."}) == []


async def test_a_change_replaces_the_held_fact_without_asking_and_isnt_a_rename(env):
    import json
    m, ml = env.agent.memory, env.agent.memory_learner
    old = learned(m, "The user is into Blender for 3D modeling.", said=time.time() - 60 * DAY, about=["you", "tools/Blender"])
    env.model.queue({"text": "noted"})
    tid = await env.thread()
    await env.send(tid, "Update: I'm into Unity now, not Blender anymore.")
    env.model.queue({"text": json.dumps({"facts": [{"text": "The user is into Unity for 3D modeling.", "about": ["tools/Unity"], "kind": "interest",
                                                   "quote": "I'm into Unity now, not Blender anymore", "ends": ["Blender"], "confidence": 0.9}],
                                         "renames": [{"from": "Blender", "to": "Unity"}]}), "match": "lasting facts"})
    await ml.learn(tid)
    assert not any("You keep an assistant's memory. For each new fact" in r["messages"][0]["content"] for r in env.model.received)
    [new] = m.facts(state="active", current=True)
    assert new["text"] == "The user is into Unity for 3D modeling." and new["replaces"] == old["id"]
    o = m.fact_public(m.need_fact(old["id"]))
    assert o["state"] == "retired" and o["valid_until"] == new["valid_from"]
    assert m.facts(state="proposed") == [] and m.resolve("Blender")["name"] == "Blender"     # no rename proposed
