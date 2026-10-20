"""22.6: when the learner runs: nightly, after idle_min with something new, Learn now; one run at a
time; pausing on a user message; off when learning is off."""

from __future__ import annotations

import asyncio
import time

from agent.learn.loop import Learner
from agent.learn.schedule import Schedule


class FakeLearner:
    def __init__(self, active=False):
        self.runs_started: list[str] = []
        self.active = active
        self.gate = asyncio.Event()

    async def run(self, domains=None, why="manual"):
        self.runs_started.append(why)
        await self.gate.wait()
        return {"state": "done"}

    def user_active(self, since):
        return self.active


def at(hour, minute=0):
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, minute, 0, 0, 0, -1))


async def test_nightly_once_and_one_run_at_a_time(env):
    fl = FakeLearner()
    now = [at(2, 59)]
    s = Schedule(env.agent, fl, clock=lambda: now[0])
    assert await s.tick() is None
    now[0] = at(3, 1)
    assert await s.tick() == "nightly"
    assert await s.tick() is None and s.busy                    # one at a time
    assert s.start("manual") is False
    fl.gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await s.tick() is None                               # once per night
    assert fl.runs_started == ["nightly"]


async def test_idle_needs_something_new(env):
    fl = FakeLearner()
    fl.gate.set()
    tid = env.agent.store.create_thread(title="real")["id"]
    ev = env.agent.store.append(tid, "user", {"text": "hi"})
    now = [ev["ts"] + 30 * 60]
    s = Schedule(env.agent, fl, clock=lambda: now[0])
    s.last_nightly = time.strftime("%Y-%m-%d")
    assert await s.tick() is None                               # 30 minutes: not yet
    now[0] = ev["ts"] + 61 * 60
    assert await s.tick() == "idle"
    await asyncio.sleep(0)
    now[0] += 3 * 3600
    assert await s.tick() is None                               # nothing new since that run


async def test_learning_off_and_the_route(env):
    fl = FakeLearner()
    s = Schedule(env.agent, fl, clock=lambda: at(3, 30))

    async def off():
        return {"learning": {"enabled": False}}
    env.agent.hub.settings = off
    assert await s.tick() is None and fl.runs_started == []
    r = await env.client.post("/v1/learn/run")
    assert r.status_code == 409


async def test_a_user_message_pauses_a_run(env):
    from agent.learn.loop import Paused
    lr = Learner(env.agent, "http://agent", model="main")
    tid = env.agent.store.create_thread(title="real")["id"]
    rec = {"id": "r", "started": time.time() - 1, "ledger": [], "stage": ""}
    env.agent.store.append(tid, "user", {"text": "I'm back"})
    try:
        await lr.ask(rec, "x:reflect", "prompt")
        raise AssertionError("should pause")
    except Paused as p:
        assert str(p) == "x:reflect"
