"""structured-memory 4.1: learning after a chat goes quiet: proposals with evidence, same/replaces/adds, renames,
a reply that isn't JSON retried once, and nothing from documents or tool results in the model's input."""

from __future__ import annotations

import json


def facts_reply(facts, renames=()):
    return {"text": "Here you go:\n```json\n" + json.dumps({"facts": list(facts), "renames": list(renames)}) + "\n```"}


async def chat(env, text, **kw):
    env.model.queue({"text": "noted"})
    tid = await env.thread()
    await env.send(tid, text, **kw)
    return tid


async def test_a_new_fact_and_entity_are_proposed_with_evidence(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    tid = await chat(env, "From now on I prefer 4:3 images. My thesis project is about memory systems.")
    env.model.queue(facts_reply([{"text": "Prefers 4:3 images", "about": ["you"], "kind": "preference"},
                                 {"text": "The thesis is about memory systems", "about": ["projects/Thesis"], "kind": "fact"}]))
    assert await ml.learn(tid) == 2
    prompt = env.model.received[-1]["messages"][0]["content"]
    assert "USER: From now on I prefer 4:3 images" in prompt and "Memory already holds:\n(nothing yet)" in prompt
    props = {f["text"]: f for f in m.facts(state="proposed")}
    assert set(props) == {"Prefers 4:3 images", "The thesis is about memory systems"}
    user_seq = env.payloads(tid, "user") and env.events(tid, "user")[-1]["seq"]
    assert props["Prefers 4:3 images"]["evidence"] == [{"thread": tid, "seq": user_seq}] and props["Prefers 4:3 images"]["source"] == "inferred"
    assert m.resolve("Thesis") is None and m.entities(state="proposed")[0]["name"] == "Thesis"
    assert m.facts(current=True) == []                                         # nothing a chat knows yet
    m.set_fact_state(props["The thesis is about memory systems"]["id"], "active")
    assert m.resolve("Thesis")["kind"] == "project"
    assert await ml.learn(tid) == 0                                            # nothing new since


async def test_same_and_replaces(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    old = m.add_fact("Prefers 16:9 images", kind="preference")
    seen = m.add_fact("Works late", kind="fact")
    await env.agent.memory_index.flush()
    tid = await chat(env, "I work late again, and I prefer 4:3 images now")
    env.model.queue(facts_reply([{"text": "Works late at night", "about": ["you"]}, {"text": "Prefers 4:3 images", "about": ["you"], "kind": "preference"}]),
                    {"text": json.dumps({"decisions": [{"n": 1, "op": "same", "id": seen["id"]}, {"n": 2, "op": "replaces", "id": old["id"]}]})})
    assert await ml.learn(tid) == 1
    assert m.need_fact(seen["id"])["seen"] == 2
    [p] = m.facts(state="proposed")
    assert p["text"] == "Prefers 4:3 images" and p["replaces"] == old["id"]
    assert m.fact_public(m.need_fact(old["id"]))["current"]                     # until it's approved
    m.set_fact_state(p["id"], "active")
    assert not m.fact_public(m.need_fact(old["id"]))["current"]


async def test_a_rename_is_proposed_and_applied_on_approval(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    g = m.create_entity("project", "AIHub")
    tid = await chat(env, "We renamed AIHub to GAIFA today")
    env.model.queue(facts_reply([], renames=[{"from": "AIHub", "to": "GAIFA"}]))
    assert await ml.learn(tid) == 1
    [p] = m.facts(state="proposed")
    assert p["text"] == "Renamed AIHub to GAIFA" and m.need(g["id"])["name"] == "AIHub"
    m.set_fact_state(p["id"], "active")
    assert m.need(g["id"])["name"] == "GAIFA" and m.resolve("AIHub")["id"] == g["id"]


async def test_no_json_is_tried_again_once(env):
    ml = env.agent.memory_learner
    tid = await chat(env, "I prefer tea")
    env.model.queue({"text": "Sure! The user likes tea."})
    assert await ml.learn(tid) is None and ml.state(tid)["upto_seq"] == 0 and ml.state(tid)["tries"] == 1
    env.model.queue({"text": "still not json"})
    assert await ml.learn(tid) is None and ml.state(tid)["upto_seq"] > 0       # given up: moves on


async def test_documents_and_tool_results_never_reach_the_model(env):
    ml = env.agent.memory_learner
    oid = env.hub.doc("notes.md", text="SECRET-DOC-TEXT: the user loves sardines\n", kind="text", subtype="md")
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"q": "x"}}]}, {"text": "done"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "read this", attachments=[oid])
    env.model.queue(facts_reply([]))
    assert await ml.learn(tid) == 0
    prompt = env.model.received[-1]["messages"][0]["content"]
    assert "SECRET-DOC-TEXT" not in prompt and "USER: read this" in prompt and "(document #1: notes.md" in prompt


async def test_eval_and_no_learn_chats_are_never_due(env):
    ml = env.agent.memory_learner
    ml.idle_s = 0
    a = await env.thread(settings={"dry_run": True})
    b = await env.thread(settings={"no_learn": True})
    c = await chat(env, "I prefer tea")
    for t in (a, b):
        env.model.queue({"text": "ok"})
        await env.send(t, "I prefer coffee")
    assert [t["id"] for t in ml.due()] == [c]


async def test_learning_starts_from_now_and_proposals_share_new_entries(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    old = await chat(env, "I prefer tea")                     # a chat from before learning was turned on
    with m.lock:
        m.c.execute("DELETE FROM mem_learned")
    assert ml.baseline() >= 1 and ml.state(old)["upto_seq"] > 0 and ml.baseline() == 0
    ml.idle_s = 0
    assert old not in [t["id"] for t in ml.due()]
    tid = await chat(env, "Mycelium is my search engine project; it targets ECIR 2027")
    env.model.queue(facts_reply([{"text": "Mycelium is a search engine project", "about": ["projects/Mycelium"]},
                                 {"text": "Mycelium targets ECIR 2027", "about": ["Mycelium"]}]))
    assert await ml.learn(tid) == 2
    assert len(m.entities(state="proposed")) == 1                # one Mycelium for both


def test_clean_about():
    from agent.memory.learn import clean_about
    assert [clean_about(x) for x in ("topics/user preference", "User", "the user's habits", "topics/Lumen project", "Lumen project",
                                     "projects/Lumen", "GAIFA", "Ana person", "topics/cooking")] == \
        ["you", "you", "you", "projects/Lumen", "projects/Lumen", "projects/Lumen", "GAIFA", "people/Ana", "topics/cooking"]
