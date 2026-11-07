"""memory-auto-learning 1.1–1.3: learned facts in the third person: the check, the learner's rewording, the prompt's
fields, and rewording the facts already saved (never a stated one)."""

from __future__ import annotations

import json

from agent.memory.wording import first_person

NOV5 = ["I work independently and hate qualifying exams.",
        "The qualifying exam is the only barrier to getting a PhD because I cannot pass it.",
        "I can easily do proposals, conference submissions, and have grants; my advisor is supportive.",
        "I love learning and building things, setting goals, and testing.",
        "If I don't pass the qualifying exam, I get kicked out of the PhD program."]


def test_first_person_is_caught():
    assert all(first_person(t) for t in NOV5)
    assert all(first_person(t) for t in ("We use uv for everything", "Our lab meets on Fridays", "It reminds me of home",
                                         "I'm learning Rust", "Something I've wanted"))
    assert not any(first_person(t) for t in (
        "The user said \"I can't\" about the exam", "The user said “my way or nothing”", "The user prefers 4:3 images",
        "The user's advisor is supportive", "Mycelium targets ECIR 2027", "Uses iOS and MIT licenses", "The user likes Imagen",
        "Prefers dark themes for IDEs"))


def facts_reply(facts):
    return {"text": json.dumps({"facts": facts, "renames": []}), "match": "lasting facts"}


async def chat(env, text):
    env.model.queue({"text": "noted"})
    tid = await env.thread()
    await env.send(tid, text)
    return tid


async def test_the_prompt_asks_for_the_third_person_a_quote_a_confidence_and_sensitivity(env):
    ml = env.agent.memory_learner
    tid = await chat(env, "I prefer short answers")
    env.model.queue(facts_reply([{"text": "The user prefers short answers", "about": ["you"], "kind": "preference",
                                  "quote": "I prefer short answers", "confidence": 0.95, "sensitive": False}]))
    assert await ml.learn(tid) == 1
    prompt = env.model.received[-1]["messages"][0]["content"]
    assert "third person" in prompt and '"quote"' in prompt and '"confidence"' in prompt and '"sensitive"' in prompt
    assert [f["text"] for f in env.agent.memory.facts(state="proposed")] == ["The user prefers short answers"]


async def test_the_learner_rewords_first_person_facts_once(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    tid = await chat(env, "I hate qualifying exams and my advisor is supportive. I like tea.")
    env.model.queue(facts_reply([{"text": "I hate qualifying exams.", "about": ["you"]},
                                 {"text": "My advisor is supportive.", "about": ["you"]},
                                 {"text": "The user likes tea.", "about": ["you"]}]),
                    {"text": json.dumps({"facts": ["The user dislikes qualifying exams.", "My advisor is supportive."]}),
                     "match": "third person"})
    assert await ml.learn(tid) == 3
    reword_prompt = env.model.received[-1]["messages"][0]["content"]
    assert "1. I hate qualifying exams." in reword_prompt and "The user likes tea" not in reword_prompt
    assert {f["text"] for f in m.facts(state="proposed")} == {"The user dislikes qualifying exams.", "My advisor is supportive.",
                                                              "The user likes tea."}


async def test_a_failed_reword_leaves_the_facts_as_they_were(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    tid = await chat(env, "I live in Lisbon")
    env.model.queue(facts_reply([{"text": "I live in Lisbon.", "about": ["you"]}]),
                    {"text": "not json", "match": "third person"})
    assert await ml.learn(tid) == 1
    assert [f["text"] for f in m.facts(state="proposed")] == ["I live in Lisbon."]


async def test_reword_saved_facts_over_http_never_a_stated_one(env):
    m, c = env.agent.memory, env.client
    learned = m.add_fact(NOV5[0], source="inferred", by="learner")
    active = m.add_fact("I love building things.", source="inferred", by="learner")
    m.set_fact_state(active["id"], "active")
    stated = m.add_fact("I prefer tea", source="stated")
    fine = m.add_fact("The user likes jazz", source="inferred", by="learner")
    env.model.queue({"text": json.dumps({"facts": ["The user works independently and dislikes qualifying exams.",
                                                   "The user loves building things."]}), "match": "third person"})
    r = (await c.post("/v1/memory/reword")).json()
    assert r == {"reworded": 2, "left": 0}
    assert m.need_fact(learned["id"])["text"] == "The user works independently and dislikes qualifying exams."
    assert m.need_fact(active["id"])["text"] == "The user loves building things."
    assert m.need_fact(stated["id"])["text"] == "I prefer tea" and m.need_fact(fine["id"])["text"] == "The user likes jazz"
    [entry] = [e for e in m.log(learned["id"], 10) if e["op"] == "fact_update"]
    assert entry["by"] == "learner"
    (await c.post(f"/v1/memory/undo/{entry['id']}")).raise_for_status()
    assert m.need_fact(learned["id"])["text"] == NOV5[0]
