"""Plan projects 3.1: files and pages in a project. A file is an output already in GAIFA; a page is fetched through the
hub's /api/web/read in the background, and a failed fetch keeps the last copy; a refresh replaces the output; every
change is a project_source event."""

from __future__ import annotations

import asyncio
import time

from agent.projects import sources

URL = "https://news.example.org/alps-summer-melt"


async def _project(c, **kw):
    return (await c.post("/v1/projects", json={"name": "Thesis", **kw})).json()


async def _settled(env, pid, sid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = env.agent.projects.source(sid)
        if s and s["status"] != "fetching":
            return s
        await asyncio.sleep(0.02)
    raise TimeoutError(sid)


async def test_add_a_file(env):
    c = env.client
    p = await _project(c)
    oid = env.hub.doc("Mass balance.pdf", pages=["Glaciers lost mass.", "Table 2."])
    r = await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": f"output:{oid}"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["kind"] == "file" and s["output_id"] == oid and s["title"] == "Mass balance.pdf" and s["chars"] > 20
    assert (await c.get(f"/v1/projects/{p['id']}")).json()["sources"][0]["id"] == s["id"]
    assert "Glaciers lost mass." in await sources.text(env.agent, s)
    img = env.hub._output("image", "a fox", "a fox")["output_id"]
    r = await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": img})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_text"
    assert (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": oid})).status_code == 409
    assert (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file"})).status_code == 422
    r = await c.delete(f"/v1/projects/{p['id']}/sources/{s['id']}")
    assert r.json() == {"removed": s["id"]} and oid in env.hub.outputs                   # the output stays


async def test_add_a_page_then_refresh(env):
    c = env.client
    env.hub.pages[URL] = "The Alps lost 4% of their ice this summer."
    q: asyncio.Queue = asyncio.Queue()
    env.agent.live.watchers.add(q)
    p = await _project(c)
    r = await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": URL, "max_age_s": 900})
    assert r.status_code == 201 and r.json()["status"] == "fetching" and r.json()["max_age_s"] == 900
    s = await _settled(env, p["id"], r.json()["id"])
    assert s["status"] == "ok" and s["output_id"] and s["fetched"] and s["title"] == "Alps Summer Melt"
    first = s["output_id"]
    env.hub.pages[URL] = "Updated: the Alps lost 5% of their ice."
    s2 = (await c.post(f"/v1/projects/{p['id']}/sources/{s['id']}/refresh")).json()
    assert s2["status"] == "ok" and s2["output_id"] != first and s2["fetched"] >= s["fetched"]
    assert "5%" in await sources.text(env.agent, s2)
    states = [e["source"]["status"] for e in [q.get_nowait() for _ in range(q.qsize())] if e["type"] == "project_source"]
    assert states[:3] == ["fetching", "fetching", "ok"] and states[-2:] == ["fetching", "ok"]
    assert (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": "ftp://x"})).json()["detail"]["code"] == "bad_url"


async def test_a_failed_fetch_keeps_the_last_copy(env):
    c = env.client
    env.hub.pages[URL] = "First copy."
    p = await _project(c)
    sid = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": URL})).json()["id"]
    s = await _settled(env, p["id"], sid)
    env.hub.page_fail.add(URL)
    s2 = (await c.post(f"/v1/projects/{p['id']}/sources/{sid}/refresh")).json()
    assert s2["status"] == "error" and "didn't answer" in s2["error"] and s2["output_id"] == s["output_id"]
    assert s2["fetched"] == s["fetched"]
    env.hub.page_fail.clear()
    assert (await c.post(f"/v1/projects/{p['id']}/sources/{sid}/refresh")).json()["error"] is None


async def test_patch_and_order(env):
    c = env.client
    p = await _project(c)
    a = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": env.hub.doc("a.md", text="a", kind="text")})).json()
    b = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": env.hub.doc("b.md", text="b", kind="text")})).json()
    r = (await c.patch(f"/v1/projects/{p['id']}/sources/{b['id']}", json={"position": 0, "title": "B"})).json()
    assert r["title"] == "B" and [s["id"] for s in (await c.get(f"/v1/projects/{p['id']}")).json()["sources"]] == [b["id"], a["id"]]
    env.hub.pages[URL] = "x"
    pg = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": URL})).json()
    await _settled(env, p["id"], pg["id"])
    assert (await c.patch(f"/v1/projects/{p['id']}/sources/{pg['id']}", json={"max_age_s": None})).json()["max_age_s"] is None
    assert (await c.post(f"/v1/projects/{p['id']}/sources/{a['id']}/refresh")).json()["detail"]["code"] == "not_a_page"
    other = await _project(c, name="Other")
    assert (await c.delete(f"/v1/projects/{other['id']}/sources/{a['id']}")).status_code == 404


def test_age_words():
    assert [sources.age_words(s) for s in (10, 60, 600, 7200, 3 * 86400)] == ["just now", "1 min", "10 min", "2 h", "3 days"]
