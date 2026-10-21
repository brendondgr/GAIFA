"""Plan 31.1: the `/api/gpu` routes on a real hub app."""

from __future__ import annotations

import asyncio


async def test_acquire_grant_wait_release(client):
    r = await client.post("/api/gpu/acquire", json={"service": "comfy", "class": "job", "label": "image", "est_s": 60})
    assert r.status_code == 200 and r.json()["state"] == "granted"
    first = r.json()["lease"]

    r = await client.post("/api/gpu/acquire", params={"wait": 0.05}, json={"service": "gen3d", "class": "job", "label": "model"})
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "waiting" and [a["service"] for a in body["ahead"]] == ["comfy"]
    assert body["ahead"][0]["eta_s"] is not None
    second = body["lease"]

    # repeating with the lease keeps its place
    r = await client.post("/api/gpu/acquire", json={"service": "gen3d", "class": "job", "label": "model", "lease": second})
    assert r.status_code == 202 and r.json()["lease"] == second

    g = (await client.get("/api/gpu")).json()
    assert g["queue"] is True and g["holder"]["group"] == "comfy"
    assert g["holder"]["leases"][0]["class"] == "job" and g["holder"]["leases"][0]["label"] == "image"
    assert [w["id"] for w in g["waiting"]] == [second]

    # a waiter is woken by the release
    waiter = asyncio.create_task(client.post("/api/gpu/acquire", params={"wait": 5},
                                             json={"service": "gen3d", "label": "model", "lease": second}))
    await asyncio.sleep(0.05)
    r = await client.post(f"/api/gpu/{first}/release")
    assert r.json()["state"] == "released"
    r = await asyncio.wait_for(waiter, 3)
    assert r.status_code == 200 and r.json()["state"] == "granted"

    assert (await client.post(f"/api/gpu/{second}/renew")).json()["state"] == "granted"
    await client.post(f"/api/gpu/{second}/release")
    g = (await client.get("/api/gpu")).json()
    assert g["holder"] is None and g["waiting"] == []
    assert [x["service"] for x in g["recent"]] == ["gen3d", "comfy"]
    assert g["recent"][1]["run_s"] >= 0 and "wait_s" in g["recent"][0]


async def test_cancel_and_errors(client):
    held = (await client.post("/api/gpu/acquire", json={"service": "comfy", "label": "image"})).json()["lease"]
    waiting = (await client.post("/api/gpu/acquire", json={"service": "tts", "label": "speech"})).json()["lease"]
    r = await client.delete(f"/api/gpu/{waiting}")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    r = await client.delete(f"/api/gpu/{held}")
    assert r.status_code == 409 and r.json()["code"] == "gpu_lease_held"
    r = await client.delete("/api/gpu/gl_000000000000")
    assert r.status_code == 404 and r.json()["code"] == "gpu_lease_unknown"
    assert (await client.post("/api/gpu/gl_000000000000/release")).json()["state"] == "unknown"
    assert (await client.post("/api/gpu/gl_000000000000/renew")).status_code == 404
    r = await client.post("/api/gpu/acquire", json={"service": "x", "class": "urgent"})
    assert r.status_code == 422


async def test_renew_re_registers_an_unknown_lease(client):
    r = await client.post("/api/gpu/gl_aaaaaaaaaaaa/renew", json={"service": "comfy", "class": "job", "label": "image"})
    assert r.status_code == 200 and r.json()["state"] == "granted"
    r = await client.post("/api/gpu/gl_bbbbbbbbbbbb/renew", json={"service": "gen3d", "class": "job", "label": "model"})
    assert r.status_code == 202 and r.json()["state"] == "waiting"


async def test_events_on_the_bus(app, client):
    sub = app.state.hub.bus.subscribe()
    lease = (await client.post("/api/gpu/acquire", json={"service": "comfy", "label": "image"})).json()["lease"]
    await client.post(f"/api/gpu/{lease}/release")
    seen = []
    while not sub.queue.empty():
        ev = sub.queue.get_nowait()
        if ev["type"] == "gpu":
            seen.append(ev["event"])
    assert seen == ["granted", "released"]


async def test_metrics_record_wait_and_hold(app, client):
    lease = (await client.post("/api/gpu/acquire", json={"service": "comfy", "label": "image"})).json()["lease"]
    await client.post(f"/api/gpu/{lease}/release")
    names = {info.name for info, _ in app.state.hub.metrics.gpu_samples()}
    assert {"gpu.waiting", "gpu.wait.comfy", "gpu.hold.comfy"} <= names


async def test_queue_off(make_app, root):
    import httpx

    (root / "config.toml").write_text("[gpu]\nqueue = false\n")
    app = make_app(port=7000)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            for svc in ("comfy", "gen3d"):
                r = await c.post("/api/gpu/acquire", json={"service": svc, "label": "x"})
                assert r.status_code == 200 and r.json()["state"] == "granted"
            assert (await c.get("/api/gpu")).json()["queue"] is False
