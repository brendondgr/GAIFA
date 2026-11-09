"""Plan projects 3.5: before a project chat's answer, pages the message matches and whose copy is older than their limit
are fetched again (and nothing else is); a slow fetch leaves the last copy to the model; a project_refresh event says
what happened."""

from __future__ import annotations

import time

from agent.projects import fresh

from .test_project_index import _wait

MELT = "https://news.example.org/alps-summer-melt"
GARDEN = "https://garden.example.com/tomato-planting"


async def _setup(env, max_age=3600):
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Thesis"})).json()
    env.hub.pages[MELT] = "Glaciers in the Alps lost four percent of their ice this summer: record melt."
    env.hub.pages[GARDEN] = "Plant tomatoes after frost, full sun."
    ids = {}
    for url in (MELT, GARDEN):
        s = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": url, "max_age_s": max_age})).json()
        ids[url] = s["id"]
        await _wait(lambda: env.agent.projects.source(s["id"])["status"] == "ok")
        await _wait(lambda: env.agent.project_index_store.rows(p["id"], [s["id"]]))
    tid = (await c.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    return p, ids, tid


def age(env, sid, seconds):
    env.agent.projects.update_source(sid, fetched=time.time() - seconds)


async def test_a_matching_message_refreshes_a_stale_page(env):
    p, ids, tid = await _setup(env)
    age(env, ids[MELT], 7200)
    age(env, ids[GARDEN], 7200)
    before = env.agent.projects.source(ids[MELT])["output_id"]
    env.hub.page_reads.clear()
    env.hub.pages[MELT] = "Updated: glaciers in the Alps lost five percent of their ice."
    env.model.queue({"text": "Five percent."})
    await env.send(tid, "How much ice did the glaciers in the Alps lose?")
    assert env.hub.page_reads == [MELT]                                      # only the matched page
    ev = env.payloads(tid, "project_refresh")
    assert ev == [{"for": env.events(tid, "user")[-1]["seq"], "pages": [{"sid": ids[MELT], "title": "Alps Summer Melt", "ok": True}]}]
    assert env.agent.projects.source(ids[MELT])["output_id"] != before
    sys = next(m["content"] for m in env.model.received[-1]["messages"] if m["role"] == "system")
    assert "five percent" in sys                                             # the model read the new copy
    types = env.types(tid)
    assert types.index("project_refresh") < types.index("assistant")


async def test_a_fresh_page_is_not_fetched(env):
    p, ids, tid = await _setup(env)
    env.hub.page_reads.clear()
    env.model.queue({"text": "ok"})
    await env.send(tid, "How much ice did the glaciers in the Alps lose?")
    assert env.hub.page_reads == [] and env.payloads(tid, "project_refresh") == []


async def test_never_refresh_and_an_unrelated_message(env):
    p, ids, tid = await _setup(env)
    age(env, ids[MELT], 7200)
    env.hub.page_reads.clear()
    env.model.queue({"text": "ok"}, {"text": "ok"})
    await env.send(tid, "Write me a haiku about autumn leaves.")
    assert env.hub.page_reads == [] and env.payloads(tid, "project_refresh") == []
    await env.client.patch(f"/v1/projects/{p['id']}/sources/{ids[MELT]}", json={"max_age_s": None})
    await env.send(tid, "How much ice did the glaciers in the Alps lose?")
    assert env.hub.page_reads == []


async def test_named_by_its_title(env):
    p, ids, tid = await _setup(env)
    age(env, ids[GARDEN], 90000)
    env.hub.embed_down = True                                                # names still match without the embed mod
    got = await fresh.match(env.agent, p["id"], "anything new on the tomato planting page?")
    assert [s["id"] for s in got] == [ids[GARDEN]]


async def test_a_slow_fetch_times_out_to_the_last_copy(env, monkeypatch):
    p, ids, tid = await _setup(env)
    age(env, ids[MELT], 7200)
    monkeypatch.setattr(fresh, "FRESH_WAIT_S", 0.2)
    env.hub.page_delay = 1.0
    env.model.queue({"text": "From the last copy."})
    await env.send(tid, "How much ice did the glaciers in the Alps lose?")
    ev = env.payloads(tid, "project_refresh")[0]
    assert ev["pages"] == [{"sid": ids[MELT], "title": "Alps Summer Melt", "ok": False, "slow": True}]
    sys = next(m["content"] for m in env.model.received[-1]["messages"] if m["role"] == "system")
    assert "four percent" in sys and "being fetched again" in sys
    await _wait(lambda: env.agent.projects.source(ids[MELT])["status"] == "ok", 5)   # it finishes in the background


def test_stale():
    now = 10_000.0
    assert fresh.stale({"max_age_s": 3600, "fetched": now - 4000}, now)
    assert not fresh.stale({"max_age_s": 3600, "fetched": now - 100}, now)
    assert not fresh.stale({"max_age_s": None, "fetched": 0}, now)
    assert fresh.stale({"max_age_s": 60, "fetched": None}, now)
