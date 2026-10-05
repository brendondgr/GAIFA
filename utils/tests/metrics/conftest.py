"""Fixtures for metrics: an open `hub.db` and a recorder over fake services and memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from utils.db import Database
from utils.events import Alerts, EventBus
from utils.metrics import Recorder

GB = 1000**3
T0 = 1_760_000_000  # a fixed start on the 10 s grid (and on a whole hour: 1760000400 is)


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "hub.db")
    d.open()
    yield d
    d.close()


@dataclass
class FakeMod:
    name: str


@dataclass
class FakeSvc:
    id: str
    state: str = "ready"
    load: str = "n/a"
    stats: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def mod(self) -> FakeMod:
        return FakeMod(self.id.upper())


class FakeMgr:
    def __init__(self, *svcs: FakeSvc) -> None:
        self.services = {s.id: s for s in svcs}

    def list(self) -> list[FakeSvc]:
        return list(self.services.values())


class FakeMemory:
    def __init__(self) -> None:
        self.snapshot: dict[str, Any] | None = {
            "total_bytes": 100 * GB, "used_bytes": 30 * GB, "available_bytes": 70 * GB, "reserve_bytes": 12 * GB,
            "other_bytes": 20 * GB, "gpu": {"name": "x", "vram_total_bytes": 0, "vram_used_bytes": 0,
                                           "gtt_total_bytes": 64 * GB, "gtt_used_bytes": 5 * GB},
            "by_service": [{"id": "a", "used_bytes": 10 * GB}],
        }


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def rec(db):
    """`rec(*svcs)` → a Recorder (not started) on a fake clock; `.clock.t` moves time."""

    def make(*svcs: FakeSvc, disk_path: Any = None, alerts: Alerts | None = None) -> Recorder:
        bus = EventBus()
        r = Recorder(FakeMgr(*svcs), FakeMemory(), db, bus, alerts, disk_path=disk_path, clock=Clock())
        return r

    return make


from utils.tests.services.conftest import rig, serve  # noqa: E402,F401 (fixtures for the route tests)
