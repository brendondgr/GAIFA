"""structured-memory 1.3: agent preferences and the old memory files become facts; preferences are retired."""

from __future__ import annotations

from agent.memory import importer


async def test_preferences_and_files_become_facts_once(env):
    env.hub.prefs = [{"id": "pref_1", "scope": "agent", "value": "Prefers short replies", "state": "active", "source": "stated"},
                     {"id": "pref_2", "scope": "tool", "tool": "tts_speak", "field": "voice", "value": "Hope", "state": "active"}]
    mem = env.agent.cfg.data / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_text("- likes 16:9 images (2026-10-01)\n- [Voices](voices.md): the voices\n# Heading\n")
    (mem / "voices.md").write_text("- my voice is Brendon\n")
    await importer.run(env.agent.memory, env.agent.hub, env.agent.cfg.data)   # (or the one at start got there first)
    facts = {f["text"]: f for f in env.agent.memory.facts(current=True)}
    assert set(facts) == {"Prefers short replies", "likes 16:9 images", "my voice is Brendon"}
    assert facts["Prefers short replies"]["source"] == "stated" and facts["likes 16:9 images"]["source"] == "imported"
    assert {e["path"] for e in facts["my voice is Brendon"]["entities"]} == {"you", "topics/voices"}
    assert env.hub.prefs[0]["state"] == "retired" and env.hub.prefs[0]["note"].startswith("moved to memory: f_")
    assert env.hub.prefs[1]["state"] == "active"                      # tool preferences stay
    assert await importer.run(env.agent.memory, env.agent.hub, env.agent.cfg.data) == 0
    env.hub.prefs.append({"id": "pref_3", "scope": "agent", "value": "Works late", "state": "active", "source": "stated"})
    assert await importer.run(env.agent.memory, env.agent.hub, env.agent.cfg.data) == 1   # new preferences still move


async def test_the_prompt_lists_current_facts(env):
    env.agent.memory.add_fact("Prefers 16:9 images", kind="preference")
    g = env.agent.memory.create_entity("project", "GAIFA")
    env.agent.memory.add_fact("Mods use ports 5100-5199", about=[g["id"]])
    tid = await env.thread()
    await env.send(tid, "hi")
    system = env.model.received[-1]["messages"][0]["content"]
    assert "About the user:\n- Prefers 16:9 images" in system and "Projects: GAIFA" in system
