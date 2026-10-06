"""6.2: the chart data routes and mod widgets, against a hub running fake-ok."""

from __future__ import annotations

import time

import httpx

from utils.tests.services.conftest import ready, until


async def _hub(rig, serve, *mods, **opts):
    for m in mods:
        rig.add(m)
    served = await serve(**opts)
    await ready(served, *mods)
    return served


async def test_metrics_series_and_stats(rig, serve):
    served = await _hub(rig, serve, "fake-ok")
    hub = served.hub
    async with httpx.AsyncClient(base_url=served.url) as c:
        await c.post("/api/s/fake-ok/v1/echo", json={})
        await until(lambda: hub.services.get("fake-ok").stats and hub.services.get("fake-ok").stats[0]["value"] >= 1)
        await until(lambda: hub.memory.snapshot is not None)     # the tick records what the sampler last saw
        # The axis ends at the last complete 10 s bucket: record into one it surely has (a tick in a
        # bucket that began a moment ago fell outside it; this was the suite's intermittent failure).
        await hub.metrics.tick(ts=time.time() - 10)
        r = await c.get("/api/metrics", params={"series": "mem.used,svc.fake-ok.stat.*,nope", "range": "1h"})
        assert r.status_code == 200
        m = r.json()
        assert m["range"] == "1h" and m["step_s"] == 10 and len(m["t"]) in (360, 361)
        assert all(b - a == 10 for a, b in zip(m["t"], m["t"][1:]))
        assert set(m["series"]) == {"mem.used", "svc.fake-ok.stat.requests", "svc.fake-ok.stat.outputs_today", "nope"}
        last = lambda vals: [v for v in vals if v is not None][-1]  # noqa: E731  (the newest recorded value)
        assert last(m["series"]["mem.used"]) > 0 and last(m["series"]["svc.fake-ok.stat.requests"]) >= 1
        assert m["series"]["nope"] == [None] * len(m["t"])
        assert all(len(v) == len(m["t"]) for v in m["series"].values())
        # longer ranges read the rollups, on their own axis
        m = (await c.get("/api/metrics", params={"series": "mem.used", "range": "7d"})).json()
        assert m["step_s"] == 1800 and len(m["t"]) in (336, 337)
        series = {s["name"]: s for s in (await c.get("/api/metrics/series")).json()}
        assert series["svc.fake-ok.stat.outputs_today"] == {"name": "svc.fake-ok.stat.outputs_today", "label": "Outputs today",
                                                             "unit": "count", "service": "fake-ok", "reset": "daily"}
        assert series["mem.used"] == {"name": "mem.used", "label": "Memory used", "unit": "bytes"}
        # stats name their series, for sparklines
        stats = (await c.get("/api/services/fake-ok")).json()["stats"]
        assert stats[0]["series"] == "svc.fake-ok.stat.requests"
        for bad in ({"series": "mem.used", "range": "1y"}, {"series": " , ", "range": "1h"}, {"range": "1h"}):
            r = await c.get("/api/metrics", params=bad)
            assert r.status_code == 422 and r.json()["code"] == "invalid_request"


