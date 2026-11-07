"""memory-auto-learning 2.1–2.2: learned facts saved without asking when grounded, confident and not sensitive; the
rest wait with a reason; a repeat is saved at `auto_after_seen`; Undo makes an auto-approved fact a proposal again."""

from __future__ import annotations

import json

from agent.memory import auto

CFG = auto.settings({})
SAID = ["Quick note: I prefer short answers, and I'm learning Rust these days.", "my doctor says I should cut caffeine"]


def cand(text, quote, confidence=0.9, **kw):
    return {"text": text, "quote": quote, "confidence": confidence, **kw}


def test_each_rule():
    ok = cand("The user prefers short answers.", "I prefer short answers")
    assert auto.decide(ok, SAID, None, CFG) == (True, "")
    assert auto.decide(cand("The user prefers short answers.", "I PREFER   short answers!"), SAID, None, CFG)[0]
    assert auto.decide(cand("The user prefers long answers.", "I prefer long answers"), SAID, None, CFG) == (False, "not in your words")
    assert auto.decide(cand("The user prefers short answers.", ""), SAID, None, CFG) == (False, "not in your words")
    assert auto.decide({**ok, "confidence": 0.55}, SAID, None, CFG) == (False, "not sure: 0.55")
    assert auto.decide({**ok, "confidence": "high"}, SAID, None, CFG) == (False, "not sure")
    assert auto.decide(cand("The user should cut caffeine on their doctor's advice.", "my doctor says I should cut caffeine"),
                       SAID, None, CFG) == (False, "sensitive: health")
    assert auto.decide({**ok, "sensitive": True}, SAID, None, CFG) == (False, "sensitive")
    assert auto.decide(ok, SAID, {"source": "stated"}, CFG) == (False, "would change something you said")
    assert auto.decide(ok, SAID, {"source": "inferred"}, CFG) == (True, "")
    assert auto.decide({**ok, "text": "I prefer short answers."}, SAID, None, CFG) == (False, "worded as the user")
    assert auto.decide(ok, SAID, None, {**CFG, "auto_approve": False}) == (False, "auto-approval is off")
    assert auto.decide({**ok, "confidence": 0.7}, SAID, None, {**CFG, "auto_threshold": 0.65})[0]


def test_sensitive_words_are_words():
    s = lambda t: auto.sensitive(t, list(auto.CATEGORIES))   # noqa: E731
    assert s("The user lost $50 million in the tech sell-off") == "money"
    assert s("The user's son plays chess") == "relationships" and s("The user's partner is a nurse") == "relationships"
    assert s("The user is in therapy") == "health" and s("The user has a diagnosis of ADHD") == "health"
    assert s("The user wrote a song about parenting apps") is None                 # not "son", not "rent"
    assert s("The user prefers lightweight editors") is None and s("The user uses Blender") is None
    assert s("The user likes jazz") is None and s("The user is learning Rust") is None
    assert auto.sensitive("The user's son plays chess", ["health"]) is None        # only the categories asked for


def facts_reply(facts, renames=()):
    return {"text": json.dumps({"facts": list(facts), "renames": list(renames)}), "match": "lasting facts"}


async def chat(env, text):
    env.model.queue({"text": "noted"})
    tid = await env.thread()
    await env.send(tid, text)
    return tid


