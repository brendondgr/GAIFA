"""5.5: a proxied call that loads a mod's models makes room first, or returns needs_room;
the caller retries with X-GAIFA-Make-Room: 1."""

from __future__ import annotations

from utils.tests.memory.conftest import loaded


async def test_trigger_needs_room_then_retry(memhub):
    async with memhub(triggers=True) as (app, c, src):
        hub = app.state.hub
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        r = await c.post("/api/s/fake-mem2/v1/load", json={"mb": 8})
        assert r.status_code == 409 and r.headers["x-gaifa-error"] == "needs_room"
        assert [u["id"] for u in r.json()["data"]["plan"]["unload"]] == ["fake-mem"]
        assert hub.services.get("fake-mem").load == "loaded"
        r = await c.post("/api/s/fake-mem2/v1/load", json={"mb": 8}, headers={"X-GAIFA-Make-Room": "1"})
        assert r.status_code == 200 and r.json() == {"loaded": True, "mb": 8}  # the mod's own answer
        assert hub.services.get("fake-mem").load == "unloaded"
        await loaded(app, "fake-mem2")  # its status says so on the next poll
        assert "fake-mem2" in hub.memory.reservations


async def test_non_trigger_calls_and_loaded_mods_pass_straight_through(memhub):
    async with memhub(triggers=True) as (app, c, src):
        r = await c.post("/api/s/fake-mem2/v1/load", json={"mb": 1})
        assert r.status_code == 200  # enough room: nothing to plan
        await loaded(app, "fake-mem2")
        app.state.hub.memory.reservations.clear()
        await c.post("/api/services/fake-mem/load", params={"make_room": 1})  # unloads fake-mem2 for it
        await loaded(app, "fake-mem")
        assert app.state.hub.services.get("fake-mem2").load == "unloaded"
        assert (await c.get("/api/s/fake-mem2/v1/status")).status_code == 200  # not a trigger: no room needed
        assert (await c.post("/api/s/fake-mem/v1/load", json={"mb": 1})).status_code == 200  # fake-mem has no triggers


async def test_a_mod_with_a_request_in_flight_is_never_unloaded(memhub):
    async with memhub(triggers=True) as (app, c, src):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        app.state.hub.services.get("fake-mem").in_flight = 1
        r = await c.post("/api/s/fake-mem2/v1/load", json={"mb": 8}, headers={"X-GAIFA-Make-Room": "1"})
        assert r.status_code == 409 and r.json()["data"]["plan"]["unload"] == []
        assert app.state.hub.services.get("fake-mem").load == "loaded"
        app.state.hub.services.get("fake-mem").in_flight = 0


async def test_a_gpu_mod_gets_its_room_at_its_gpu_turn():
    """Plan 31: a mod that takes the GPU slot and would wait for it gets the check now and the room (unloads and
    the reservation) when its lease is granted; with the slot free, the room comes at once as before."""
    from types import SimpleNamespace

    from utils.config import GpuCfg
    from utils.events import Alerts, EventBus
    from utils.gpu import GpuQueue
    from utils.memory.triggers import hook

    calls: list[tuple[str, str, bool]] = []
    svc = SimpleNamespace(id="gen3d", load="unloaded",
                          m=SimpleNamespace(memory=SimpleNamespace(triggers=["POST /v1/jobs"]), gpu=SimpleNamespace(group=None)))

    class Mem:
        mgr = SimpleNamespace(get=lambda sid: svc)

        async def precheck(self, sid, make_room=False):
            calls.append(("check", sid, make_room))

        async def ensure_room(self, sid, make_room=False, ttl=0.0):
            calls.append(("room", sid, make_room))

    bus = EventBus()
    q = GpuQueue(bus, Alerts(bus), cfg=GpuCfg)
    before = hook(Mem(), lambda: q)
    comfy = q.register("comfy", "job", "video")                     # holds the slot
    await before(svc, "POST", "/v1/jobs", {"x-gaifa-make-room": "1"})
    assert calls == [("check", "gen3d", True)]                       # nothing unloaded or reserved while it waits
    lease = q.register("gen3d", "job", "a model")
    assert lease.state == "waiting"
    q.release(comfy.id)
    assert lease.state == "held"
    await q.granted(lease)
    assert calls[-1] == ("room", "gen3d", True)
    await q.granted(lease)                                           # once
    assert len(calls) == 2
    q.release(lease.id)
    await before(svc, "POST", "/v1/jobs", {})                        # a free slot: the room at once
    assert calls[-1] == ("room", "gen3d", False) and len(calls) == 3
