"""Plan calendar 6.1–6.2: a task once (runs and turns off; a missed one runs late), and a task before a calendar
event (each occurrence once, from the calendar; a moved occurrence; missed before and after the event's end; the
item gone turns it off; the calendar down leaves it waiting)."""

from __future__ import annotations

import time

from agent.tasks import when

from .test_task_schedule import schedule_with


async def _task(c, schedule, **kw):
    r = await c.post("/v1/tasks", json={"name": "Prep", "schedule": schedule, "instructions": "Gather my notes.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def at(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M", time.localtime(ts))


def test_once_rules():
    assert when.check({"kind": "once", "at": "2026-11-14T07:00"}) == []
    assert when.check({"kind": "once", "at": "2026-02-30T07:00"}) and when.check({"kind": "once", "at": "soon"})
    s = {"kind": "once", "at": "2026-11-14T07:00"}
    t = time.mktime((2026, 11, 14, 7, 0, 0, 0, 0, -1))
    assert when.next_due(s, t - 60) == t and when.next_due(s, t) is None
    assert when.describe(s) == "Once, Sat 14 Nov 07:00"
    assert when.check({"kind": "event", "item": "c_1", "before_min": 30}) == [] and when.check({"kind": "event", "item": "x"})
    assert when.describe({"kind": "event", "item": "c_1", "before_min": 30, "title": "Design review"}) == "30 min before “Design review”, each time"
    assert when.next_due({"kind": "event", "item": "c_1"}, 0) is None


async def test_once_runs_and_turns_off(env):
    t0 = time.time() + 3600
    t = await _task(env.client, {"kind": "once", "at": at(t0)})
    assert t["next_due"] and t["enabled"]
    sch, clock = schedule_with(env, t["next_due"] + 5)
    started = await sch.tick()
    assert len(started) == 1 and started[0]["late"] == 0
    await env.settle(started[0]["thread_id"])
    after = env.agent.scheduled.get(t["id"])
    assert not after["enabled"] and after["next_due"] is None
    assert await sch.tick() == []


async def test_once_missed_runs_late(env):
    t = await _task(env.client, {"kind": "once", "at": at(time.time() + 3600)})
    sch, clock = schedule_with(env, t["next_due"] + 3 * 3600)
    started = await sch.tick()
    assert len(started) == 1 and started[0]["late"] == 1
    await env.settle(started[0]["thread_id"])


async def test_before_an_event_each_occurrence_once(env):
    now = time.time()
    env.hub.cal_items["c_rev"] = [{"occurrence": "o1", "ts": now + 3600, "end_ts": now + 7200, "title": "Review"},
                                  {"occurrence": "o2", "ts": now + 86400 + 3600, "end_ts": now + 86400 + 7200, "title": "Review"}]
    t = await _task(env.client, {"kind": "event", "item": "c_rev", "before_min": 30, "title": "Review"})
    assert t["next_due"] is None                             # the calendar answers it, at the scheduler's next check
    sch, clock = schedule_with(env, now)
    assert await sch.tick() == []
    assert env.agent.scheduled.get(t["id"])["next_due"] == now + 1800
    clock.t = now + 1800 + 5
    started = await sch.tick()
    assert len(started) == 1 and started[0]["occurrence"] == "o1" and started[0]["late"] == 0
    await env.settle(started[0]["thread_id"])
    clock.t = now + 1800 + 70                                # the next check: the next occurrence, o1 not again
    assert await sch.tick() == []
    assert env.agent.scheduled.get(t["id"])["next_due"] == now + 86400 + 1800


async def test_a_moved_occurrence_and_missed_ones(env):
    now = time.time()
    env.hub.cal_items["c_m"] = [{"occurrence": "o1", "ts": now - 600, "end_ts": now + 3000, "title": "Meet"}]   # started 10 min ago
    t = await _task(env.client, {"kind": "event", "item": "c_m", "before_min": 30})
    sch, clock = schedule_with(env, now)
    started = await sch.tick()                               # missed while down, the event still on: late
    assert len(started) == 1 and started[0]["late"] == 1 and started[0]["occurrence"] == "o1"
    await env.settle(started[0]["thread_id"])
    env.hub.cal_items["c_m"] = [{"occurrence": "o2", "ts": now - 7200, "end_ts": now - 3600, "title": "Meet"},   # over
                                {"occurrence": "o3", "ts": now + 5 * 3600, "end_ts": now + 6 * 3600, "title": "Meet"}]
    sch.events.forget()
    clock.t = now + 120
    assert await sch.tick() == []
    assert env.agent.scheduled.get(t["id"])["next_due"] == now + 5 * 3600 - 1800    # moved: the calendar's time


async def test_item_gone_and_calendar_down(env):
    now = time.time()
    env.hub.cal_items["c_x"] = [{"occurrence": "o1", "ts": now + 3600, "end_ts": now + 7200, "title": "X"}]
    t = await _task(env.client, {"kind": "event", "item": "c_x", "before_min": 10})
    sch, clock = schedule_with(env, now)
    env.hub.cal_down = True
    assert await sch.tick() == [] and env.agent.scheduled.get(t["id"])["enabled"]
    env.hub.cal_down = False
    del env.hub.cal_items["c_x"]
    sch.events.forget()
    clock.t = now + 60
    await sch.tick()
    assert not env.agent.scheduled.get(t["id"])["enabled"]


async def test_the_check(env):
    env.hub.cal_items["c_ok"] = [{"occurrence": "o1", "ts": time.time() + 3600, "end_ts": time.time() + 7200, "title": "Ok"}]
    t = await _task(env.client, {"kind": "event", "item": "c_ok", "before_min": 10})
    r = (await env.client.post(f"/v1/tasks/{t['id']}/check")).json()
    assert not [p for p in r["problems"] if p["field"] == "schedule"]
    gone = await _task(env.client, {"kind": "event", "item": "c_nope", "before_min": 10})
    r = (await env.client.post(f"/v1/tasks/{gone['id']}/check")).json()
    assert any("event_gone" in p["detail"] for p in r["problems"])
    env.hub.cal_down = True
    r = (await env.client.post(f"/v1/tasks/{t['id']}/check")).json()
    assert any(w["field"] == "schedule" for w in r["warnings"])
