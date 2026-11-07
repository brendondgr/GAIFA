"""structured-memory 3.3: the profile in the system prompt, a chat's projects by its folders, and recall on each
message, stored with it so the message never changes."""

from __future__ import annotations

import json

from agent.memory import profile

DEFAULT = {"id": "default", "name": "Default", "folders": [{"id": "gaifa", "path": "/home/u/Agents/GAIFA", "level": "read"}]}
NONE = {"id": "none", "name": "None", "folders": []}


def system(env) -> str:
    return env.model.received[-1]["messages"][0]["content"]


def recalled(env, tid) -> list:
    """What was recalled for the last user message (a `recall` event since chat-responsive 1.1)."""
    seq = env.events(tid, "user")[-1]["seq"]
    return next((p["memory"] for p in env.payloads(tid, "recall") if p["for"] == seq), [])


def last_user(env) -> str:
    return [m for m in env.model.received[-1]["messages"] if m["role"] == "user"][-1]["content"]


async def test_the_profile_and_its_cap(env):
    m = env.agent.memory
    m.add_fact("Works late", kind="fact")
    m.add_fact("Prefers 16:9 images", kind="preference")
    g = m.create_entity("project", "GAIFA", summary="the local AI hub")
    m.create_entity("project", "Ariadne")
    m.add_fact("Mods use ports 5100-5199", about=[g["id"]])
    text, shown = profile.build(m)
    mo = __import__("time").strftime("%Y-%m")
    assert text.startswith(f"About the user:\n- Prefers 16:9 images (since {mo})\n- Works late (since {mo})\nProjects: Ariadne; GAIFA (the local AI hub)")
    assert "5100" not in text and len(shown) == 2
    for i in range(200):
        m.add_fact(f"Fact number {i} about the user, written to be long enough to fill the profile")
    text, shown = profile.build(m)
    assert len(text.split("Projects:")[0]) <= profile.PROFILE_MAX + 40 and len(shown) < 200


async def test_a_chat_in_a_projects_folder_gets_its_facts(env):
    m = env.agent.memory
    g = m.create_entity("project", "GAIFA")
    m.add_fact("Mods use ports 5100-5199", about=[g["id"]])
    a = m.create_entity("project", "Site", anchors=[{"kind": "folder", "value": "/home/u/Agents"}])
    m.add_fact("The site is built with Astro", about=[a["id"]])
    env.hub.workspace = {"default": DEFAULT, "none": NONE}
    tid = await env.thread(settings={"environment": "default"})
    await env.send(tid, "hi")
    s = system(env)
    assert "This chat works in GAIFA (projects/GAIFA):\n- Mods use ports 5100-5199" in s    # by the folder's name
    assert "This chat works in Site (projects/Site):\n- The site is built with Astro" in s   # by an anchor above it
    await env.send(tid, "what are the mods' ports?")
    assert not recalled(env, tid)                               # in this chat's profile already: not recalled
    other = await env.thread(settings={"environment": "none"})
    await env.send(other, "hi")
    assert "This chat works in" not in system(env)


async def test_recall_is_stored_with_the_message_and_sent_the_same(env):
    m = env.agent.memory
    g = m.create_entity("project", "AIHub")
    f = m.add_fact("The hub listens on port 7000", about=[g["id"]])
    m.add_fact("Prefers 16:9 images")                        # in the profile: never recalled
    m.update_entity(g["id"], name="GAIFA")
    await env.agent.memory_index.flush()
    tid = await env.thread()
    await env.send(tid, "which port does AIHub use again?")
    mem = recalled(env, tid)
    assert [r["id"] for r in mem] == [f["id"]] and mem[0]["about"] == ["projects/GAIFA"]
    first = last_user(env)
    assert "<memory note=" in first and "- The hub listens on port 7000 (projects/GAIFA)" in first and "16:9" not in first
    m.update_fact(f["id"], text="The hub listens on 127.0.0.1:7000")
    await env.send(tid, "thanks")
    again = [x["content"] for x in env.model.received[-1]["messages"] if x["role"] == "user"][0]
    assert again == first                                      # byte-identical: the stored recall, not today's text
    assert not recalled(env, tid)                              # "thanks" calls nothing to mind
    assert m.need_fact(f["id"])["last_used"] is not None


async def test_recall_off_and_eval_threads(env):
    env.agent.memory.add_fact("The hub listens on port 7000", about=[{"name": "GAIFA", "kind": "project"}])
    (env.agent.cfg.data).mkdir(parents=True, exist_ok=True)
    (env.agent.cfg.data / "memory.json").write_text(json.dumps({"recall": False}))
    tid = await env.thread()
    await env.send(tid, "which port does GAIFA use?")
    assert not recalled(env, tid)
    (env.agent.cfg.data / "memory.json").unlink()
    ev = await env.thread(settings={"dry_run": True})
    await env.send(ev, "which port does GAIFA use?")
    assert not recalled(env, ev)
