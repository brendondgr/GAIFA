"""Plan scheduled-tasks 3.2–3.3: a test run's approvals as suggested pre-allows and adding them; the judgement log's
outcomes and what decided each call (pre-allow, rules, judge, mode, you, local)."""

from __future__ import annotations

DAILY = {"kind": "daily", "time": "07:00"}


async def _task(c, **kw):
    r = await c.post("/v1/tasks", json={"name": "Digest", "schedule": DAILY, "instructions": "Check the feed.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_suggested_pre_allows_from_a_test_run(env):
    c = env.client
    env.hub.tools["mcp_blender_scene"] = {**env.hub.tools["fake_wipe"], "name": "mcp_blender_scene", "mod": "mcp", "group": "mcp:blender"}
    env.model.queue({"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}},
                                    {"name": "mcp_blender_scene", "arguments": {"id": "b"}},
                                    {"name": "hub_set_preference", "arguments": {"tool": "x", "field": "y", "value": 1}}]},
                    {"text": "done"})
    t = await _task(c)
    run = (await c.post(f"/v1/tasks/{t['id']}/test")).json()
    tid = run["thread_id"]
    answered: set[str] = set()
    while await env.settle(tid) == "waiting":                        # one card at a time
        a = next(e["payload"] for e in env.events(tid, "approval") if e["payload"]["approval_id"] not in answered)
        answered.add(a["approval_id"])
        await c.post(f"/v1/threads/{tid}/approval", json={"approval_id": a["approval_id"], "approve": a["tool"] != "hub_set_preference"})
    assert len(answered) == 3 and env.agent.scheduled.run(run["id"])["state"] == "done"
    got = (await c.get(f"/v1/tasks/{t['id']}/runs/{run['id']}/allows")).json()
    assert [(g["kind"], g["value"]) for g in got] == [("tool", "fake_wipe"), ("mcp", "blender")]       # not the denied one
    r = await c.post(f"/v1/tasks/{t['id']}/allow", json={"tools": ["fake_wipe"], "mcp": ["blender"]})
    assert r.status_code == 200 and r.json()["allow"] == {"tools": ["fake_wipe"], "sites": [], "mcp": ["blender"]}
    assert (await c.get(f"/v1/tasks/{t['id']}/runs/{run['id']}/allows")).json() == []                 # allowed now
    r = await c.post(f"/v1/tasks/{t['id']}/allow", json={"tools": ["nothing_*"]})
    assert r.status_code == 409 and r.json()["detail"]["data"]["task"]["enabled"] is False
    log = (await c.get(f"/v1/tasks/{t['id']}/runs/{run['id']}/log")).json()
    assert [(x["tool"], x["outcome"], x["by"]) for x in log] == [
        ("fake_wipe", "asked", "you"), ("mcp_blender_scene", "asked", "you"), ("hub_set_preference", "asked", "you")]
    assert log[2]["reason"] == "you said no"


async def test_the_log_of_an_unattended_run(env):
    c = env.client
    env.model.queue({"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}, {"name": "fake_get", "arguments": {"id": "b"}},
                                    {"name": "hub_set_preference", "arguments": {"tool": "x", "field": "y", "value": 1}},
                                    {"name": "task_note", "arguments": {"action": "add", "text": "Feed at /srv."}}]},
                    {"text": "done"})
    t = await _task(c, allow={"tools": ["fake_wipe"]})
    run = (await c.post(f"/v1/tasks/{t['id']}/run")).json()
    await env.settle(run["thread_id"])
    log = (await c.get(f"/v1/tasks/{t['id']}/runs/{run['id']}/log")).json()
    rows = {x["tool"]: x for x in log}
    assert (rows["fake_wipe"]["outcome"], rows["fake_wipe"]["by"]) == ("allowed", "pre-allow")
    assert (rows["fake_get"]["outcome"], rows["fake_get"]["by"]) == ("allowed", "mode")
    assert (rows["hub_set_preference"]["outcome"], rows["hub_set_preference"]["by"]) == ("refused", "mode")
    assert "no one is here" in rows["hub_set_preference"]["reason"]
    assert (rows["task_note"]["outcome"], rows["task_note"]["by"]) == ("allowed", "local")
    assert rows["fake_get"]["summary"] == 'fake_get: {"id": "b"}'
    assert (await c.get(f"/v1/tasks/{t['id']}/runs/r_nope/log")).status_code == 404


async def test_judged_rows(env):
    """The judge's verdicts, as the hub puts them on results (no fake hub judges, so the events are written here)."""
    from agent.tasks.log import log
    tid = await env.thread()
    a = env.agent
    for i, (judge, err) in enumerate([({"verdict": "allow", "source": "rules", "reason": "a test runner", "summary": "workspace_run: pytest"}, None),
                                      ({"verdict": "allow", "source": "model", "reason": "the user asked for it"}, None),
                                      ({"verdict": "ask", "source": "model", "reason": "not in the instructions", "refused": True},
                                       {"code": "unattended", "detail": "asks"}),
                                      ({"verdict": "ask", "source": "user", "reason": "your ask rule"}, {"code": "unattended", "detail": "x"})]):
        a.emit(tid, "tool_call", {"id": f"c{i}", "name": "workspace_run", "arguments": {"command": "pytest"}, "by": "model"})
        a.emit(tid, "tool_result", {"id": f"c{i}", "name": "workspace_run", "status": "denied" if err else "done",
                                    "content": "", "judge": judge, **({"error": err} if err else {})})
    rows = [(r["outcome"], r["by"], r["reason"]) for r in log(a, tid)]
    assert rows == [("allowed", "rules", "a test runner"), ("allowed", "judge", "the user asked for it"),
                    ("refused", "judge", "not in the instructions"), ("refused", "rules", "your ask rule")]
    assert log(a, tid)[0]["summary"] == "workspace_run: pytest"
