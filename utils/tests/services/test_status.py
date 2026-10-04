"""2.4: status polling: load, busy, stats, jobs; events only on change."""

from __future__ import annotations

import asyncio

import httpx

from utils import status
from utils.tests.services.conftest import until


def test_validate_good_body():
    st, problems = status.validate({
        "loaded": True, "busy": False, "idle_s": 42, "memory_estimate_gb": 9.2,
        "stats": [{"label": "Voices", "value": 3}, {"label": "Clips today", "value": 12, "reset": "daily", "unit": "clips"}],
        "jobs": [{"id": "j_1", "label": "fox", "progress": 0.4, "state": "running", "route": "#/s/gen3d/jobs?id=j_1"}],
        "extra": "ignored",
    })
    assert problems == []
    assert st["loaded"] is True and st["idle_s"] == 42.0 and st["memory_estimate_gb"] == 9.2
    assert st["stats"][1] == {"label": "Clips today", "value": 12, "reset": "daily", "unit": "clips"}
    assert st["jobs"][0]["route"] == "#/s/gen3d/jobs?id=j_1"


def test_validate_keeps_the_good_parts_and_lists_the_rest():
    st, problems = status.validate({
        "loaded": "yes", "busy": 1, "idle_s": -1,
        "stats": [{"value": 1}, 3, {"label": "ok", "value": "fine"}, {"label": "x", "value": [1]}, {"label": "five", "value": 5}],
        "jobs": [{"id": 1}, {"id": "a", "state": "weird"}, {"id": "b", "progress": 2}],
    })
    assert st["loaded"] is None and st["busy"] is False and st["idle_s"] is None
    assert st["stats"] == [{"label": "ok", "value": "fine"}]
    assert st["jobs"] == [{"id": "b", "label": "b", "progress": None, "state": "running"}]
    assert problems == [
        "loaded must be true, false or null",
        "busy must be true or false",
        "idle_s must be a number ≥ 0 or null",
        "stats has 5 entries; at most 4 are shown",
        "stats[0] needs a non-empty label",
        "stats[1] needs a non-empty label",
        "stats[3] (x): value must be a number or a string",
        "jobs[0] needs a string id",
        "jobs[1] (a): state must be one of cancelled, done, failed, queued, running",
        "jobs[2] (b): progress must be between 0 and 1, or null",
    ]


def test_validate_rejects_non_objects():
    assert status.validate([1, 2])[1] == ["status must be a JSON object, got list"]


def test_slug():
    assert status.slug("Clips today") == "clips_today" and status.slug("p50 TTFT (ms)") == "p50_ttft_ms" and status.slug("!!") == "stat"


async def test_stats_and_load_from_status(rig):
    rig.add("fake-ok")
    rig.add("fake-mem")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    await mgr.start("fake-mem", wait=True)
    ok, mem = mgr.get("fake-ok"), mgr.get("fake-mem")
    await until(lambda: ok.stats and mem.stats)
    assert ok.load == "n/a"  # status says loaded: null and no [memory]
    assert [s["label"] for s in ok.stats] == ["Requests", "Outputs today"] and ok.stats[1]["reset"] == "daily"
    assert ok.idle_s is not None
    assert mem.load == "unloaded" and mem.memory_estimate_gb == 0.062  # the mod rounds 64 MB to 3 places
    async with httpx.AsyncClient() as c:
        await c.post(f"{mem.url}/v1/load", json={"mb": 1})
    await until(lambda: mem.load == "loaded", timeout=3)
    assert any(e["type"] == "service" and e["service"]["id"] == "fake-mem" and e["service"]["load"] == "loaded" for e in rig.events)


async def test_jobs_are_published_and_busy_speeds_up_polling(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    assert status.interval(mgr, svc) == mgr.t.status_idle_s
    async with httpx.AsyncClient() as c:
        await c.post(f"{svc.url}/v1/jobs", json={"label": "low-poly fox", "seconds": 0.8})
    await until(lambda: svc.busy, timeout=3)
    assert status.interval(mgr, svc) == mgr.t.status_busy_s
    await until(lambda: svc.jobs and svc.jobs[0]["state"] == "done", timeout=5)
    assert not svc.busy
    jobs = [e["job"] for e in rig.events if e["type"] == "job"]
    assert jobs[0]["service"] == "fake-ok" and jobs[0]["label"] == "low-poly fox" and jobs[0]["state"] == "running"
    assert jobs[-1]["state"] == "done" and jobs[-1]["progress"] == 1.0
    progress = [j["progress"] for j in jobs]
    assert progress == sorted(progress) and len(set(progress)) == len(progress)  # one event per change


async def test_no_event_when_nothing_changed(rig):
    rig.add("fake-mem")
    mgr = await rig.manager()
    await mgr.start("fake-mem", wait=True)
    svc = mgr.get("fake-mem")
    await until(lambda: svc.stats)
    await asyncio.sleep(0.2)
    n = len([e for e in rig.events if e["type"] == "service"])
    await asyncio.sleep(1.0)  # ~3 more idle polls; nothing changes (idle_s alone doesn't count)
    assert len([e for e in rig.events if e["type"] == "service"]) == n


async def test_jobs_end_when_the_mod_stops(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    async with httpx.AsyncClient() as c:
        await c.post(f"{svc.url}/v1/jobs", json={"label": "long", "seconds": 60})
    await until(lambda: svc.jobs)
    await mgr.stop("fake-ok", wait=True)
    last = [e["job"] for e in rig.events if e["type"] == "job"][-1]
    assert last["state"] == "cancelled" and svc.jobs == [] and svc.stats == []


async def test_bad_status_body_does_not_break_anything(rig):
    rig.add("fake-ok")
    rig.config('[services.fake-ok]\nenv = { FAKE_BAD_STATUS = "1" }')
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    await until(lambda: svc.status is not None)
    await asyncio.sleep(0.4)
    assert svc.state == "ready" and svc.stats == [] and svc.jobs == [] and svc.load == "n/a"


async def test_hub_load_states_hold_until_confirmed(rig):
    rig.add("fake-mem")
    mgr = await rig.manager()
    await mgr.start("fake-mem", wait=True)
    svc = mgr.get("fake-mem")
    svc.load = "loading"  # what the load route sets (2.7)
    status.apply(mgr, svc, status.validate({"loaded": False})[0])
    assert svc.load == "loading"
    status.apply(mgr, svc, status.validate({"loaded": True})[0])
    assert svc.load == "loaded"


async def test_without_status_route_load_is_na_or_hub_managed(rig):
    rig.add("fake-ok", edit={"status": '"/nothing"'})
    d = rig.add("fake-ok", as_id="plain")
    (d / "service.toml").write_text((d / "service.toml").read_text().replace('status = "/v1/status"\n', ""))
    mgr = await rig.manager()
    await mgr.start("plain", wait=True)
    assert mgr.get("plain").load == "n/a" and mgr.get("plain").m.run.status is None
    await mgr.start("fake-ok", wait=True)  # status route 404s: values just stay as they were
    await asyncio.sleep(0.4)
    assert mgr.get("fake-ok").state == "ready" and mgr.get("fake-ok").stats == []
