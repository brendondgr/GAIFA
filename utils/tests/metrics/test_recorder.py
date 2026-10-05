"""6.1: what the recorder writes: samples every tick, daily counters, service/load/job history,
the gap a hub downtime leaves, and the low-disk alert (6.4)."""

from __future__ import annotations

from collections import namedtuple

from utils.events import Alerts, EventBus
from utils.metrics import recorder as recmod
from utils.metrics.store import DAY
from utils.tests.metrics.conftest import GB, T0, FakeSvc


async def series_values(db, name):
    return [(r["ts"], r["value"]) for r in await db.fetchall(
        "SELECT ts, value FROM metrics_raw m JOIN series s ON s.id = m.sid WHERE s.name = ? ORDER BY ts", (name,))]


async def test_tick_records_memory_jobs_and_stats(db, rec):
    a = FakeSvc("a", stats=[{"label": "Clips today", "value": 3, "reset": "daily"}, {"label": "Voices", "value": "n/a"},
                            {"label": "Latency", "value": 12.5, "unit": "ms"}],
                jobs=[{"id": "j1", "state": "running"}, {"id": "j2", "state": "queued"}])
    b = FakeSvc("b", state="stopped", stats=[{"label": "Calls", "value": 9}])
    r = rec(a, b)
    samples = {i.name: v for i, v in await r.tick(T0 + 3)}
    assert samples["mem.used"] == 30 * GB and samples["mem.other"] == 20 * GB and samples["mem.reserve"] == 12 * GB
    assert samples["gpu.gtt_used"] == 5 * GB and "gpu.vram_used" not in samples  # no VRAM on this GPU
    assert samples["mem.svc.a"] == 10 * GB and samples["jobs.running"] == 1
    assert samples["svc.a.stat.clips_today"] == 3 and samples["svc.a.stat.latency"] == 12.5
    assert "svc.a.stat.voices" not in samples and "svc.b.stat.calls" not in samples  # strings and stopped mods
    assert await series_values(db, "mem.used") == [(T0, 30 * GB)]  # on the 10 s grid
    infos = {i.name: i.as_dict() for i in await r.store.series()}
    assert infos["svc.a.stat.clips_today"] == {"name": "svc.a.stat.clips_today", "label": "Clips today", "unit": "count", "service": "a", "reset": "daily"}
    assert infos["svc.a.stat.latency"]["unit"] == "ms" and infos["mem.svc.a"]["label"] == "A"
    hb = await db.fetchone("SELECT value FROM kv WHERE key = 'metrics.heartbeat'")
    assert hb["value"] == str(T0)


async def test_daily_counter_reset_breaks_the_line(db, rec):
    a = FakeSvc("a", stats=[{"label": "Clips today", "value": 40, "reset": "daily"}, {"label": "Total", "value": 40}])
    r = rec(a)
    await r.tick(T0)
    a.stats = [{"label": "Clips today", "value": 30, "reset": "daily"}, {"label": "Total", "value": 30}]
    await r.tick(T0 + 10)  # a drop on the same day is real
    a.stats = [{"label": "Clips today", "value": 2, "reset": "daily"}, {"label": "Total", "value": 2}]
    await r.tick(T0 + DAY)  # the next day: the counter reset
    await r.tick(T0 + DAY + 10)
    assert await series_values(db, "svc.a.stat.clips_today") == [(T0, 40), (T0 + 10, 30), (T0 + DAY, None), (T0 + DAY + 10, 2)]
    assert [v for _, v in await series_values(db, "svc.a.stat.total")] == [40, 30, 2, 2]


async def test_service_load_and_job_history(db, rec):
    a = FakeSvc("a", state="starting", load="unloaded")
    r = rec(a)
    await r.recover()
    await r.reconcile()
    r.clock.t = T0 + 5
    await r.on_event({"type": "service", "service": {"id": "a", "state": "ready", "load": "unloaded"}})
    await r.on_event({"type": "service", "service": {"id": "a", "state": "ready", "load": "loading"}})
    r.clock.t = T0 + 10
    await r.on_event({"type": "service", "service": {"id": "a", "state": "ready", "load": "loaded"}})
    await r.on_event({"type": "job", "job": {"id": "j1", "service": "a", "label": "fox", "state": "queued", "progress": None}})
    r.clock.t = T0 + 12
    await r.on_event({"type": "job", "job": {"id": "j1", "service": "a", "label": "fox", "state": "running", "progress": 0.1}})
    await r.on_event({"type": "job", "job": {"id": "j1", "service": "a", "label": "fox", "state": "running", "progress": 0.5}})
    r.clock.t = T0 + 20
    await r.on_event({"type": "job", "job": {"id": "j1", "service": "a", "label": "fox", "state": "done", "progress": 1}})
    await r.on_event({"type": "job", "job": {"id": "j9", "service": "a", "label": "seen done", "state": "failed", "progress": None}})
    await r.on_event({"type": "service", "service": {"id": "a", "state": "ready", "load": "unloading"}})
    r.clock.t = T0 + 30
    await r.on_event({"type": "service", "service": {"id": "a", "state": "stopping", "load": "unloaded"}})
    r.clock.t = T0 + 31
    await r.on_event({"type": "service", "service": {"id": "a", "state": "stopped", "load": "unloaded"}})
    states = [(x["state"], x["from_ts"], x["to_ts"]) for x in await db.fetchall("SELECT * FROM service_states ORDER BY id")]
    assert states == [("starting", T0, T0 + 5), ("ready", T0 + 5, T0 + 30), ("stopping", T0 + 30, T0 + 31), ("stopped", T0 + 31, None)]
    loads = [(x["from_ts"], x["to_ts"]) for x in await db.fetchall("SELECT * FROM load_intervals")]
    assert loads == [(T0 + 10, T0 + 30)]  # loaded until the unload finished
    jobs = [(x["job_id"], x["state"], x["start_ts"], x["end_ts"]) for x in await db.fetchall("SELECT * FROM job_history ORDER BY id")]
    assert jobs == [("j1", "done", T0 + 10, T0 + 20), ("j9", "failed", T0 + 20, T0 + 20)]