async def test_timeline_and_stats(rig, serve):
    served = await _hub(rig, serve, "fake-ok")
    hub = served.hub
    async with httpx.AsyncClient(base_url=served.url) as c:
        await c.post("/api/s/fake-ok/v1/jobs", json={"label": "fox", "seconds": 0.3})
        await c.post("/api/s/fake-ok/v1/outputs", json={"text": "hello there"})
        await hub.activity.add("fake-ok had a hiccup", service="fake-ok", level="warn")
        await hub.activity.add("fake-ok broke", service="fake-ok", level="error")
        rows = lambda: hub.db.fetchall_sync("SELECT * FROM job_history WHERE end_ts IS NOT NULL")  # noqa: E731
        await until(lambda: rows(), timeout=10)
        await until(lambda: hub.db.fetchall_sync("SELECT * FROM outputs"), timeout=10)
        tl = (await c.get("/api/timeline", params={"range": "1h"})).json()
        assert tl["to"] - tl["from"] == 3600
        lane = next(x for x in tl["lanes"] if x["service"] == "fake-ok")
        assert [s["state"] for s in lane["states"]][-1] == "ready" and lane["states"][-1]["to"] == tl["to"]
        assert [(j["label"], j["state"]) for j in lane["jobs"]] == [("fox", "done")] and lane["jobs"][0]["to"] >= lane["jobs"][0]["from"]
        assert [o["kind"] for o in lane["outputs"]] == ["text"]
        assert [(e["level"], e["text"]) for e in lane["events"]] == [("warn", "fake-ok had a hiccup"), ("error", "fake-ok broke")]
        assert lane["loaded"] == []  # fake-ok has no models
        only = (await c.get("/api/timeline", params={"services": "nope"})).json()
        assert [x["service"] for x in only["lanes"]] == ["nope"] and only["lanes"][0]["states"] == []

        day = time.strftime("%Y-%m-%d")
        b = (await c.get("/api/outputs/stats")).json()["buckets"]
        assert len(b) in (30, 31) and b[-1]["key"] == day and b[-1]["count"] == 1 and b[-1]["by_kind"] == {"text": 1}
        assert b[-1]["size_bytes"] > 0 and all(x["count"] == 0 for x in b[:-1])
        assert (await c.get("/api/outputs/stats", params={"by": "service"})).json()["buckets"][0]["key"] == "fake-ok"
        assert (await c.get("/api/outputs/stats", params={"by": "kind"})).json()["buckets"][0]["key"] == "text"
        assert (await c.get("/api/outputs/stats", params={"by": "week"})).status_code == 422

        cells = (await c.get("/api/activity/stats")).json()["cells"]
        assert len(cells) in (14 * 24, 15 * 24)
        now = next(x for x in cells if x["day"] == day and x["hour"] == time.localtime().tm_hour)
        assert now["count"] >= 2 and now["errors"] == 1

        js = (await c.get("/api/jobs/stats")).json()["by_service"]
        assert js == [{"service": "fake-ok", "count": 1, "failed": 0, "p50_s": js[0]["p50_s"], "p90_s": js[0]["p90_s"], "max_s": js[0]["max_s"]}]
        assert 0 < js[0]["p50_s"] == js[0]["max_s"] < 10


async def test_widgets(rig, serve):
    served = await _hub(rig, serve, "fake-ok")
    async with httpx.AsyncClient(base_url=served.url) as c:
        assert (await c.get("/api/widgets")).json() == [
            {"service": "fake-ok", "id": "requests", "title": "Requests", "kind": "bar", "ranges": ["24h", "7d"], "span": 6}]
        r = await c.get("/api/widgets/fake-ok/requests")
        assert r.status_code == 200
        d = r.json()
        assert d["unit"] == "requests" and len(d["t"]) == 24 and [s["name"] for s in d["series"]] == ["Requests", "Calls"]
        assert d["series"][1]["axis"] == "right" and d["series"][1]["values"][0] == 1
        # cached for 30 s: the mod isn't asked again
        assert (await c.get("/api/widgets/fake-ok/requests")).json()["series"][1]["values"][0] == 1
        d7 = (await c.get("/api/widgets/fake-ok/requests", params={"range": "7d"})).json()
        assert len(d7["t"]) == 7 and d7["series"][1]["values"][0] == 2  # another range: another call
        r = await c.get("/api/widgets/fake-ok/requests", params={"range": "30d"})
        assert r.status_code == 422 and "offers 24h, 7d" in r.json()["detail"]
        assert (await c.get("/api/widgets/fake-ok/nope")).json()["code"] == "widget_not_found"
        assert (await c.get("/api/widgets/nope/requests")).json()["code"] == "service_not_found"
        served.hub.widgets._cache.clear()
        await c.post("/api/services/fake-ok/stop", params={"wait": 1})
        assert (await c.get("/api/widgets")).json() == []  # only running mods
        r = await c.get("/api/widgets/fake-ok/requests")
        assert r.status_code == 503 and r.json()["code"] == "service_not_running"


async def test_widget_with_bad_data(rig, serve):
    rig.add("fake-ok", edit={"env": '{ FAKE_PORT = "{port}", FAKE_OUTPUTS = "{outputs}", FAKE_BAD_WIDGET = "1" }'})
    served = await serve()
    await ready(served, "fake-ok")
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.get("/api/widgets/fake-ok/requests")
        assert r.status_code == 502 and r.json()["code"] == "widget_invalid"
        assert "values must be numbers or null" in r.json()["detail"]
