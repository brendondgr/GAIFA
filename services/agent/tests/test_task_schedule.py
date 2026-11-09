"""Plan scheduled-tasks 2.3: due tasks start a run and move on, a missed run runs once (latest, with how many passed),
a turned-off task never runs, Run now, and old run chats archived once a day."""

from __future__ import annotations

import time

from agent.tasks import when
from agent.tasks.schedule import TaskSchedule, latest_due

HOURLY = {"kind": "hourly", "every": 1, "minute": 0}


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _task(c, **kw):
    r = await c.post("/v1/tasks", json={"name": "Digest", "schedule": HOURLY, "instructions": "Check the feed.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def schedule_with(env, now: float) -> tuple[TaskSchedule, Clock]:
    clock = Clock(now)
    env.agent.runner.clock = clock
    return TaskSchedule(env.agent, env.agent.runner, clock=clock), clock


async def test_due_and_not_due(env):
    t = await _task(env.client)
    sch, clock = schedule_with(env, t["next_due"] - 10)
    assert await sch.tick() == []
    clock.t = t["next_due"] + 5
    started = await sch.tick()
    assert len(started) == 1 and started[0]["late"] == 0 and started[0]["due"] == t["next_due"]
    await env.settle(started[0]["thread_id"])
    nxt = env.agent.scheduled.get(t["id"])["next_due"]
    assert nxt == when.next_after(HOURLY, clock.t) and nxt > clock.t
    assert await sch.tick() == []                                     # not twice


async def test_missed_runs_once_for_the_latest(env):
    t = await _task(env.client)
    sch, clock = schedule_with(env, t["next_due"] + 5 * 3600 + 60)     # off for five hours
    started = await sch.tick()
    assert len(started) == 1
    run = started[0]
    assert run["late"] == 6 and run["why"] == "late" and run["due"] == t["next_due"] + 5 * 3600
    await env.settle(run["thread_id"])
    note = env.events(run["thread_id"], "note")[0]["payload"]["text"]
    assert "late: 6 due time(s) passed" in note
    assert latest_due(HOURLY, t["next_due"], t["next_due"] + 30) == (t["next_due"], 1)


async def test_turned_off_never_runs(env):
    t = await _task(env.client, enabled=False)
    sch, clock = schedule_with(env, time.time() + 10 * 86400)
    assert await sch.tick() == [] and env.agent.scheduled.runs(t["id"]) == []


async def test_run_now(env):
    t = await _task(env.client)
    r = await env.client.post(f"/v1/tasks/{t['id']}/run")
    assert r.status_code == 202 and r.json()["why"] == "run now"
    await env.settle(r.json()["thread_id"])
    assert env.agent.scheduled.get(t["id"])["next_due"] == t["next_due"]          # the schedule is unchanged
    assert (await env.client.post("/v1/tasks/k_nope/run")).status_code == 404


async def test_upkeep_archives_old_run_chats(env):
    t = await _task(env.client, keep_days=1)
    r = (await env.client.post(f"/v1/tasks/{t['id']}/run")).json()
    await env.settle(r["thread_id"])
    sch, clock = schedule_with(env, time.time() + 3600)
    assert sch.upkeep(clock.t) == 0                                       # a day old: kept
    sch.last_upkeep = None
    assert sch.upkeep(time.time() + 2 * 86400) == 1
    assert env.agent.store.thread(r["thread_id"])["archived"]
    assert sch.upkeep(time.time() + 2 * 86400) == 0                         # once a day
