"""The agent against a scripted model (fakemodel.py) and a stand-in hub (fakehub.py), both real
HTTP servers on free ports; the agent app runs in-process (ASGI) unless a test starts it as a
process."""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from agent.loop import Config
from agent.server import create_app

from .fakehub import FakeHub
from .fakemodel import FakeModel


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serve(app: Any) -> tuple[uvicorn.Server, asyncio.Task[Any], int]:
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    return server, task, port


@dataclass
class Env:
    model: FakeModel
    hub: FakeHub
    client: httpx.AsyncClient
    app: Any
    tmp: Path
    hub_url: str
    llm_url: str

    @property
    def agent(self) -> Any:
        return self.app.state.agent

    async def thread(self, **kw: Any) -> str:
        r = await self.client.post("/v1/threads", json=kw)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def send(self, tid: str, text: str, wait: bool = True, **kw: Any) -> dict[str, Any]:
        r = await self.client.post(f"/v1/threads/{tid}/messages", json={"text": text, **kw})
        assert r.status_code == 202, r.text
        if wait:
            await self.settle(tid)
        return r.json()

    async def settle(self, tid: str, timeout: float = 15) -> str:
        """Wait until the turn stops running; returns the thread state."""
        deadline = time.monotonic() + timeout
        await asyncio.sleep(0.02)
        while time.monotonic() < deadline:
            if not self.agent.running(tid):
                return self.agent.store.thread(tid)["state"]
            await asyncio.sleep(0.02)
        raise TimeoutError(f"thread {tid} still running: {self.types(tid)}")

    def events(self, tid: str, type_: str | None = None) -> list[dict[str, Any]]:
        evs = self.agent.store.events(tid)
        return [e for e in evs if type_ is None or e["type"] == type_]

    def types(self, tid: str) -> list[str]:
        return [e["type"] for e in self.agent.store.events(tid) if e["type"] not in ("state", "usage")]

    def payloads(self, tid: str, type_: str) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events(tid, type_)]


@pytest.fixture
async def env(tmp_path):
    model, hub = FakeModel(), FakeHub()
    ms, mt, mport = await serve(model.app)
    hs, ht, hport = await serve(hub.app)
    cfg = Config(model="main", fallback="backup", max_steps=6, data=tmp_path / "data" / "agent", default_window=8000)
    hub_url, llm_url = f"http://127.0.0.1:{hport}", f"http://127.0.0.1:{mport}/v1"
    app = create_app(cfg, db=tmp_path / "agent.db", hub_url=hub_url, llm_url=llm_url)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agent", timeout=30) as c:
            yield Env(model, hub, c, app, tmp_path, hub_url, llm_url)
    for s in (ms, hs):
        s.should_exit = True
    await asyncio.gather(mt, ht, return_exceptions=True)
