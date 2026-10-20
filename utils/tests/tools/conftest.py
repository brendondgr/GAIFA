"""The `tools` area against `fake-tools` (manifest tools of every risk, a job, file inputs,
binary results, a tools_source) and `fake-perms` (network and execute tools, plan 25) under the
subprocess backend."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from utils import config
from utils.tests.conftest import free_port


@dataclass
class ToolsHub:
    app: Any
    client: httpx.AsyncClient
    root: Path

    @property
    def hub(self) -> Any:
        return self.app.state.hub

    async def call(self, name: str, arguments: dict | None = None, mode: str = "ask", wait: float = 30, **origin: Any) -> dict:
        r = await self.client.post(f"/api/tools/{name}/call?wait={wait}", json={"arguments": arguments or {}, "mode": mode, "origin": origin})
        assert r.status_code == 200, r.text
        return r.json()


async def wait_ready(client: httpx.AsyncClient, sid: str, timeout: float = 15) -> None:
    for _ in range(int(timeout / 0.1)):
        r = (await client.get(f"/api/services/{sid}")).json()
        if r.get("state") == "ready":
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"{sid} not ready: {r}")


@pytest.fixture
def tools_cfg(root) -> config.Config:
    return config.load(root / "config.toml")


async def _hub_with(mod: str, services_dir, make_app, cfg):
    services = services_dir(mod)
    toml = services / mod / "service.toml"
    toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text()))
    app = make_app(cfg, port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            await wait_ready(c, mod)
            yield ToolsHub(app, c, services.parent)


@pytest.fixture
async def th(services_dir, root, make_app, tools_cfg):
    async for h in _hub_with("fake-tools", services_dir, make_app, tools_cfg):
        yield h


@pytest.fixture
async def ph(services_dir, root, make_app, tools_cfg):
    """`fake-perms`: network and execute tools (plan 25)."""
    async for h in _hub_with("fake-perms", services_dir, make_app, tools_cfg):
        yield h


@pytest.fixture
async def wh(services_dir, root, make_app, tools_cfg):
    """`fake-ws`: a workspace mod in miniature with a preflight (plan 27.4)."""
    async for h in _hub_with("fake-ws", services_dir, make_app, tools_cfg):
        yield h
