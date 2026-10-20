"""21.5: the miner: card edits, question answers and thumbs become proposed preferences after 2 times
in 2 chats; contradictions hold them back; fading; dry runs and opted-out chats never count."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent.learn import mine

FIX = Path(__file__).parent / "fixtures" / "approvals-2026-10.json"


def ap(i, chat, final, edited, tool="gen3d_make_3d", **origin):
    return {"id": f"ap_{i}", "tool": tool, "state": "approved", "final": final, "edited": edited, "origin": {"thread": chat, **origin}}


def test_card_edits_need_two_chats_and_count_contradictions():
    rows = mine.card_edits([ap(1, "t1", {"preset": "fast"}, ["preset"]), ap(2, "t1", {"preset": "fast"}, ["preset"]),
                            ap(3, "t2", {"preset": "fast"}, ["preset"]), ap(4, "t3", {"preset": "base"}, ["preset"]),
                            ap(5, "t4", {"preset": "fast"}, ["preset"], dry_run=True)])
    fast = rows[("gen3d_make_3d", "preset", '"fast"')]
    assert fast["chats"] == {"thread:t1", "thread:t2"} and len(fast["approvals"]) == 3 and fast["against"] == 1


def test_the_real_cards_propose_fast_3d_without_parts():
    """The 2026-10 approvals (settings only): 7 of 8 gen3d cards changed preset to fast and dropped parts."""
    rows = mine.card_edits(json.loads(FIX.read_text()))
    fast = rows[("gen3d_make_3d", "preset", '"fast"')]
    stages = rows[("gen3d_make_3d", "stages", '["shape", "preview"]')]
    assert len(fast["approvals"]) >= 7 and len(fast["chats"]) >= 2 and fast["against"] * 2 < len(fast["approvals"])
    assert len(stages["approvals"]) >= 7 and len(stages["chats"]) >= 2


async def test_run_proposes_once_and_skips_what_is_known(env):
    approvals = [ap(1, "t1", {"preset": "fast"}, ["preset"]), ap(2, "t2", {"preset": "fast"}, ["preset"])]

    async def fake_approvals(state="all", limit=1000):
        return approvals
    env.agent.hub.approvals = fake_approvals
    done = await mine.run(env.agent.hub, env.agent.store)
    assert [(p["tool"], p["field"], p["value"], p["state"], p["source"]) for p in done["proposed"]] == \
        [("gen3d_make_3d", "preset", "fast", "proposed", "inferred")]
    again = await mine.run(env.agent.hub, env.agent.store)
    assert again["proposed"] == []


async def test_answers_and_thumbs(env):
    for t in ("t_a", "t_b"):
        tid = env.agent.store.create_thread(title=t)["id"]
        env.agent.store.append(tid, "answer", {"id": "q", "answers": {"How should I make the 3D model?": "From the text"}})
        env.agent.store.append(tid, "tool_call", {"id": "c", "name": "comfy_generate_image", "arguments": {"workflow": "zimage-turbo"}})
        env.agent.store.append(tid, "tool_result", {"id": "c", "status": "done", "outputs": [{"output_id": f"o{t}"}]})
        env.agent.store.append(tid, "feedback", {"value": "up", "output_id": f"o{t}"})
    opted = env.agent.store.create_thread(title="private", settings={"no_learn": True})["id"]
    env.agent.store.append(opted, "answer", {"id": "q", "answers": {"Which voice?": "Brendon"}})
    evs = env.agent.store.events_by_type(["answer", "tool_call", "tool_result", "feedback"])
    a = mine.answers(evs)
    assert list(a.values())[0]["chats"] and len(a) == 1                 # the opted-out chat isn't read
    th = mine.thumbs(evs)[("comfy_generate_image", "workflow", '"zimage-turbo"')]
    assert th["up"] == 2 and len(th["chats"]) == 2
    done = await mine.run(env.agent.hub, env.agent.store)
    texts = [p["value"] for p in done["proposed"]]
    assert any("From the text" in str(t) for t in texts) and "zimage-turbo" in texts


async def test_inferred_preferences_fade(env):
    env.hub.prefs.append({"id": "pref_old", "scope": "tool", "tool": "gen3d_make_3d", "field": "preset", "value": "fast", "when": {},
                          "source": "inferred", "state": "active", "last_used_ts": time.time() - 90 * 86400})
    env.hub.prefs.append({"id": "pref_said", "scope": "tool", "tool": "gen3d_make_3d", "field": "engine", "value": "trellis2", "when": {},
                          "source": "stated", "state": "active", "last_used_ts": time.time() - 90 * 86400})

    async def update_pref(pid, patch):
        p = next(x for x in env.hub.prefs if x["id"] == pid)
        p.update(patch)
        return p
    env.agent.hub.update_pref = update_pref
    done = await mine.run(env.agent.hub, env.agent.store)
    assert [p["id"] for p in done["faded"]] == ["pref_old"]
    assert next(p for p in env.hub.prefs if p["id"] == "pref_said")["state"] == "active"
