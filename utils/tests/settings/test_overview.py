"""6.3: GET /api/overview aggregates what the Overview page shows first."""

from __future__ import annotations

import httpx

from utils.tests.services.conftest import ready, until


async def test_overview(rig, serve):
    rig.add("fake-ok")
    served = await serve()
    await ready(served, "fake-ok")
    hub = served.hub
    async with httpx.AsyncClient(base_url=served.url) as c:
        for i in range(10):
            await c.post("/api/s/fake-ok/v1/outputs", json={"text": f"note {i}"})
        await c.post("/api/s/fake-ok/v1/jobs", json={"label": "slow", "seconds": 30})
        await until(lambda: hub.db.fetchone_sync("SELECT COUNT(*) AS n FROM outputs")["n"] == 10, timeout=10)
        await until(lambda: hub.services.get("fake-ok").jobs, timeout=10)
        for i in range(40):
            await hub.activity.add(f"item {i}")
        hub.alerts.set("x", "warn", "Something")
        r = await c.get("/api/overview")
        assert r.status_code == 200
        ov = r.json()
        assert set(ov) == {"services", "memory", "recent_outputs", "activity", "alerts", "jobs", "system"}
        assert [s["id"] for s in ov["services"]] == ["fake-ok"] and ov["services"][0]["state"] == "ready"
        assert len(ov["recent_outputs"]) == 8 and ov["recent_outputs"][0]["title"].startswith("note")
        assert len(ov["activity"]) == 30 and ov["activity"][0]["text"] == "item 39"
        assert {"id": "x", "level": "warn", "text": "Something"} in ov["alerts"]
        assert [(j["label"], j["service"]) for j in ov["jobs"]] == [("slow", "fake-ok")]
        assert ov["memory"]["total_bytes"] > 0 and ov["system"]["hub"]["port"] == hub.port
