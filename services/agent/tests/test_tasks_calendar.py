"""Plan calendar 6.4: GET /v1/tasks/calendar: each task's due times in the range (daily, once; a task before an event
has none of its own) and its runs there; a range that's too long is refused."""

from __future__ import annotations

import time

from .test_task_schedule import schedule_with


async def _task(c, schedule, **kw):
    r = await c.post("/v1/tasks", json={"name": kw.pop("name", "T"), "schedule": schedule, "instructions": "Do it.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_due_times_and_runs(env):
    now = time.time()
    daily = await _task(env.client, {"kind": "daily", "time": "07:00"}, name="Digest")
    once = await _task(env.client, {"kind": "once", "at": time.strftime("%Y-%m-%dT%H:%M", time.localtime(now + 2 * 86400))}, name="Once")
    await _task(env.client, {"kind": "event", "item": "c_1", "before_min": 10}, name="Prep")
    r = (await env.client.get("/v1/tasks/calendar", params={"from": now, "to": now + 7 * 86400})).json()
    by = {t["name"]: t for t in r["tasks"]}
    assert len(by["Digest"]["due"]) == 7 and all(now <= d < now + 7 * 86400 for d in by["Digest"]["due"])
    assert by["Once"]["due"] == [once["next_due"]] and "Prep" not in by
    sch, clock = schedule_with(env, daily["next_due"] + 5)
    run = (await sch.tick())[0]
    await env.settle(run["thread_id"])
    r = (await env.client.get("/v1/tasks/calendar", params={"from": now, "to": now + 7 * 86400})).json()
    runs = next(t for t in r["tasks"] if t["name"] == "Digest")["runs"]
    assert [x["id"] for x in runs] == [run["id"]] and runs[0]["thread_id"] == run["thread_id"]
    assert (await env.client.get("/v1/tasks/calendar", params={"from": now, "to": now + 90 * 86400})).status_code == 422