async def test_hub_downtime_is_a_gap_and_running_jobs_reopen(db, rec):
    a = FakeSvc("a", state="ready", load="loaded", jobs=[{"id": "j1", "label": "long", "state": "running", "progress": 0.2}])
    r1 = rec(a)
    await r1.recover()
    await r1.reconcile()
    await r1.tick(T0 + 20)  # heartbeat at T0+20, then the hub dies without closing anything
    # 10 minutes later a new hub starts; the mod kept running and still reports j1
    r2 = rec(a)
    r2.clock.t = T0 + 620
    await r2.recover()
    await r2.reconcile()
    states = [(x["state"], x["from_ts"], x["to_ts"]) for x in await db.fetchall("SELECT * FROM service_states ORDER BY id")]
    assert states == [("ready", T0, T0 + 20), ("ready", T0 + 620, None)]  # the gap: T0+20 … T0+620
    loads = [(x["from_ts"], x["to_ts"]) for x in await db.fetchall("SELECT * FROM load_intervals ORDER BY id")]
    assert loads == [(T0, T0 + 20), (T0 + 620, None)]
    jobs = [(x["job_id"], x["state"], x["start_ts"], x["end_ts"]) for x in await db.fetchall("SELECT * FROM job_history")]
    assert jobs == [("j1", "running", T0, None)]  # reopened, not duplicated
    # a clean stop closes rows at the stop time instead
    r2.clock.t = T0 + 700
    await r2.close()
    a.jobs = []
    r3 = rec(a)
    r3.clock.t = T0 + 900
    await r3.recover()
    await r3.reconcile()
    jobs = [(x["state"], x["end_ts"]) for x in await db.fetchall("SELECT * FROM job_history")]
    assert jobs == [("cancelled", T0 + 700)]  # gone after the restart: ended when the hub stopped
    states = [(x["from_ts"], x["to_ts"]) for x in await db.fetchall("SELECT * FROM service_states ORDER BY id")]
    assert states[1:] == [(T0 + 620, T0 + 700), (T0 + 900, None)]


async def test_resync_and_removed_mods(db, rec):
    a, b = FakeSvc("a"), FakeSvc("b")
    r = rec(a, b)
    await r.reconcile()
    del r.mgr.services["b"]
    a.state = "failed"
    r.clock.t = T0 + 50
    await r.on_event({"type": "resync"})
    rows = {(x["service"], x["state"]): x["to_ts"] for x in await db.fetchall("SELECT * FROM service_states")}
    assert rows == {("a", "ready"): T0 + 50, ("b", "ready"): T0 + 50, ("a", "failed"): None}


async def test_disk_alert(db, rec, monkeypatch, tmp_path):
    bus = EventBus()
    alerts = Alerts(bus)
    r = rec(FakeSvc("a"), disk_path=tmp_path, alerts=alerts)
    Usage = namedtuple("Usage", "total used free")
    free = {"v": 400 * GB}
    monkeypatch.setattr(recmod.shutil, "disk_usage", lambda p: Usage(1000 * GB, 0, free["v"]))
    r.check_disk()
    assert alerts.list() == []
    free["v"] = 42 * GB
    r.check_disk()
    assert alerts.list() == [{"id": "disk-low", "level": "warn", "text": "Disk space is low: 42.0 GB free", "action": {"label": "Outputs", "route": "#/outputs"}}]
    free["v"] = 5 * GB
    r.check_disk()
    assert alerts.list()[0]["level"] == "error"
    free["v"] = 52 * GB  # inside the hysteresis band: stays
    r.check_disk()
    assert alerts.list()
    free["v"] = 60 * GB
    r.check_disk()
    assert alerts.list() == []
