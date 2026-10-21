"""14.9: AGENT.md re-read every turn, skills listed and read (mod and user), memory written,
shown in the prompt and edited in settings."""

from __future__ import annotations


async def test_agent_md_is_reread_each_turn(env):
    tid = await env.thread()
    data = env.agent.cfg.data
    data.mkdir(parents=True, exist_ok=True)
    (data / "AGENT.md").write_text("Rule one.")
    await env.send(tid, "a")
    assert "Rule one." in env.model.received[-1]["messages"][0]["content"]
    r = await env.client.put("/v1/settings", json={"agent_md": "Rule two."})
    assert r.json()["agent_md"] == "Rule two."
    await env.send(tid, "b")
    s = env.model.received[-1]["messages"][0]["content"]
    assert "Rule two." in s and "Rule one." not in s


async def test_skills_from_mods_and_the_user(env):
    d = env.agent.cfg.data / "skills" / "my-style"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: my-style\ndescription: My house style\n---\nAlways pastel colors.")
    s = (await env.client.get("/v1/settings")).json()["skills"]
    assert {x["id"] for x in s} == {"fake/drawing", "user/my-style"}
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "fake/drawing"}},
                                    {"name": "read_skill", "arguments": {"name": "my-style"}},
                                    {"name": "read_skill", "arguments": {"name": "../../etc"}}]}, {"text": "read"})
    tid = await env.thread()
    await env.send(tid, "/my-style draw")
    calls = [c["id"] for c in env.payloads(tid, "tool_call")]
    by = {r["id"]: r for r in env.payloads(tid, "tool_result")}
    a, b, c = (by[i] for i in calls)
    assert a["content"] == "Use 16:9 for landscapes." and b["content"] == "Always pastel colors."
    assert c["status"] == "error" and c["error"]["code"] == "not_found"
    assert "- user/my-style: My house style" in env.model.received[0]["messages"][0]["content"]


async def test_remember_writes_memory_and_shows_it(env):
    env.model.queue({"tool_calls": [{"name": "remember", "arguments": {"text": "likes 16:9 images"}},
                                    {"name": "remember", "arguments": {"text": "voice is Brendon", "topic": "Voices"}}]}, {"text": "noted"})
    tid = await env.thread()
    await env.send(tid, "remember I like 16:9 and my voice is Brendon")
    for _ in range(2):                         # each one is a card (the hub's default ask list), approved in turn
        ap = env.payloads(tid, "approval")[-1]
        assert ap["tool"] == "hub_set_preference"
        assert (await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True})).status_code == 202
        await env.settle(tid)
    assert [p["text"] for p in env.payloads(tid, "memory")] == ["likes 16:9 images", "voice is Brendon"]
    # plan 21.4: remember saves a preference in the hub (every chat, and MCP clients, see it)
    assert [(p["value"], p["cue"], p["scope"]) for p in env.hub.prefs] == [("likes 16:9 images", "", "agent"), ("voice is Brendon", "Voices", "agent")]
    await env.send(tid, "next")
    assert "- likes 16:9 images" in env.model.received[-1]["messages"][0]["content"]
    await env.client.put("/v1/settings", json={"memory": "- prefers square images\n"})      # Settings → Agent still edits the file
    await env.send(tid, "and now")
    s = env.model.received[-1]["messages"][0]["content"]
    assert "prefers square images" in s and "likes 16:9" in s


async def test_tool_preferences_show_only_for_loaded_tools_and_not_when_opted_out(env):
    env.hub.prefs.append({"id": "pref_9", "scope": "tool", "tool": "fake_make_image", "field": "aspect", "value": "16:9",
                          "when": {}, "cue": "", "source": "stated", "state": "active", "evidence": [], "seen": 1})
    tid = await env.thread()
    await env.send(tid, "hi")
    assert "fake_make_image: aspect" not in env.model.received[-1]["messages"][0]["content"]       # not loaded
    tid2 = await env.thread(settings={"pinned": ["fake"]})
    await env.send(tid2, "hi")
    assert "- fake_make_image: aspect = '16:9' (the hub fills it in)" in env.model.received[-1]["messages"][0]["content"]
    tid3 = await env.thread(settings={"pinned": ["fake"], "no_learn": True})
    await env.send(tid3, "hi")
    assert "fake_make_image: aspect" not in env.model.received[-1]["messages"][0]["content"]


async def test_old_memory_files_are_imported_once(env, tmp_path):
    from agent.knowledge import Knowledge
    mem = env.agent.cfg.data / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_text("- likes cats (2026-10-01)\n- [Voices](voices.md): the voices\n")
    (mem / "voices.md").write_text("- Brendon is my voice (2026-10-02)\n")
    k = Knowledge(env.agent.cfg.data, env.agent.hub)
    assert await k.import_memory() == 2 and await k.import_memory() == 0
    assert [(p["value"], p["cue"]) for p in env.hub.prefs] == [("likes cats", ""), ("Brendon is my voice", "voices")]
