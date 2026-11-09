"""Plan scheduled-tasks 1.3: the task routes: CRUD, a bad schedule, next_due, runs and unread, notes, folders, the
`task` events, delete leaving ordinary chats, and a deleted project detaching its tasks."""

from __future__ import annotations

import asyncio

DAILY = {"kind": "daily", "time": "07:00"}


async def _task(c, **kw):
    r = await c.post("/v1/tasks", json={"name": "Digest", "schedule": DAILY, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_crud(env):
    c = env.client
    t = await _task(c, instructions="Summarise the news", allow={"tools": ["web_*"], "sites": ["example.com"]},
                    settings={"disabled": ["comfy"]})
    assert t["id"].startswith("k_") and t["mode"] == "auto" and t["when"] == "Every day at 07:00" and t["next_due"]
    assert t["allow"] == {"tools": ["web_*"], "sites": ["example.com"], "mcp": []} and t["settings"] == {"disabled": ["comfy"]}
    assert [x["id"] for x in (await c.get("/v1/tasks")).json()] == [t["id"]]
    assert (await c.get(f"/v1/tasks/{t['id']}")).json()["name"] == "Digest"
    r = await c.patch(f"/v1/tasks/{t['id']}", json={"enabled": False, "instructions": "new"})
    assert r.status_code == 200 and r.json()["next_due"] is None and r.json()["instructions"] == "new"
    r = await c.patch(f"/v1/tasks/{t['id']}", json={"enabled": True, "schedule": {"kind": "hourly", "every": 2, "minute": 5}})
    assert r.json()["next_due"] and r.json()["when"] == "Every 2 hours at :05"
    bad = await c.post("/v1/tasks", json={"name": "x", "schedule": {"kind": "daily", "time": "noon"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_schedule"
    assert (await c.patch(f"/v1/tasks/{t['id']}", json={"schedule": {"kind": "weekly"}})).status_code == 422
    assert (await c.post("/v1/tasks", json={"name": "x", "schedule": DAILY, "mode": "manual"})).status_code == 422
    assert (await c.post("/v1/tasks", json={"name": "x", "schedule": DAILY, "project_id": "p_nope"})).status_code == 404
    assert (await c.get("/v1/tasks/k_nope")).json()["detail"]["code"] == "unknown_task"
    assert (await c.delete(f"/v1/tasks/{t['id']}")).json()["deleted"] == t["id"]
    assert (await c.get(f"/v1/tasks/{t['id']}")).status_code == 404


async def test_project_filter_and_detach(env):
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Thesis"})).json()
    t = await _task(c, project_id=p["id"], only_own=True)
    await _task(c, name="Alone")
    assert [x["id"] for x in (await c.get("/v1/tasks", params={"project": p["id"]})).json()] == [t["id"]]
    assert [x["name"] for x in (await c.get("/v1/tasks", params={"project": "none"})).json()] == ["Alone"]
    done = (await c.delete(f"/v1/projects/{p['id']}")).json()
    assert done["tasks"] == 1
    got = (await c.get(f"/v1/tasks/{t['id']}")).json()
    assert got["project_id"] is None and not got["enabled"] and not got["only_own"]


async def test_runs_unread_and_threads(env):
    c = env.client
    t = await _task(c)
    tid = (await c.post("/v1/threads", json={"settings": {"task": t["id"], "task_run": "r_x"}})).json()["id"]
    k = env.agent.scheduled
    r = k.add_run(t["id"], 100.0, state="done", thread_id=tid, ended=110.0, seen=False)
    assert [x["id"] for x in (await c.get(f"/v1/tasks/{t['id']}/runs")).json()] == [r["id"]]
    assert (await c.get("/v1/tasks/unread")).json() == {"count": 1, "tasks": {t["id"]: 1}}
    assert (await c.get(f"/v1/tasks/{t['id']}")).json()["last_run"]["id"] == r["id"]
    assert (await c.patch(f"/v1/tasks/{t['id']}/runs/{r['id']}", json={"seen": True})).json()["seen"] is True
    assert (await c.get("/v1/tasks/unread")).json()["count"] == 0
    assert (await c.patch(f"/v1/tasks/{t['id']}/runs/r_nope", json={"seen": True})).status_code == 404
    assert [x["id"] for x in (await c.get("/v1/threads", params={"task": t["id"]})).json()] == [tid]
    done = (await c.delete(f"/v1/tasks/{t['id']}")).json()
    assert done["chats"] == 1 and done["environment"] == "none"
    assert "task" not in (await c.get(f"/v1/threads/{tid}")).json()["settings"]


async def test_notes(env):
    c = env.client
    t = await _task(c)
    n = (await c.post(f"/v1/tasks/{t['id']}/notes", json={"text": "the feed is at /srv/feed.xml"})).json()
    assert (await c.patch(f"/v1/tasks/{t['id']}/notes/{n['id']}", json={"text": "moved"})).json()["text"] == "moved"
    assert [x["text"] for x in (await c.get(f"/v1/tasks/{t['id']}/notes")).json()] == ["moved"]
    assert (await c.post(f"/v1/tasks/{t['id']}/notes", json={"text": "x" * 501})).status_code == 422
    assert (await c.delete(f"/v1/tasks/{t['id']}/notes/{n['id']}")).json() == {"deleted": n["id"]}
    assert (await c.delete(f"/v1/tasks/{t['id']}/notes/{n['id']}")).status_code == 404


async def test_own_folders(env):
    c = env.client
    t = await _task(c, name="Backup")
    assert (await c.get(f"/v1/tasks/{t['id']}/folders")).json() == []
    assert (await c.patch(f"/v1/tasks/{t['id']}/folders/x", json={"level": "edit"})).status_code == 404
    r = await c.post(f"/v1/tasks/{t['id']}/folders", json={"path": "/home/u/backups", "level": "edit"})
    assert r.status_code == 201 and r.json()["level"] == "edit"
    own = env.agent.scheduled.get(t["id"])["own_env"]
    assert own == "task-" + t["id"][2:] and env.hub.ws_envs[own]["name"] == "Backup (scheduled)"
    assert env.hub.ws_envs[own]["project"] == t["id"]
    assert [f["id"] for f in (await c.get(f"/v1/tasks/{t['id']}/folders")).json()] == ["backups"]
    done = (await c.delete(f"/v1/tasks/{t['id']}")).json()
    assert done["environment"] == own and own not in env.hub.ws_envs


async def test_task_events(env):
    q: asyncio.Queue = asyncio.Queue()
    env.agent.live.watchers.add(q)
    t = await _task(env.client)
    await env.client.patch(f"/v1/tasks/{t['id']}", json={"name": "New"})
    await env.client.delete(f"/v1/tasks/{t['id']}")
    evs = [q.get_nowait() for _ in range(q.qsize())]
    assert [e["type"] for e in evs] == ["task"] * 3
    assert evs[1]["task"]["name"] == "New" and evs[2]["task"] is None
