"""Each mod's GPU busy percentage (plan 28.2): DRM engine counters read per mod's processes, the busiest
engine's share between two samples, published as `gpu_busy_pct` in `GET /api/memory` (the embed mod's
idle gate reads it)."""

from __future__ import annotations

from pathlib import Path

from utils import proc
from utils.tests.memory.conftest import FakeSource


def fdinfo(root: Path, pid: int, fd: int, client: int, **engines: int) -> None:
    d = root / str(pid) / "fdinfo"
    d.mkdir(parents=True, exist_ok=True)
    (root / str(pid) / "task" / str(pid)).mkdir(parents=True, exist_ok=True)
    lines = [f"drm-client-id:\t{client}"] + [f"drm-engine-{k}:\t{v} ns" for k, v in engines.items()]
    (d / str(fd)).write_text("\n".join(lines) + "\n")


def test_engine_ns_counts_each_client_once_and_includes_children(tmp_path):
    fdinfo(tmp_path, 10, 3, client=7, gfx=100, compute=40)
    fdinfo(tmp_path, 11, 4, client=7, gfx=100, compute=40)            # the same client after a fork
    fdinfo(tmp_path, 11, 5, client=8, gfx=25)
    (tmp_path / "10" / "task" / "10" / "children").write_text("11")
    (tmp_path / "12" / "fdinfo").mkdir(parents=True)
    (tmp_path / "12" / "fdinfo" / "1").write_text("pos: 0\n")          # not a GPU file
    assert proc.engine_ns([10], tmp_path) == {"gfx": 125, "compute": 40}
    assert proc.engine_ns([12, 99], tmp_path) == {}


def test_busy_pct():
    assert proc.busy_pct({"gfx": 0, "compute": 0}, {"gfx": 500_000_000, "compute": 100_000_000}, 1.0) == 50.0
    assert proc.busy_pct({"gfx": 10}, {"gfx": 5}, 1.0) == 0.0                 # a counter that went back
    assert proc.busy_pct({}, {"gfx": 10**10}, 1.0) == 0.0                     # new since the last reading
    assert proc.busy_pct({"gfx": 0}, {"gfx": 10**10}, 1.0) == 100.0          # capped
    assert proc.busy_pct({"gfx": 0}, {"gfx": 1}, 0) == 0.0


class EngineSource(FakeSource):
    def __init__(self) -> None:
        super().__init__()
        self.ns = {"fake-mem": {"gfx": 0}}

    async def collect(self, mgr):
        await super().collect(mgr)
        return {"fake-mem": [1], "fake-mem2": [2]}

    def engines(self, pids):
        return {sid: dict(self.ns.get(sid, {})) for sid in pids}


async def test_memory_reports_each_mods_gpu_busy(memhub, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("utils.memory.manager.time.monotonic", lambda: clock["t"])
    async with memhub(start=False) as (app, c, src):
        mem = app.state.hub.memory
        await mem.close()                                               # drive sampling by hand
        mem.source = EngineSource()
        await mem.sample()
        assert all("gpu_busy_pct" not in r for r in (await c.get("/api/memory")).json()["by_service"])   # one reading
        clock["t"] += 2.0
        mem.source.ns["fake-mem"] = {"gfx": 500_000_000}                # 0.5 s busy in 2 s
        await mem.sample()
        rows = {r["id"]: r for r in (await c.get("/api/memory")).json()["by_service"]}
        assert rows["fake-mem"]["gpu_busy_pct"] == 25.0 and rows["fake-mem2"]["gpu_busy_pct"] == 0.0
