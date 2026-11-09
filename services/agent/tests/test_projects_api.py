"""Plan projects 1.2: the project routes, new chats taking a project's defaults, moving chats in and out, groups by
project, delete leaving its chats as ordinary chats, and the `project` event on streams that watch projects."""

from __future__ import annotations

import asyncio

from .conftest import serve
from .test_streams import read_events


async def _project(c, **kw):
    r = await c.post("/v1/projects", json={"name": "Thesis", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_crud(env):
    c = env.client
    p = await _project(c, description="chapters", instructions="Answer in French", environments=["grants", "notes"],
                       defaults={"model": "main", "mode": "auto", "disabled": ["comfy"]})
    assert p["id"].startswith("p_") and p["sources"] == [] and p["environments"] == ["grants", "notes"]
    await _project(c, name="Garden")
    assert [x["name"] for x in (await c.get("/v1/projects", params={"sort": "name"})).json()] == ["Garden", "Thesis"]
    assert [x["name"] for x in (await c.get("/v1/projects", params={"q": "chap"})).json()] == ["Thesis"]
    r = await c.patch(f"/v1/projects/{p['id']}", json={"name": "Thesis 2", "pinned": True, "defaults": {"mode": "plan"}})
    assert r.status_code == 200 and r.json()["name"] == "Thesis 2" and r.json()["defaults"] == {"mode": "plan"}
    assert (await c.get("/v1/projects")).json()[0]["id"] == p["id"]                       # pinned first
    assert (await c.get(f"/v1/projects/{p['id']}")).json()["pinned"] is True
    assert (await c.post("/v1/projects", json={"name": ""})).status_code == 422
    assert (await c.post("/v1/projects", json={"name": "x", "instructions": "y" * 16_001})).status_code == 422
    r = await c.get("/v1/projects/p_nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_project"
    assert (await c.delete(f"/v1/projects/{p['id']}")).json()["deleted"] == p["id"]
    assert (await c.get(f"/v1/projects/{p['id']}")).status_code == 404


async def test_new_chat_takes_defaults_request_wins(env):
    c = env.client
    p = await _project(c, environments=["grants"], defaults={"model": "backup", "mode": "auto", "disabled": ["comfy"],
                                                             "pinned": ["tts"], "mcp_on": ["mcp:blender"]})
    r = await c.post("/v1/threads", json={"settings": {"project": p["id"]}})
    t = r.json()
    assert t["model"] == "backup" and t["mode"] == "auto"
    assert t["settings"] == {"project": p["id"], "environment": "grants", "disabled": ["comfy"], "pinned": ["tts"],
                             "mcp_on": ["mcp:blender"]}
    r = await c.post("/v1/threads", json={"model": "main", "mode": "plan", "settings": {"project": p["id"], "disabled": [],
                                                                                         "environment": "notes"}})
    t = r.json()
    assert t["model"] == "main" and t["mode"] == "plan"                                  # the request's own win
    assert t["settings"]["disabled"] == [] and t["settings"]["environment"] == "notes" and t["settings"]["pinned"] == ["tts"]
    assert (await c.post("/v1/threads", json={"settings": {"project": "p_nope"}})).status_code == 404
    plain = (await c.post("/v1/threads", json={"settings": {"project": None}})).json()
    assert "project" not in plain["settings"] and plain["mode"] == "manual"
    listed = (await c.get(f"/v1/projects/{p['id']}/threads")).json()
    assert len(listed) == 2 and all(x["settings"]["project"] == p["id"] for x in listed)
    assert len((await c.get("/v1/threads", params={"project": "none"})).json()) == 1


async def test_move_in_and_out(env):
    c = env.client
    p = await _project(c, environments=["grants"], defaults={"model": "backup", "mode": "auto"})
    tid = await env.thread(model="main", mode="manual", settings={"environment": "notes", "pinned": ["x"]})
    t = (await c.patch(f"/v1/threads/{tid}", json={"settings": {"project": p["id"]}})).json()
    assert t["settings"]["project"] == p["id"] and t["settings"]["environment"] == "grants"
    assert t["model"] == "main" and t["mode"] == "manual" and t["settings"]["pinned"] == ["x"]   # model and mode stay
    t = (await c.patch(f"/v1/threads/{tid}", json={"settings": {"project": None}})).json()
    assert "project" not in t["settings"] and t["settings"]["environment"] == "grants"           # environment kept
    assert (await c.patch(f"/v1/threads/{tid}", json={"settings": {"project": "p_nope"}})).status_code == 404


async def test_primary_environment_follows(env):
    c = env.client
    p = await _project(c, environments=["grants"])
    tids = [(await c.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"] for _ in range(2)]
    other = await env.thread(settings={"environment": "grants"})
    await c.patch(f"/v1/projects/{p['id']}", json={"environments": ["notes", "grants"]})
    assert [env.agent.store.thread(t)["settings"]["environment"] for t in tids] == ["notes", "notes"]
    assert env.agent.store.thread(other)["settings"]["environment"] == "grants"


async def test_groups_by_project(env):
    c = env.client
    a, b = await _project(c, name="A"), await _project(c, name="B")
    for pid in (a["id"], a["id"], b["id"]):
        await c.post("/v1/threads", json={"settings": {"project": pid}})
    await env.thread()
    groups = {g["project"]: g["count"] for g in (await c.get("/v1/threads/groups", params={"by": "project"})).json()}
    assert groups == {a["id"]: 2, b["id"]: 1, "none": 1}
    assert {"environment", "count"} <= set((await c.get("/v1/threads/groups")).json()[0])
    assert (await c.get("/v1/threads/groups", params={"by": "nope"})).status_code == 422


async def test_delete_leaves_ordinary_chats(env):
    c = env.client
    p = await _project(c, environments=["grants"])
    tid = (await c.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    before = env.agent.store.thread(tid)["updated"]
    r = await c.delete(f"/v1/projects/{p['id']}")
    assert r.status_code == 200 and r.json()["chats"] == 1
    t = (await c.get(f"/v1/threads/{tid}")).json()
    assert "project" not in t["settings"] and t["settings"]["environment"] == "grants" and t["updated"] == before
    assert (await c.get("/v1/projects")).json() == []


async def test_project_event(env):
    q: asyncio.Queue = asyncio.Queue()
    env.agent.live.watchers.add(q)
    p = await _project(env.client)
    await env.client.patch(f"/v1/projects/{p['id']}", json={"description": "new"})
    await env.client.delete(f"/v1/projects/{p['id']}")
    evs = [q.get_nowait() for _ in range(q.qsize())]
    assert [e["type"] for e in evs] == ["project"] * 3 and all(e["id"] == p["id"] for e in evs)
    assert evs[1]["project"]["description"] == "new" and evs[2]["project"] is None


async def test_project_event_on_a_watching_stream(env):
    tid = await env.thread()
    server, task, port = await serve(env.app)
    try:
        url = f"http://127.0.0.1:{port}/v1/streams?threads={tid}&watch=projects"
        reader = asyncio.create_task(read_events(url, lambda e: any(x["type"] == "project" for x in e)))
        plain = asyncio.create_task(read_events(f"http://127.0.0.1:{port}/v1/streams?threads={tid}",
                                                lambda e: any(x["type"] == "project" for x in e), timeout=1.5))
        await asyncio.sleep(0.3)
        await _project(env.client, name="Live")
        evs = await reader
        assert [e for e in evs if e["type"] == "project"][0]["project"]["name"] == "Live"
        try:
            await plain
            raise AssertionError("a stream that doesn't watch projects got the event")
        except (asyncio.TimeoutError, TimeoutError):
            pass
    finally:
        server.should_exit = True
        await task


async def test_own_folders(env):
    """Plan projects 2.3: the first folder makes the hidden environment; a level change; a removal; the workspace mod's
    rules come back as they are; delete removes the environment."""
    c = env.client
    p = await _project(c, name="Thesis")
    assert (await c.get(f"/v1/projects/{p['id']}/folders")).json() == []
    r = await c.post(f"/v1/projects/{p['id']}/folders", json={"path": "/home/u/refs"})
    assert r.status_code == 201 and r.json()["level"] == "read"
    own = env.agent.projects.get(p["id"])["own_env"]
    assert own == "proj-" + p["id"][2:]
    assert env.hub.ws_envs[own]["name"] == "Thesis (project)" and env.hub.ws_envs[own]["project"] == p["id"]
    await c.post(f"/v1/projects/{p['id']}/folders", json={"path": "/home/u/drafts", "level": "edit"})
    assert len(env.hub.ws_envs) == 1                                                          # made once
    r = await c.post(f"/v1/projects/{p['id']}/folders", json={"path": "/home/u/Agents/GAIFA", "level": "edit"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "capped"
    assert (await c.patch(f"/v1/projects/{p['id']}/folders/refs", json={"level": "run"})).json()["level"] == "run"
    assert (await c.delete(f"/v1/projects/{p['id']}/folders/drafts")).json() == {"removed": "drafts"}
    assert [(f["id"], f["level"]) for f in (await c.get(f"/v1/projects/{p['id']}/folders")).json()] == [("refs", "run")]
    assert (await c.delete(f"/v1/projects/{p['id']}/folders/nope")).status_code == 404
    assert (await c.post(f"/v1/projects/{p['id']}/folders", json={"path": "/x", "level": "admin"})).status_code == 422
    # another project with the same name gets another environment name
    q = await _project(c, name="Thesis")
    await c.post(f"/v1/projects/{q['id']}/folders", json={"path": "/home/u/other"})
    assert env.hub.ws_envs["proj-" + q["id"][2:]]["name"] == f"Thesis (project {q['id'][2:]})"
    done = (await c.delete(f"/v1/projects/{p['id']}")).json()
    assert done["environment"] == own and own not in env.hub.ws_envs
    bare = await _project(c, name="Bare")
    assert (await c.delete(f"/v1/projects/{bare['id']}")).json()["environment"] == "none"
    assert (await c.patch(f"/v1/projects/{bare['id']}/folders/x", json={"level": "edit"})).status_code == 404
