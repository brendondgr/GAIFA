"""Plan scheduled-tasks 2.2: a run's chat (settings, grants, first message), the judge's health check, refused calls
counted, overlapping runs skipped, the queue, a project task's environments and `task_only`."""

from __future__ import annotations

import asyncio

from agent.projects.origin import chat_envs

DAILY = {"kind": "daily", "time": "07:00"}


async def _task(c, **kw):
    r = await c.post("/v1/tasks", json={"name": "Digest", "schedule": DAILY, "instructions": "Summarise the feed.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def _run_now(env, kid):
    r = await env.client.post(f"/v1/tasks/{kid}/run")
    assert r.status_code == 202, r.text
    run = r.json()
    if run.get("thread_id"):
        await env.settle(run["thread_id"])
    return env.agent.scheduled.run(run["id"])


async def test_a_run_s_chat(env):
    env.hub.tools["mcp_blender_scene"] = {**env.hub.tools["fake_get"], "name": "mcp_blender_scene", "mod": "mcp", "group": "mcp:blender"}
    t = await _task(env.client, allow={"tools": ["fake_wipe"], "sites": ["example.com", "*"], "mcp": ["blender"]},
                    settings={"disabled": ["comfy"]}, model="backup")
    run = await _run_now(env, t["id"])
    assert run["state"] == "done" and run["seen"] is False and run["judge"] == "ok" and run["why"] == "run now"
    th = env.agent.store.thread(run["thread_id"])
    s = th["settings"]
    assert s["task"] == t["id"] and s["task_run"] == run["id"] and s["unattended"] is True and s["no_learn"] is True
    assert s["disabled"] == ["comfy"] and s["mcp_on"] == ["mcp:blender"] and s["use_profile"] is True
    assert th["model"] == "backup" and th["mode"] == "auto" and th["title"].startswith("Digest · ")
    user = env.events(run["thread_id"], "user")[0]["payload"]
    assert user["text"] == "Summarise the feed." and user["by"] == "schedule"
    notes = [e["payload"]["text"] for e in env.events(run["thread_id"], "note")]
    assert "no one is watching" in notes[0]
    got = [(g["tool"], g.get("kind"), g.get("key")) for g in env.hub.grants if g["thread"] == run["thread_id"]]
    assert got == [("fake_wipe", None, None), ("web_fetch", "url:host", "example.com"), ("web_fetch", "url:any", "*"),
                   ("mcp_blender_*", None, None)]
    assert (await env.client.get("/v1/tasks/unread")).json()["count"] == 1


async def test_a_grant_the_hub_refuses_is_noted(env):
    env.hub.grant_fail.add("fake_get")
    t = await _task(env.client, allow={"tools": ["fake_get"]})
    run = await _run_now(env, t["id"])
    notes = [e["payload"]["text"] for e in env.events(run["thread_id"], "note")]
    assert any("fake_get couldn't be set" in n for n in notes) and run["state"] == "done"


async def test_judge_down(env):
    env.hub.judge_up = False
    t = await _task(env.client)
    run = await _run_now(env, t["id"])
    assert run["judge"].startswith("unavailable") and "decide mod is off" in run["judge"]
    notes = [e["payload"] for e in env.events(run["thread_id"], "note")]
    assert any(n["level"] == "warn" and "only pre-allowed calls" in n["text"] for n in notes)
    plan = await _task(env.client, name="Reader", mode="plan")
    assert (await _run_now(env, plan["id"]))["judge"] is None                 # no judge outside Auto


async def test_refused_calls_are_counted_and_a_pre_allow_runs(env):
    env.model.queue({"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}]}, {"text": "Couldn't wipe a."})
    t = await _task(env.client)
    run = await _run_now(env, t["id"])
    assert run["refused"] == 1 and run["state"] == "done"
    res = env.events(run["thread_id"], "tool_result")[0]["payload"]
    assert res["error"]["code"] == "unattended" and not env.hub.approvals
    env.model.queue({"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "b"}}]}, {"text": "Wiped b."})
    allowed = await _task(env.client, name="Wiper", allow={"tools": ["fake_wipe"]})
    run = await _run_now(env, allowed["id"])
    assert run["refused"] == 0 and [c["arguments"] for c in env.hub.calls if c["name"] == "fake_wipe"] == [{"id": "b"}]


async def test_a_test_run_has_cards(env):
    env.model.queue({"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}]}, {"text": "done"})
    t = await _task(env.client)
    r = await env.client.post(f"/v1/tasks/{t['id']}/test")
    run = r.json()
    assert run["test"] is True and "unattended" not in env.agent.store.thread(run["thread_id"])["settings"]
    assert await env.settle(run["thread_id"]) == "waiting"
    assert env.agent.scheduled.run(run["id"])["state"] == "running"            # you're there to answer
    aid = env.events(run["thread_id"], "approval")[0]["payload"]["approval_id"]
    await env.client.post(f"/v1/threads/{run['thread_id']}/approval", json={"approval_id": aid, "approve": True})
    await env.settle(run["thread_id"])
    assert env.agent.scheduled.run(run["id"])["state"] == "done"


async def test_overlap_skips_and_the_queue(env):
    runner = env.agent.runner
    t = await _task(env.client)
    gate = asyncio.Event()

    async def slow(*a, **k):
        await gate.wait()
        return {"available": True}
    env.agent.hub.judge_status = slow                     # the first run holds at its judge check
    first = asyncio.create_task(runner.start(env.agent.scheduled.get(t["id"]), "schedule"))
    await asyncio.sleep(0.05)
    again = await runner.start(env.agent.scheduled.get(t["id"]), "schedule")
    assert again["state"] == "skipped" and again["why"] == "still running"
    runner.parallel = 1
    other = await _task(env.client, name="Other")
    queued = await runner.start(env.agent.scheduled.get(other["id"]), "schedule")
    assert queued["state"] == "queued"
    gate.set()
    run = await first
    await env.settle(run["thread_id"])
    await asyncio.sleep(0.1)
    got = env.agent.scheduled.run(queued["id"])
    assert got["state"] in ("running", "done") and got["thread_id"]             # launched when the first ended
    await env.settle(got["thread_id"])
    late = env.agent.scheduled.add_run(other["id"], runner.clock() - 7200, state="queued")
    await runner.drain()
    assert env.agent.scheduled.run(late["id"])["state"] == "skipped" and env.agent.scheduled.run(late["id"])["why"] == "busy"


async def test_project_task_environments(env):
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Thesis", "environments": ["grants"], "defaults": {"model": "backup", "disabled": ["tts"]}})).json()
    t = await _task(c, project_id=p["id"])
    await c.post(f"/v1/tasks/{t['id']}/folders", json={"path": "/home/u/out", "level": "edit"})
    run = await _run_now(env, t["id"])
    s = env.agent.store.thread(run["thread_id"])["settings"]
    assert s["project"] == p["id"] and s["environment"] == "grants" and s["task_env"] == "task-" + t["id"][2:]
    assert s["disabled"] == ["tts"] and "task_only" not in s
    assert env.agent.store.thread(run["thread_id"])["model"] == "backup"           # the project's default model
    assert chat_envs(s, env.agent.projects) == {"environment": "grants", "environments": ["grants", "task-" + t["id"][2:]]}
    await c.patch(f"/v1/tasks/{t['id']}", json={"only_own": True})
    run = await _run_now(env, t["id"])
    s = env.agent.store.thread(run["thread_id"])["settings"]
    assert s["task_only"] is True and chat_envs(s, env.agent.projects) == {"environment": "task-" + t["id"][2:]}
    alone = await _task(c, name="Alone")
    run = await _run_now(env, alone["id"])
    assert chat_envs(env.agent.store.thread(run["thread_id"])["settings"], env.agent.projects) == {}   # Default
