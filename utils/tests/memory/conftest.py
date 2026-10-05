"""Fixtures for the memory manager: a fake memory source and a hub with two fake-mem mods.

`FakeSource` follows the mods' real load states: a loaded (or unloading) mod uses its
size from `sizes`, so loads and unloads through the real fake mods move the numbers the
planner sees. Default machine: 100 GB total, 20 GB used by everything else, and the
default 12 GB reserve, so 68 GB is available to load into.
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx
import pytest

from utils.tests.conftest import free_port
from utils.tests.services.conftest import FAST, rig, serve, until  # noqa: F401 (rig and serve are fixtures)

GB = 1000**3


class FakeSource:
    def __init__(self, total: int = 100 * GB, base: int = 20 * GB, sizes: dict[str, int] | None = None) -> None:
        self.total, self.base = total, base
        self.sizes = sizes or {}
        self.extra: dict[str, int] = {}  # measured use regardless of load state
        self.mgr: Any = None

    async def collect(self, mgr: Any) -> dict[str, list[int]]:
        self.mgr = mgr
        return {}

    def used(self) -> dict[str, int]:
        out = dict(self.extra)
        for s in self.mgr.list() if self.mgr else []:
            if s.load in ("loaded", "unloading"):
                out[s.id] = out.get(s.id, 0) + self.sizes.get(s.id, 0)
        return out

    def read(self, pids: dict[str, list[int]]) -> tuple[dict[str, int], None, dict[str, int]]:
        used = self.used()
        total_used = self.base + sum(used.values())
        return {"total_bytes": self.total, "used_bytes": total_used, "available_bytes": self.total - total_used}, None, used

    def available(self) -> int:
        return self.read({})[0]["available_bytes"]


@pytest.fixture
def memhub(rig, make_app):
    """`async with memhub(config="...", triggers=True) as (app, client, source):` two fake-mem mods
    of 40 GB each (`fake-mem` and `fake-mem2`), running; nothing loaded."""

    @contextlib.asynccontextmanager
    async def make(config: str = "", triggers: bool = False, sizes: dict[str, int] | None = None, start: bool = True):
        env = '{ FAKE_PORT = "{port}", FAKE_OUTPUTS = "{outputs}", FAKE_ESTIMATE_GB = "40" }'  # its status says 40 GB too
        rig.add("fake-mem", edit={"estimate_gb": "40", "env": env})
        two = rig.add("fake-mem", as_id="fake-mem2", edit={"name": '"Fake Memory 2"', "estimate_gb": "40", "env": env})
        if triggers:
            with (two / "service.toml").open("a") as f:
                f.write('triggers = ["POST /v1/load", "POST /v1/items/{id}/run"]\n')
        rig.config(config)
        rig.write_config()
        app = make_app(backend=rig.backend, port=free_port(), autostart=False)
        hub = app.state.hub
        hub.timing = FAST
        src = FakeSource(sizes=sizes or {"fake-mem": 40 * GB, "fake-mem2": 40 * GB})
        hub.memory_source = src
        hub.memory_every_s = 0.05
        async with app.router.lifespan_context(app):
            hub.memory.wait_s, hub.memory.poll_s = 3.0, 0.02
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
                if start:
                    for sid in ("fake-mem", "fake-mem2"):
                        assert (await c.post(f"/api/services/{sid}/start", params={"wait": 1})).json()["state"] == "ready"
                yield app, c, src
                for sid in ("fake-mem", "fake-mem2"):
                    await c.post(f"/api/services/{sid}/stop", params={"wait": 1})

    return make


async def loaded(app, sid: str, state: str = "loaded", timeout: float = 10) -> None:
    mgr = app.state.hub.services
    await until(lambda: mgr.get(sid).load == state, timeout=timeout)