async def test_the_learner_saves_what_passes_and_proposes_the_rest(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    tid = await chat(env, "I'm writing my thesis on sparse solvers, and I prefer Python over Julia. My doctor says I should cut caffeine.")
    env.model.queue(facts_reply([
        {"text": "The user's thesis is on sparse solvers.", "about": ["projects/Thesis"], "quote": "I'm writing my thesis on sparse solvers",
         "confidence": 0.95, "sensitive": False},
        {"text": "The user prefers Python over Julia.", "about": ["you"], "kind": "preference", "quote": "I prefer Python over Julia",
         "confidence": 0.9, "sensitive": False},
        {"text": "The user should cut caffeine.", "about": ["you"], "quote": "My doctor says I should cut caffeine",
         "confidence": 0.9, "sensitive": True},
        {"text": "The user may like Haskell.", "about": ["you"], "quote": "I prefer Python", "confidence": 0.4}]))
    ml.last = {"proposed": 0, "auto": 0}
    assert await ml.learn(tid) == 4 and ml.last == {"proposed": 2, "auto": 2}
    active = {f["text"]: f for f in m.facts(state="active")}
    assert set(active) == {"The user's thesis is on sparse solvers.", "The user prefers Python over Julia."}
    assert m.resolve("Thesis")["state"] == "active"                               # the new entry came with it
    py = active["The user prefers Python over Julia."]
    assert py["confidence"] == 0.9 and py["evidence"][0]["quote"] == "I prefer Python over Julia" and py["source"] == "inferred"
    waiting = {f["text"]: f["evidence"][0]["why"] for f in m.facts(state="proposed")}
    assert waiting == {"The user should cut caffeine.": "sensitive: health", "The user may like Haskell.": "not sure: 0.40"}
    [entry] = [e for e in m.log(py["id"], 10) if e["op"] == "fact_auto"]
    assert entry["by"] == "learner" and entry["summary"].startswith("learned on its own:")
    m.undo(entry["id"])
    assert m.need_fact(py["id"])["state"] == "proposed"                           # Undo: back to a proposal
    thesis = active["The user's thesis is on sparse solvers."]
    [entry] = [e for e in m.log(thesis["id"], 10) if e["op"] == "fact_auto"]
    m.undo(entry["id"])
    assert m.need_fact(thesis["id"])["state"] == "proposed" and m.resolve("Thesis") is None


async def test_a_repeat_is_saved_once_seen_twice(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    p = m.add_fact("The user drinks green tea.", source="inferred", by="learner")
    await env.agent.memory_index.flush()
    tid = await chat(env, "green tea again for me")
    env.model.queue(facts_reply([{"text": "The user drinks green tea.", "about": ["you"], "quote": "green tea again", "confidence": 0.3}]),
                    {"text": json.dumps({"decisions": [{"n": 1, "op": "same", "id": p["id"]}]})})
    ml.last = {"proposed": 0, "auto": 0}
    await ml.learn(tid)
    f = m.need_fact(p["id"])
    assert f["seen"] == 2 and f["state"] == "active" and ml.last["auto"] == 1


async def test_switched_off_everything_waits(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    env.agent.cfg.data.mkdir(parents=True, exist_ok=True)
    (env.agent.cfg.data / "memory.json").write_text(json.dumps({"auto_approve": False}))
    tid = await chat(env, "I prefer short answers")
    env.model.queue(facts_reply([{"text": "The user prefers short answers.", "about": ["you"], "quote": "I prefer short answers",
                                  "confidence": 1}]))
    await ml.learn(tid)
    [f] = m.facts(state="proposed")
    assert f["evidence"][0]["why"] == "auto-approval is off" and m.facts(state="active") == []


async def test_replacing_a_stated_fact_waits(env):
    m, ml = env.agent.memory, env.agent.memory_learner
    old = m.add_fact("The user prefers 16:9 images.", kind="preference")            # stated
    await env.agent.memory_index.flush()
    tid = await chat(env, "I prefer 4:3 images now")
    env.model.queue(facts_reply([{"text": "The user prefers 4:3 images.", "about": ["you"], "kind": "preference",
                                  "quote": "I prefer 4:3 images now", "confidence": 0.95}]),
                    {"text": json.dumps({"decisions": [{"n": 1, "op": "replaces", "id": old["id"]}]})})
    await ml.learn(tid)
    [p] = m.facts(state="proposed")
    assert p["replaces"] == old["id"] and p["evidence"][0]["why"] == "would change something you said"
    assert m.fact_public(m.need_fact(old["id"]))["current"]


async def test_settings_hold_the_auto_approval_choices(env):
    c = env.client
    s = (await c.get("/v1/settings")).json()["memory_settings"]
    assert s["auto_approve"] is True and s["auto_threshold"] == 0.8 and s["auto_after_seen"] == 2 and "health" in s["always_review"]
    r = await c.put("/v1/settings", json={"memory_settings": {"auto_approve": False, "auto_threshold": 0.65, "always_review": ["health"]}})
    s = r.json()["memory_settings"]
    assert (s["auto_approve"], s["auto_threshold"], s["always_review"], s["recall"]) == (False, 0.65, ["health"], True)
    assert json.loads((env.agent.cfg.data / "memory.json").read_text())["auto_threshold"] == 0.65
    assert (await c.put("/v1/settings", json={"memory_settings": {"always_review": ["gossip"]}})).status_code == 422


async def test_learned_on_its_own_and_keep_over_http(env):
    m, c = env.agent.memory, env.client
    f = m.add_fact("The user prefers Python.", source="inferred", by="learner")
    m.set_fact_state(f["id"], "active", by="learner", op="fact_auto")
    g = m.add_fact("The user likes jazz.", source="inferred", by="learner")
    m.set_fact_state(g["id"], "active")                                            # approved by the user: not listed
    assert [x["id"] for x in (await c.get("/v1/memory/auto")).json()] == [f["id"]]
    (await c.post(f"/v1/memory/facts/{f['id']}/keep")).raise_for_status()
    assert (await c.get("/v1/memory/auto")).json() == []
    assert m.need_fact(f["id"])["state"] == "active"
