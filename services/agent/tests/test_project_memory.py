"""Plan projects 4.2: a project's memory is a `project` entity anchored to it; a rename keeps the old name as an alias;
its facts are in its own chats' profiles and recall and in no other chat's; the learner files a fact about the work
under it; deleting the project removes the anchor and keeps the entity."""

from __future__ import annotations

import json

from agent.memory import profile
from agent.projects.memory import entity_of, private

from .test_environments import system_prompt


async def _project(env, name="Glacier thesis"):
    return (await env.client.post("/v1/projects", json={"name": name, "description": "Chapters on glaciers"})).json()


async def test_the_entity_made_and_anchored_and_a_rename(env):
    m = env.agent.memory
    p = await _project(env)
    e = entity_of(m, p["id"])
    assert e and e["kind"] == "project" and e["name"] == "Glacier thesis"
    assert env.agent.projects.get(p["id"])["memory_entity"] == e["id"]
    assert {"kind": "project", "value": p["id"]} in [dict(a) for a in m.anchors(e["id"])]
    await env.client.patch(f"/v1/projects/{p['id']}", json={"name": "Ice thesis"})
    e2 = entity_of(m, p["id"])
    assert e2["id"] == e["id"] and e2["name"] == "Ice thesis" and "Glacier thesis" in m.aliases(e["id"])
    # an entry memory already had by that name is adopted
    old = m.create_entity("project", "Garden", by="user")
    q = await _project(env, "Garden")
    assert entity_of(m, q["id"])["id"] == old["id"]
    r = (await env.client.get(f"/v1/projects/{q['id']}/memory")).json()
    assert r["entity"]["id"] == old["id"] and r["facts"] == []


async def test_facts_kept_to_the_projects_chats(env):
    m = env.agent.memory
    p = await _project(env)
    e = entity_of(m, p["id"])
    f = m.add_fact("The thesis draft is due on December 1.", about=[e["id"]], kind="fact", source="stated", by="user")
    other = m.create_entity("project", "Lumen", by="user")
    m.add_fact("Lumen is a reading app.", about=[other["id"]], kind="fact", source="stated", by="user")
    assert private(m) == {e["id"]} and private(m, p["id"]) == set()
    # in the project's chat: its facts lead the profile
    text, shown = profile.build(m, None, project=p["id"])
    assert text.startswith("This chat is in the project Glacier thesis") and "due on December 1" in text and f["id"] in shown
    assert "Lumen" in text.split("Projects:")[1]                                 # ordinary project entries still listed
    # in another chat: not on the Projects line, not in recall
    text2, shown2 = profile.build(m, None)
    assert "Glacier thesis" not in text2 and "December 1" not in text2 and "Lumen" in text2
    got = await profile.recall(m, env.agent.hub, "when is the thesis draft due?", shown2)
    assert all("December" not in r["text"] for r in got)
    got_p = await profile.recall(m, env.agent.hub, "when is the thesis draft due?", set(), project=p["id"])
    assert any("December" in r["text"] for r in got_p)
    # and through a real turn
    tid = (await env.client.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    await env.send(tid, "hello")
    assert "due on December 1" in system_prompt(env)
    plain = await env.thread()
    await env.send(plain, "hello")
    assert "December 1" not in system_prompt(env)
    r = (await env.client.get(f"/v1/projects/{p['id']}/memory")).json()
    assert [x["text"] for x in r["facts"]] == ["The thesis draft is due on December 1."] and r["entity"]["path"]


async def test_the_learner_files_work_under_the_project(env):
    m = env.agent.memory
    p = await _project(env)
    path = m.path(entity_of(m, p["id"]))
    tid = (await env.client.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    env.model.queue({"text": "Noted."})
    await env.send(tid, "Our deadline is Dec 1.")
    seen = {}

    async def ask(model, prompt):
        seen["prompt"] = prompt
        return {"facts": [{"text": "The thesis deadline is December 1.", "about": [path], "kind": "fact",
                           "quote": "Our deadline is Dec 1", "confidence": 0.95, "sensitive": False, "ends": []}], "renames": []}
    learner = env.agent.memory_learner
    learner.ask = ask
    n = await learner.learn(tid)
    assert n == 1 and f"This chat is in the project Glacier thesis: facts about its work go about \"{path}\"" in seen["prompt"]
    facts = (await env.client.get(f"/v1/projects/{p['id']}/memory")).json()["facts"]
    assert [x["text"] for x in facts] == ["The thesis deadline is December 1."]
    plain = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(plain, "Our deadline is Dec 1.")
    await learner.learn(plain)
    assert "This chat is in the project" not in seen["prompt"]


async def test_delete_removes_the_anchor_and_keeps_the_entity(env):
    m = env.agent.memory
    p = await _project(env)
    e = entity_of(m, p["id"])
    m.add_fact("The thesis draft is due on December 1.", about=[e["id"]], kind="fact", source="stated", by="user")
    done = (await env.client.delete(f"/v1/projects/{p['id']}")).json()
    assert done["memory"] == e["id"]
    assert m.entity_row(e["id"])["state"] == "active" and not [a for a in m.anchors(e["id"]) if a["kind"] == "project"]
    assert len(m.facts_of(e["id"])) == 1 and private(m) == set()
    text, _ = profile.build(m, None)
    assert "Glacier thesis" in text                                          # an ordinary project entry again
    assert json.dumps(done)
