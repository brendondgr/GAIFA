"""Plan 31.1: the GPU queue's rules (utils/gpu.py), without HTTP."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from utils.config import GpuCfg
from utils.events import Alerts, EventBus
from utils.gpu import ALERT, GpuError, GpuQueue


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def q():
    bus = EventBus()
    clock = Clock()
    cfg = SimpleNamespace(gpu=GpuCfg())
    queue = GpuQueue(bus, Alerts(bus), cfg=lambda: cfg.gpu, name_of=lambda s: s.upper(), clock=clock)
    queue.clock_ = clock
    queue.cfg_ = cfg
    queue.sub = bus.subscribe()
    return queue


def states(q: GpuQueue, *leases) -> list[str]:
    return [x.state for x in leases]


def test_first_lease_is_granted_and_the_next_group_waits(q):
    a = q.register("comfy", "job", "image")
    b = q.register("gen3d", "job", "model")
    assert states(q, a, b) == ["held", "waiting"]
    assert q.group == "comfy"
    q.release(a.id)
    assert b.state == "held" and q.group == "gen3d"


def test_fifo_within_a_class(q):
    hold = q.register("comfy", "job", "first")
    jobs = [q.register(f"m{i}", "job", f"job {i}") for i in range(3)]
    for expected in jobs:
        q.release(q.held()[0].id)
        assert expected.state == "held"
        assert all(j.state == "waiting" for j in jobs[jobs.index(expected) + 1:])
    assert hold.state == "released"


def test_interactive_goes_before_queued_jobs(q):
    q.register("comfy", "job", "running")
    job = q.register("gen3d", "job", "queued job")
    chat = q.register("lcpp", "interactive", "chat")
    assert [x.id for x in q.waiting()] == [chat.id, job.id]
    q.release(q.held()[0].id)
    assert chat.state == "held" and job.state == "waiting"


def test_background_only_when_nothing_else_waits(q):
    first = q.register("comfy", "job", "image")
    bg = q.register("embed", "background", "indexing")
    job = q.register("tts", "job", "speech")
    q.release(first.id)
    assert job.state == "held" and bg.state == "waiting"
    q.release(job.id)
    assert bg.state == "held"


def test_background_starts_at_once_on_a_free_slot(q):
    assert q.register("embed", "background", "indexing").state == "held"


def test_a_group_shares_and_a_job_waits_for_all_of_it(q):
    r1 = q.register("relay", "interactive", "chat 1", group="lcpp:8080")
    r2 = q.register("relay", "interactive", "chat 2", group="lcpp:8080")
    job = q.register("comfy", "job", "image")
    assert states(q, r1, r2, job) == ["held", "held", "waiting"]
    q.release(r1.id)
    assert job.state == "waiting"
    q.release(r2.id)
    assert job.state == "held"


def test_a_group_does_not_jump_a_waiting_lease_of_its_class(q):
    q.register("relay", "interactive", "chat 1", group="lcpp")
    other = q.register("decide", "interactive", "judge")
    late = q.register("relay", "interactive", "chat 2", group="lcpp")
    assert other.state == "waiting" and late.state == "waiting"      # no starving the judge
    # but interactive still joins ahead of a waiting job
    q2_job = q.register("comfy", "job", "image")
    assert q2_job.state == "waiting"


def test_nested_lease_runs_under_its_parent(q):
    parent = q.register("gen3d", "job", "model")
    other = q.register("tts", "job", "speech")
    child = q.register("comfy", "job", "trellis", parent=parent.id)
    assert states(q, parent, other, child) == ["held", "waiting", "held"]
    q.release(child.id)
    assert other.state == "waiting"           # the parent still holds
    q.release(parent.id)
    assert other.state == "held"


def test_parent_released_before_child_keeps_the_slot(q):
    parent = q.register("gen3d", "job", "model")
    child = q.register("comfy", "job", "trellis", parent=parent.id)
    other = q.register("tts", "job", "speech")
    q.release(parent.id)
    assert other.state == "waiting" and child.state == "held"
    q.release(child.id)
    assert other.state == "held"


async def test_expiry_frees_the_slot_with_an_alert(q):
    a = q.register("comfy", "job", "image")
    b = q.register("tts", "job", "speech")
    q.clock_.t += 30
    q.renew(a.id)
    q.renew(b.id)
    q.clock_.t += 45
    q.sweep()
    assert a.state == "held"                       # renewed 45 s ago, ttl 60
    q.renew(b.id)                                  # the waiting one keeps asking
    q.clock_.t += 20
    q.sweep()
    assert a.state == "expired" and b.state == "held"
    alerts = {x["id"]: x for x in q.alerts.list()}
    assert "COMFY" in alerts[ALERT]["text"] and alerts[ALERT]["service"] == "comfy"
    assert q.history[-1]["state"] == "expired"
    q.release(b.id)
    q.register("comfy", "job", "again")           # the mod is back: the alert goes
    assert ALERT not in {x["id"] for x in q.alerts.list()}


async def test_a_waiting_lease_nobody_polls_is_dropped(q):
    q.register("comfy", "job", "image")
    w = q.register("tts", "job", "speech")
    q.clock_.t += 61
    q.renew(q.held()[0].id)
    q.sweep()
    assert w.id not in q.leases and w.state == "expired"
    assert ALERT not in {x["id"] for x in q.alerts.list()}


def test_cancel_a_waiting_lease_but_not_a_held_one(q):
    a = q.register("comfy", "job", "image")
    b = q.register("tts", "job", "speech")
    q.cancel(b.id)
    assert b.state == "cancelled" and b.id not in q.leases
    with pytest.raises(GpuError) as e:
        q.cancel(a.id)
    assert e.value.status == 409
    with pytest.raises(GpuError):
        q.cancel("gl_nope")


def test_renew_unknown_re_registers_after_a_restart(q):
    held = q.renew("gl_aaaaaaaaaaaa", {"service": "comfy", "class": "job", "label": "image"})
    assert held.state == "held" and q.group == "comfy"
    same = q.renew("gl_bbbbbbbbbbbb", {"service": "comfy", "class": "job", "label": "image 2"})
    assert same.state == "held"                    # the same group shares
    other = q.renew("gl_cccccccccccc", {"service": "gen3d", "class": "job", "label": "model"})
    assert other.state == "waiting"                # told to wait
    with pytest.raises(GpuError) as e:
        q.renew("gl_dddddddddddd")
    assert e.value.status == 404


def test_queue_off_grants_everything(q):
    q.cfg_.gpu = GpuCfg(queue=False)
    a = q.register("comfy", "job", "image")
    b = q.register("gen3d", "job", "model")
    assert states(q, a, b) == ["held", "held"]
    assert q.view()["queue"] is False


def test_turning_the_queue_off_releases_the_waiting(q):
    q.register("comfy", "job", "image")
    b = q.register("gen3d", "job", "model")
    q.cfg_.gpu = GpuCfg(queue=False)
    q.pump()
    assert b.state == "held"


def test_view_ahead_and_eta(q):
    a = q.register("comfy", "job", "image", est_s=100)
    b = q.register("gen3d", "job", "model", est_s=200)
    c = q.register("tts", "job", "speech", est_s=10)
    v = q.view()
    assert v["holder"]["group"] == "comfy" and [x["id"] for x in v["holder"]["leases"]] == [a.id]
    assert [x["id"] for x in v["waiting"]] == [b.id, c.id]
    wc = v["waiting"][1]
    assert [x["service"] for x in wc["ahead"]] == ["comfy", "gen3d"]
    assert 299 <= wc["eta_s"] <= 300
    assert wc["name"] == "TTS"


def test_eta_learns_from_past_holds(q):
    a = q.register("comfy", "job", "image")
    a.granted_ts -= 40
    q.release(a.id)
    q.register("tts", "job", "x")
    b = q.register("comfy", "job", "image 2")
    assert q.estimate(b) == pytest.approx(40, abs=1)


def test_events_and_stats(q):
    a = q.register("comfy", "job", "image")
    q.register("tts", "job", "speech")
    q.release(a.id)
    kinds = []
    while not q.sub.queue.empty():
        ev = q.sub.queue.get_nowait()
        assert ev["type"] == "gpu" and "gpu" in ev
        kinds.append((ev["event"], ev["lease"]["service"]))
    assert kinds == [("granted", "comfy"), ("waiting", "tts"), ("released", "comfy"), ("granted", "tts")]
    stats = q.drain_stats()
    assert {(s, w) for s, w, _ in stats} == {("comfy", "wait"), ("comfy", "hold"), ("tts", "wait")}
    assert q.drain_stats() == []


async def test_acquire_waits_and_is_woken_by_the_release(q):
    a = q.register("comfy", "job", "image")
    task = asyncio.create_task(q.acquire(5, service="tts", cls="job", label="speech"))
    await asyncio.sleep(0.01)
    assert not task.done()
    q.release(a.id)
    lease = await asyncio.wait_for(task, 1)
    assert lease.state == "held"


async def test_acquire_times_out_waiting_and_keeps_its_place(q):
    q.register("comfy", "job", "image")
    lease = await q.acquire(0.05, service="tts", cls="job", label="speech")
    assert lease.state == "waiting"
    again = await q.acquire(0.01, service="tts", cls="job", label="speech", lease_id=lease.id)
    assert again is lease and len(q.waiting()) == 1


async def test_a_cancel_wakes_the_poller(q):
    q.register("comfy", "job", "image")
    w = q.register("tts", "job", "speech")
    task = asyncio.create_task(q.acquire(5, service="tts", lease_id=w.id))
    await asyncio.sleep(0.01)
    q.cancel(w.id)
    assert (await asyncio.wait_for(task, 1)).state == "cancelled"


def test_bad_class(q):
    with pytest.raises(GpuError):
        q.register("comfy", "urgent", "x")


async def test_a_mod_that_fails_frees_the_slot_at_once(q):
    await q.start()
    try:
        a = q.register("comfy", "job", "image")
        b = q.register("tts", "job", "speech")
        q.bus.publish({"type": "service", "service": {"id": "comfy", "state": "failed"}})
        for _ in range(50):
            if b.state == "held":
                break
            await asyncio.sleep(0.01)
        assert a.state == "expired" and b.state == "held"
        assert ALERT in {x["id"] for x in q.alerts.list()}
        q.bus.publish({"type": "service", "service": {"id": "tts", "state": "stopped"}})   # stopped by hand: no alert text change
        for _ in range(50):
            if b.state != "held":
                break
            await asyncio.sleep(0.01)
        assert b.state == "expired" and q.held() == []
    finally:
        await q.close()
