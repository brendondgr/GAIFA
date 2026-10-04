"""Fixtures for the service tests: a ServiceManager on a temp root with fast timings."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import pytest

from utils import config
from utils.backends.subprocess import SubprocessBackend
from utils.db import Database
from utils.events import ActivityLog, Alerts, EventBus
from utils.services import ServiceManager, Timing
from utils.tests.conftest import FAKE_MODS, free_port

FAST = Timing(
    start_poll_s=0.05, health_every_s=0.1, health_timeout_s=0.3, backoff_s=(0.05, 0.1, 0.2),
    restart_window_s=60, status_busy_s=0.1, status_idle_s=0.3,
)


class KeepBackend(SubprocessBackend):
    """Children survive `close()`, like systemd units survive a hub restart."""

    async def close(self) -> None:
        pass

    async def really_close(self) -> None:
        await SubprocessBackend.close(self)


class Rig:
    """A temp root with fake mods copied in, and managers built on it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.services = root / "services"
        self.backend = KeepBackend()
        self.managers: list[ServiceManager] = []
        self.events: list[dict] = []
        self.db: Database | None = None
        self.ports: dict[str, int] = {}
        self.config_lines: list[str] = []

    def add(self, mod: str, as_id: str | None = None, edit: dict[str, str] | None = None, port: int | None = None) -> Path:
        """Copy fixture mod `mod` in as `as_id`, editing manifest lines (`key = value` replaced by key)."""
        sid = as_id or mod
        shutil.copy(FAKE_MODS / "_fakemod.py", self.services / "_fakemod.py")
        dest = self.services / sid
        shutil.copytree(FAKE_MODS / mod, dest)
        text = (dest / "service.toml").read_text().replace(f'id = "{mod}"', f'id = "{sid}"')
        self.ports[sid] = port or free_port()
        text = _set_line(text, "port", str(self.ports[sid]))
        for key, value in (edit or {}).items():
            text = _set_line(text, key, value)
        (dest / "service.toml").write_text(text)
        return dest

    def config(self, text: str) -> None:
        self.config_lines.append(text)

    def write_config(self) -> None:
        (self.root / "config.toml").write_text("\n".join(self.config_lines) + "\n")

    async def manager(self, autostart: bool = False, boot: bool = True, timing: Timing = FAST) -> ServiceManager:
        self.write_config()
        cfg = config.load(self.root / "config.toml")
        paths = config.build_paths(cfg, self.root)
        paths.ensure()
        if self.db is None:
            self.db = Database(paths.hub_db)
            self.db.open()
        bus = EventBus()
        sub = bus.subscribe()
        activity = ActivityLog(self.db, bus)
        await activity.load()
        mgr = ServiceManager(paths, cfg, self.backend, bus, activity, Alerts(bus), hub_port=free_port(), timing=timing)
        mgr.test_activity = activity  # type: ignore[attr-defined]
        self.managers.append(mgr)

        async def pump() -> None:
            async for ev in sub:
                self.events.append(ev)

        mgr.test_pump = asyncio.create_task(pump())  # type: ignore[attr-defined]
        if boot:
            await mgr.boot(autostart=autostart)
        return mgr

    def states(self, sid: str) -> list[str]:
        out: list[str] = []
        for ev in self.events:
            if ev["type"] == "service" and ev["service"]["id"] == sid:
                st = ev["service"]["state"]
                if not out or out[-1] != st:
                    out.append(st)
        return out

    async def close(self) -> None:
        for m in self.managers:
            await m.close()
            m.test_pump.cancel()  # type: ignore[attr-defined]
        await self.backend.really_close()
        if self.db:
            self.db.close()


def _set_line(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key} = {value}"
            return "\n".join(lines) + "\n"
    # not present: add it under [run]
    i = lines.index("[run]")
    lines.insert(i + 1, f"{key} = {value}")
    return "\n".join(lines) + "\n"


@pytest.fixture
async def rig(root):
    r = Rig(root)
    yield r
    await r.close()


async def until(fn, timeout: float = 10, every: float = 0.02):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(every)


class Served:
    """The hub app on a real port (uvicorn in this event loop), for streaming tests."""

    def __init__(self, app, port: int) -> None:
        self.app, self.port = app, port
        self.url = f"http://127.0.0.1:{port}"

    @property
    def hub(self):
        return self.app.state.hub

    @property
    def services(self):
        return self.app.state.hub.services


@pytest.fixture
async def serve(rig, make_app):
    """`await serve(**options)`: write the rig's config, build the app and serve it; mods autostart."""
    import uvicorn

    servers: list = []

    async def start(timing: Timing = FAST, **opts) -> Served:
        rig.write_config()
        app = make_app(backend=rig.backend, port=free_port(), **opts)
        app.state.hub.timing = timing
        port = app.state.hub.port
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2))
        task = asyncio.create_task(server.serve())
        servers.append((server, task))
        await until(lambda: server.started, timeout=10)
        served = Served(app, port)
        return served

    yield start
    for server, task in servers:
        app_hub = server.config.app.state.hub
        app_hub.bus.close()
        server.should_exit = True
        await asyncio.wait_for(task, 15)


async def ready(served: Served, *ids: str, timeout: float = 15) -> None:
    await until(lambda: all(served.services.get(i).state == "ready" for i in ids), timeout=timeout)
