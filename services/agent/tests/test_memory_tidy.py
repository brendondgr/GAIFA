"""structured-memory 4.2: nightly tidying: ended facts retired, duplicate entries proposed for merging (once),
summaries written, unused learned facts proposed for retiring; stated facts untouched."""

from __future__ import annotations

import time

from agent.memory import tidy


async def test_ended_duplicates_fading_and_summaries(env):
    m = env.agent.memory
    stated = m.add_fact("Is in Lisbon this week", valid_until="2020-01-01")
    trip = m.add_fact("Has a deadline on Friday", source="inferred")
    m.set_fact_state(trip["id"], "active")
    m.update_fact(trip["id"], valid_until="2020-01-02")
    a = m.create_entity("project", "Ariadne")
    b = m.create_entity("project", "Ariadne site")
    m.add_fact("Built with Astro", about=[b["id"]])
    m.add_fact("Deploys to Netlify", about=[b["id"]])
    old = m.add_fact("Likes jazz", source="inferred")
    m.set_fact_state(old["id"], "active")
    with m.lock:
        m.c.execute("UPDATE mem_facts SET recorded = ?, last_used = NULL WHERE id = ?", (time.time() - 400 * 86400, old["id"]))
    env.model.queue({"text": "Ariadne site: a site built with Astro that deploys to Netlify."}, {"text": "A project."})
    out = await tidy.run(env.agent)
    assert out["ended"] == 1 and out["merges"] == 1 and out["fading"] == 1 and out["summaries"] >= 1
    assert m.need_fact(trip["id"])["state"] == "retired" and m.need_fact(stated["id"])["state"] == "active"   # stated: untouched
    props = {f["text"]: f for f in m.facts(state="proposed")}
    assert "Merge Ariadne into Ariadne site" in props and "Stop remembering: Likes jazz" in props
    assert m.need(b["id"])["summary"].startswith("Ariadne site: a site built with Astro")
    again = await tidy.run(env.agent)
    assert again["merges"] == 0 and again["fading"] == 0                        # never proposed twice
    m.set_fact_state(props["Merge Ariadne into Ariadne site"]["id"], "active")
    assert m.resolve("Ariadne")["id"] == b["id"] and m.entity_row(a["id"])["state"] == "merged"
    m.set_fact_state(props["Stop remembering: Likes jazz"]["id"], "active")
    assert m.need_fact(old["id"])["state"] == "retired"
