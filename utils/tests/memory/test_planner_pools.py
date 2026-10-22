"""36.2: making room per pool. A machine with one 24 GB card: two mods of 20 GB VRAM each (4 GB of
RAM), so the GPU, not the RAM, is what's short; plus the planner's rules on their own."""

from __future__ import annotations

import contextlib

import httpx

from utils.memory.planner import Candidate, extend_plan, make_plan
from utils.memory.pools import Pool
from utils.tests.conftest import free_port
from utils.tests.memory.conftest import GB, FakeSource, loaded
from utils.tests.services.conftest import FAST, until


class GpuSource(FakeSource):
    """FakeSource plus dedicated cards: a loaded mod holds `vram[id]` on its card (`on[id]`, default gpu:0)."""

    def __init__(self, cards: dict[str, int], vram: dict[str, int], on: dict[str, str] | None = None, **kw) -> None:
        super().__init__(**kw)
        self.cards, self.vram_sizes, self.on = cards, vram, on or {}

    def pools(self, pids):
        use: dict[str, dict[str, int]] = {}
        for s in self.mgr.list() if self.mgr else []:
            if s.load in ("loaded", "unloading") and self.vram_sizes.get(s.id):
                use[s.id] = {self.on.get(s.id, "gpu:0"): self.vram_sizes[s.id]}
        out = []
        for pid, total in self.cards.items():
            used = sum(v.get(pid, 0) for v in use.values())
            out.append(Pool(pid, f"Card {pid[-1]}", total, used, total - used))
        return out, use

    def pool_available(self, pool):
        return next((p.available_bytes for p in self.pools({})[0] if p.id == pool), None)


async def _start(app, c):
    for sid in ("fake-mem", "fake-mem2"):
        assert (await c.post(f"/api/services/{sid}/start", params={"wait": 1})).json()["state"] == "ready"


@contextlib.asynccontextmanager
async def gpu_rig(rig, make_app, src, config: str = ""):
    env = '{ FAKE_PORT = "{port}", FAKE_OUTPUTS = "{outputs}", FAKE_ESTIMATE_GB = "4" }'
    for sid in ("fake-mem", "fake-mem2"):
        rig.add("fake-mem", as_id=sid if sid != "fake-mem" else None,
                edit={"estimate_gb": "4\nvram_gb = 20", "env": env, **({"name": '"Fake Memory 2"'} if sid == "fake-mem2" else {})})
    rig.config(config)
    rig.write_config()
    app = make_app(backend=rig.backend, port=free_port(), autostart=False)
    hub = app.state.hub
    hub.timing = FAST
    hub.memory_source = src
    hub.memory_every_s = 0.05
    async with app.router.lifespan_context(app):
        hub.memory.wait_s, hub.memory.poll_s = 3.0, 0.02
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            await _start(app, c)
            yield app, c
            for sid in ("fake-mem", "fake-mem2"):
                await c.post(f"/api/services/{sid}/stop", params={"wait": 1})


def two_mods(cards=None, on=None) -> GpuSource:
    return GpuSource(cards or {"gpu:0": 24 * GB}, {"fake-mem": 20 * GB, "fake-mem2": 20 * GB}, on=on,
                     sizes={"fake-mem": 4 * GB, "fake-mem2": 4 * GB})


async def test_a_vram_gap_unloads_the_other_gpu_mod(rig, make_app):
    async with gpu_rig(rig, make_app, two_mods()) as (app, c):
        hub = app.state.hub
        assert (await c.post("/api/services/fake-mem/load")).status_code == 202
        await loaded(app, "fake-mem")
        await until(lambda: hub.memory.vram.get("fake-mem") == {"gpu:0": 20 * GB})
        m = (await c.get("/api/memory")).json()
        assert [p["id"] for p in m["pools"]] == ["system", "gpu:0"] and m["pools"][1]["used_bytes"] == 20 * GB
        assert {r["id"]: r["vram_bytes"] for r in m["by_service"]} == {"fake-mem": 20 * GB, "fake-mem2": 0}
        r = await c.post("/api/services/fake-mem2/load")
        assert r.status_code == 409
        plan = r.json()["data"]["plan"]
        assert plan["pool"] == "gpu:0" and plan["enough"]
        assert plan["pools"] == [{"pool": "system", "name": "system memory", "needs_bytes": 4 * GB, "available_bytes": 64 * GB, "enough": True},
                                 {"pool": "gpu:0", "name": "Card 0", "needs_bytes": 20 * GB, "available_bytes": 4 * GB, "enough": True}]
        assert plan["unload"] == [{"id": "fake-mem", "frees_bytes": 20 * GB, "reason": plan["unload"][0]["reason"], "pool": "gpu:0"}]
        assert r.json()["detail"] == "Loading Fake Memory 2 needs ~20.0 GB on Card 0, 4.0 GB free there. Unloading fake-mem makes room."
        assert (await c.post("/api/services/fake-mem2/load", params={"make_room": 1})).status_code == 202
        await loaded(app, "fake-mem2")
        assert hub.services.get("fake-mem").load == "unloaded"
        await until(lambda: hub.memory.peaks.get("fake-mem2@gpu") == 20 * GB)      # the VRAM peak, apart from RAM's
        assert hub.memory.peaks.get("fake-mem2") == 4 * GB


