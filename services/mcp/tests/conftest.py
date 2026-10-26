"""The mcp mod's app with a throwaway state folder, and the stdio fake server's launch spec."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import create_app  # noqa: E402

FAKE = {"id": "fake", "name": "Fake", "transport": "stdio", "command": sys.executable,
        "args": [str(Path(__file__).with_name("fake_server.py"))], "env": {"FAKE_TOKEN": "${FAKE_TOKEN}"}}


@pytest.fixture
async def app(tmp_path):
    (tmp_path / ".env").write_text("FAKE_TOKEN=s3cret\n")
    a = create_app(tmp_path / "state", tmp_path / "outputs", "", tmp_path / "logs", tmp_path / ".env", idle_s=3600)
    async with a.router.lifespan_context(a):
        yield a


@pytest.fixture
async def c(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp", timeout=90) as client:
        yield client


async def approved(c, spec=FAKE):
    assert (await c.post("/v1/servers", json=spec)).status_code == 201
    s = (await c.get(f"/v1/servers/{spec['id']}?tools=true")).json()
    r = await c.post(f"/v1/servers/{spec['id']}/approve", json={"hash": s["hash"]})
    assert r.status_code == 200, r.text
    return r.json()
