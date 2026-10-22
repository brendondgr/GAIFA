"""5.2: the sampler: the Memory shape, events only when something moves, learned peaks, and the 92% alert."""

from __future__ import annotations

import pytest

from utils.memory.manager import ALERT, PUBLISH_EVERY_S
from utils.tests.memory.conftest import GB, loaded


def mem_events(sub) -> list[dict]:
    return [e["memory"] for e in [sub.queue.get_nowait() for _ in range(sub.queue.qsize())] if e["type"] == "memory"]


async def test_shape_and_other(memhub):
    async with memhub(config="[memory]\nreserve_gb = 8\n") as (app, c, src):
        m = (await c.get("/api/memory")).json()
        assert m == {
            "total_bytes": 100 * GB, "used_bytes": 20 * GB, "available_bytes": 80 * GB, "reserve_bytes": 8 * GB, "gpu": None,
            "by_service": [
                {"id": "fake-mem", "used_bytes": 0, "estimate_bytes": 40 * GB, "load": "unloaded", "idle_s": m["by_service"][0]["idle_s"], "auto_unload": True, "priority": 100},
                {"id": "fake-mem2", "used_bytes": 0, "estimate_bytes": 40 * GB, "load": "unloaded", "idle_s": m["by_service"][1]["idle_s"], "auto_unload": True, "priority": 100},
            ],
            "other_bytes": 20 * GB,
            "pools": [{"id": "system", "name": "System memory", "total_bytes": 100 * GB, "used_bytes": 20 * GB, "available_bytes": 80 * GB}],
        }


async def test_events_only_when_something_moves(memhub, monkeypatch):
    async with memhub(start=False) as (app, c, src):
        mem = app.state.hub.memory
        await mem.close()  # drive sampling by hand
        sub = app.state.hub.bus.subscribe()
        await mem.sample()
        assert mem_events(sub) == []  # nothing moved since start()
        src.base += int(0.5 * GB)  # 0.5% of 100 GB
        await mem.sample()
        assert mem_events(sub) == []
        src.base += int(0.6 * GB)  # now 1.1% from the last published
        await mem.sample()
        assert [e["used_bytes"] for e in mem_events(sub)] == [int(21.1 * GB)]
        monkeypatch.setattr("utils.memory.manager.time.monotonic", lambda real=__import__("time").monotonic: real() + PUBLISH_EVERY_S + 1)
        await mem.sample()
        assert len(mem_events(sub)) == 1  # every 10 s regardless


async def test_peaks_are_learned_while_loaded(memhub):
    async with memhub() as (app, c, src):
        hub = app.state.hub
        src.extra["fake-mem"] = 5 * GB  # measured while unloaded: not a peak
        await hub.memory.sample()
        assert "fake-mem" not in hub.memory.peaks
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        await hub.memory.sample()
        assert hub.memory.peaks["fake-mem"] == 45 * GB
        rows = await hub.db.fetchall("SELECT service, peak_bytes FROM service_peaks")
        assert {r["service"]: r["peak_bytes"] for r in rows} == {"fake-mem": 45 * GB}
        # a bigger learned peak raises what a load needs
        src.sizes["fake-mem2"] = 50 * GB
        await c.post("/api/services/fake-mem/unload")
        await loaded(app, "fake-mem", "unloaded")
        await c.post("/api/services/fake-mem2/load")
        await loaded(app, "fake-mem2")
        await hub.memory.sample()
        plan = (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json()
        assert plan["needs_bytes"] == 50 * GB


async def test_an_old_peak_stops_counting_and_a_new_load_learns_a_fresh_one(memhub):
    """Overnight 2026-10-21: peaks only grew, so a mod's worst load from weeks ago (tts 27 GB, comfy 74 GB)
    kept blocking today's small loads. Past `[memory] peak_days` a peak stops counting."""
    import time

    async with memhub() as (app, c, src):
        m = app.state.hub.memory
        m.peaks["fake-mem"], m.peak_ts["fake-mem"] = 90 * GB, time.time() - 8 * 86400   # eight days old
        svc = app.state.hub.services.get("fake-mem")
        assert m.fresh_peak("fake-mem") == 0 and m.needs(svc) == (m.estimate(svc) or 0)
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        await m.sample()                                   # today's measurement replaces the stale 90 GB
        today = m.used["fake-mem"]
        assert 0 < today < 90 * GB and m.peaks["fake-mem"] == today and m.fresh_peak("fake-mem") == today
        m.peak_ts["fake-mem"] = time.time() - 3 * 86400    # a recent peak still counts
        assert m.needs(svc) == max(m.estimate(svc) or 0, today)


async def test_high_memory_alert(memhub):
    async with memhub(start=False) as (app, c, src):
        hub = app.state.hub
        alerts = lambda: {a["id"]: a for a in hub.alerts.list()}  # noqa: E731
        src.base = 93 * GB
        await hub.memory.sample()
        assert alerts()[ALERT]["text"] == "Memory is 93% full (93.0 GB of 100.0 GB)" and alerts()[ALERT]["level"] == "warn"
        src.base = 91 * GB  # between 90 and 92: stays
        await hub.memory.sample()
        assert ALERT in alerts()
        src.base = 89 * GB
        await hub.memory.sample()
        assert ALERT not in alerts()


@pytest.mark.parametrize("path,hit", [
    ("/v1/load", True), ("/v1/load/", True), ("/v1/loads", False), ("/v1/items/42/run", True),
    ("/v1/items/42/x/run", False), ("/v1/items//run", False),
])
def test_trigger_matching(path, hit, rig):
    from utils import manifest as mf
    from utils.memory.triggers import matches

    class S:
        m = mf.Manifest.model_validate({"id": "xx", "run": {"command": ["x"], "port": 1}, "memory": {
            "triggers": ["POST /v1/load", "POST /v1/items/{id}/run", "GET /v1/files/*"]}})

    assert matches(S, "POST", path) is hit
    assert matches(S, "GET", "/v1/load") is False
    assert matches(S, "GET", "/v1/files/a/b.wav") is True
