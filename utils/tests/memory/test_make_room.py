"""5.4: loading with make-room, end to end with two real fake-mem mods (40 GB each in a
68 GB budget): needs_room with the plan, Unload & continue, auto_make_room, never_unload,
busy mods, acquire, and two loads racing for the same memory."""

from __future__ import annotations

import asyncio

from utils.tests.memory.conftest import GB, loaded
from utils.tests.services.conftest import until


async def test_needs_room_then_unload_and_continue(memhub):
    async with memhub() as (app, c, src):
        hub = app.state.hub
        r = await c.post("/api/services/fake-mem/load")
        assert r.status_code == 202 and r.json()["load"] == "loading"
        await loaded(app, "fake-mem")
        await until(lambda: hub.memory.used.get("fake-mem") == 40 * GB)
        # the second doesn't fit: 409 with the plan, and nothing changes
        r = await c.post("/api/services/fake-mem2/load")
        assert r.status_code == 409 and r.json()["code"] == "needs_room"
        plan = r.json()["data"]["plan"]
        assert plan["service"] == "fake-mem2" and plan["needs_bytes"] == 40 * GB and plan["available_bytes"] == 28 * GB
        assert [u["id"] for u in plan["unload"]] == ["fake-mem"] and plan["unload"][0]["frees_bytes"] == 40 * GB and plan["enough"]
        assert r.json()["detail"] == "Loading Fake Memory 2 needs ~40.0 GB, 28.0 GB available. Unloading fake-mem makes room."
        assert hub.services.get("fake-mem").load == "loaded" and hub.services.get("fake-mem2").load == "unloaded"
        assert (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json() == plan
        # "Unload & continue"
        sub = hub.bus.subscribe()
        r = await c.post("/api/services/fake-mem2/load", params={"make_room": 1})
        assert r.status_code == 202
        await loaded(app, "fake-mem2")
        assert hub.services.get("fake-mem").load == "unloaded"
        await until(lambda: any(a["text"].startswith("Loaded Fake Memory 2") for a in hub.activity.recent(10)))
        texts = [a["text"] for a in hub.activity.recent(10)]
        assert any(t.startswith("Unloaded Fake Memory to make room for Fake Memory 2") for t in texts)
        await until(lambda: hub.memory.used == {"fake-mem2": 40 * GB})
        events = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
        mems = [e["memory"] for e in events if e["type"] == "memory"]
        assert mems and {r["id"]: r["load"] for r in mems[-1]["by_service"]} == {"fake-mem": "unloaded", "fake-mem2": "loaded"}
        m = (await c.get("/api/memory")).json()
        assert m["available_bytes"] == 40 * GB and m["reserve_bytes"] == 12 * GB and m["other_bytes"] == 20 * GB
        assert {r["id"]: r["used_bytes"] for r in m["by_service"]} == {"fake-mem": 0, "fake-mem2": 40 * GB}
        s = (await c.get("/api/services/fake-mem2")).json()["memory"]
        assert s == {"used_bytes": 40 * GB, "estimate_bytes": 40 * GB, "peak_bytes": 40 * GB}


async def test_auto_make_room(memhub):
    async with memhub(config="[memory]\nauto_make_room = true\n") as (app, c, src):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        assert (await c.post("/api/services/fake-mem2/load")).status_code == 202
        await loaded(app, "fake-mem2")
        assert app.state.hub.services.get("fake-mem").load == "unloaded"


async def test_never_unload_mods_stay(memhub):
    async with memhub(config='[memory]\nnever_unload = ["fake-mem"]\n') as (app, c, src):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        r = await c.post("/api/services/fake-mem2/load", params={"make_room": 1})
        assert r.status_code == 409 and r.json()["data"]["plan"]["unload"] == [] and not r.json()["data"]["plan"]["enough"]
        assert app.state.hub.services.get("fake-mem").load == "loaded"


async def test_busy_mods_stay(memhub):
    async with memhub() as (app, c, src):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        svc = app.state.hub.services.get("fake-mem")
        svc.in_flight = 1  # a proxied request is running
        plan = (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json()
        assert plan["unload"] == [] and not plan["enough"]
        svc.in_flight, svc.busy = 0, True  # its status says busy
        assert (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json()["unload"] == []
        svc.busy = False
        assert [u["id"] for u in (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json()["unload"]] == ["fake-mem"]


async def test_acquire(memhub):
    async with memhub() as (app, c, src):
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem2", "needs_bytes": 10 * GB, "reason": "gemma-4"})
        assert r.status_code == 200 and r.json()["granted"] and r.json()["freed"] == []
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        app.state.hub.memory.reservations.clear()
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem2", "needs_bytes": 50 * GB})
        assert r.status_code == 409 and r.json()["code"] == "needs_room"
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem2", "needs_bytes": 50 * GB, "reason": "big model"},
                         headers={"X-AIHub-Make-Room": "1"})
        assert r.status_code == 200 and r.json() == {**r.json(), "granted": True, "freed": ["fake-mem"]}
        assert app.state.hub.services.get("fake-mem").load == "unloaded"
        assert any(a["text"] == "Made room for Fake Memory 2 (big model)" for a in app.state.hub.activity.recent(5))
        # the grant is reserved: another mod can't plan with the same memory
        assert app.state.hub.memory.reserved() == 50 * GB
        plan = (await c.post("/api/memory/plan", json={"service": "fake-mem"})).json()
        assert plan["available_bytes"] == 68 * GB - 50 * GB and not plan["enough"]
        r = await c.post("/api/memory/acquire", json={"service": "nope", "needs_bytes": 1})
        assert r.status_code == 404 and r.json()["code"] == "service_not_found"


async def test_two_loads_never_take_the_same_memory(memhub):
    async with memhub() as (app, c, src):
        src.base = 40 * GB  # 100 − 40 − 12 = 48 GB: room for one of them
        hub = app.state.hub
        await hub.memory.sample()
        mgr = hub.services
        both: list[bool] = []

        async def watch() -> None:
            while True:
                both.append(mgr.get("fake-mem").load == mgr.get("fake-mem2").load == "loaded")
                await asyncio.sleep(0.005)

        w = asyncio.create_task(watch())
        a, b = await asyncio.gather(c.post("/api/services/fake-mem/load"), c.post("/api/services/fake-mem2/load"))
        # Whichever plans second sees the first's reservation: refused at once (409), or, if both
        # prechecks ran first, its load fails in the background. Never both loaded.
        assert sorted([a.status_code, b.status_code]) in ([202, 202], [202, 409])
        await until(lambda: {mgr.get("fake-mem").load, mgr.get("fake-mem2").load} == {"loaded", "unloaded"}, timeout=10)
        await asyncio.sleep(0.3)
        w.cancel()
        assert not any(both)
        if a.status_code == b.status_code == 202:
            failed = next(s for s in ("fake-mem", "fake-mem2") if mgr.get(s).load == "unloaded")
            await until(lambda: any(x["text"].startswith(f"Couldn't load {mgr.get(failed).mod.name}: Loading") for x in hub.activity.recent(10)))


async def test_unload_that_does_not_free_memory_is_reported(memhub):
    async with memhub() as (app, c, src):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        src.sizes["fake-mem"], src.extra["fake-mem"] = 0, 40 * GB  # it keeps holding its memory after unloading
        app.state.hub.memory.wait_s = 0.3
        r = await c.post("/api/services/fake-mem2/load", params={"make_room": 1})
        assert r.status_code == 202
        await loaded(app, "fake-mem2", "unloaded")
        texts = [a["text"] for a in app.state.hub.activity.recent(10)]
        assert any("didn't drop by the expected 40.0 GB" in t for t in texts)
        assert any(t.startswith("Couldn't load Fake Memory 2") for t in texts)