async def test_each_card_is_its_own_pool(rig, make_app):
    src = two_mods(cards={"gpu:0": 24 * GB, "gpu:1": 24 * GB}, on={"fake-mem": "gpu:0", "fake-mem2": "gpu:1"})
    async with gpu_rig(rig, make_app, src) as (app, c):
        await c.post("/api/services/fake-mem/load")
        await loaded(app, "fake-mem")
        await until(lambda: app.state.hub.memory.vram.get("fake-mem") == {"gpu:0": 20 * GB})
        plan = (await c.post("/api/memory/plan", json={"service": "fake-mem2"})).json()
        assert plan["pool"] == "system" and plan["enough"] and not plan["unload"]       # the freest card: gpu:1
        assert plan["pools"][1]["pool"] == "gpu:1"
        plan = (await c.post("/api/memory/plan", json={"service": "fake-mem2", "device": 0})).json()
        assert plan["pool"] == "gpu:0" and [u["id"] for u in plan["unload"]] == ["fake-mem"]


async def test_acquire_vram_and_reservations(rig, make_app):
    async with gpu_rig(rig, make_app, two_mods()) as (app, c):
        mem = app.state.hub.memory
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem", "needs_bytes": 1 * GB, "vram_bytes": 15 * GB})
        assert r.status_code == 200 and r.json()["plan"]["pools"][1]["needs_bytes"] == 15 * GB
        assert mem.reserved_vram("gpu:0") == 15 * GB
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem2", "needs_bytes": 1 * GB, "vram_bytes": 15 * GB})
        assert r.status_code == 409 and r.json()["data"]["plan"]["pool"] == "gpu:0"      # fake-mem's 15 GB is spoken for


async def test_one_pool_counts_vram_as_system_memory(memhub):
    async with memhub() as (app, c, src):          # 68 GB to load into
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem", "needs_bytes": 30 * GB, "vram_bytes": 30 * GB})
        assert r.status_code == 200 and r.json()["plan"]["needs_bytes"] == 60 * GB and r.json()["plan"]["pools"][0]["pool"] == "system"
        assert len(r.json()["plan"]["pools"]) == 1
        r = await c.post("/api/memory/acquire", json={"service": "fake-mem2", "needs_bytes": 5 * GB, "vram_bytes": 5 * GB})
        assert r.status_code == 409 and r.json()["data"]["plan"]["pool"] == "system"


def cand(id_, prio=100, idle=10.0, used=0) -> Candidate:
    return Candidate(id=id_, name=id_, load="loaded", up=True, busy=False, in_flight=0, auto_unload=True, unloadable=True,
                     priority=prio, idle_s=idle, used_bytes=used, estimate_bytes=None)


def test_extend_plan_rules():
    cs = [cand("a", 1, used=1 * GB), cand("b", 2, used=1 * GB), cand("ram-only", 0, used=30 * GB)]
    plan = make_plan("t", 1 * GB, 50 * GB, cs, set())
    plan["pools"] = [{"pool": "system", "name": "system memory", "needs_bytes": GB, "available_bytes": 50 * GB, "enough": True}]
    extend_plan(plan, "gpu:0", "Card", 10 * GB, 2 * GB, cs, set(), {"a": 6 * GB, "b": 6 * GB})
    assert [(u["id"], u["frees_bytes"], u["pool"]) for u in plan["unload"]] == [("a", 6 * GB, "gpu:0"), ("b", 6 * GB, "gpu:0")]
    assert plan["enough"] and plan["pool"] == "gpu:0"          # ram-only frees no VRAM, so it's never picked
    plan = make_plan("t", 1 * GB, 50 * GB, cs, {"a"})
    plan["pools"] = [{"pool": "system", "name": "system memory", "needs_bytes": GB, "available_bytes": 50 * GB, "enough": True}]
    extend_plan(plan, "gpu:0", "Card", 10 * GB, 2 * GB, cs, {"a"}, {"a": 6 * GB, "b": 6 * GB})
    assert [u["id"] for u in plan["unload"]] == ["b"] and not plan["enough"]
