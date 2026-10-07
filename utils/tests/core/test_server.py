import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from utils import config
from utils.server import HubError, create_app

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
async def client(make_app):
    app = make_app(port=7123)

    class Body(BaseModel):
        n: int

    r = APIRouter()

    @r.get("/api/_test/hub-error")
    async def hub_error():
        raise HubError(409, "needs_room", "not enough memory", {"plan": {"enough": False}})

    @r.get("/api/_test/crash")
    async def crash():
        raise RuntimeError("kaboom")

    @r.post("/api/_test/body")
    async def body(b: Body):
        return b

    app.include_router(r)
    app.router.routes.insert(0, app.router.routes.pop())  # before the static mount
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub") as c:
            c.app = app
            yield c


async def test_lifespan_creates_dirs_and_db(client, root):
    assert (root / "data/databases/hub.db").exists()
    assert (root / "outputs").is_dir() and (root / "data/models").is_dir()
    assert client.app.state.hub.activity is not None


async def test_system(client, root):
    (root / "outputs/tts").mkdir()
    (root / "outputs/tts/a.wav").write_bytes(b"x" * 1000)
    s = (await client.get("/api/system")).json()
    assert s["hub"]["pid"] == os.getpid() and s["hub"]["port"] == 7123
    assert s["hub"]["version"] == "0.1.0" and s["hub"]["rss_bytes"] > 0
    assert s["paths"]["root"] == str(root.resolve())
    assert s["paths"]["outputs"] == str(root.resolve() / "outputs")
    assert s["usage"]["outputs_bytes"] == 1000
    assert s["usage"]["databases_bytes"] > 0
    assert 0 < s["disk"]["free_bytes"] <= s["disk"]["total_bytes"]


async def test_config_js_lists_live_areas(client):
    r = await client.get("/config.js")
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.text == 'window.AIHUB_API_BASE = "";\nwindow.AIHUB_LIVE_AREAS = ["system", "services", "logs", "operations", "proxy", "events", "models", "outputs", "memory", "metrics", "widgets", "overview", "settings", "tools"];\n'


async def test_docs_and_openapi(client):
    assert (await client.get("/api/docs")).status_code == 200
    spec = (await client.get("/api/openapi.json")).json()
    assert "/api/system" in spec["paths"] and "/api/events" in spec["paths"]
    assert "/config.js" not in spec["paths"]


async def test_error_envelope(client):
    r = await client.get("/api/_test/hub-error")
    assert r.status_code == 409
    assert r.json() == {"detail": "not enough memory", "code": "needs_room", "data": {"plan": {"enough": False}}}
    assert r.headers["x-aihub-error"] == "needs_room"

    r = await client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found", "code": "not_found"}

    r = await client.post("/api/_test/body", json={"n": "x"})
    assert r.status_code == 422
    j = r.json()
    assert j["code"] == "invalid_request" and j["detail"].startswith("body.n:")
    assert j["data"]["errors"][0]["loc"] == ["body", "n"]

    r = await client.get("/api/_test/crash")
    assert r.status_code == 500
    assert r.json() == {"detail": "RuntimeError: kaboom", "code": "hub_error"}


async def test_static_web(tmp_path):
    cfg = config.Config()
    paths = config.build_paths(cfg, tmp_path)
    paths.web.mkdir()
    (paths.web / "x.txt").write_text("hello")
    app = create_app(paths, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            assert (await c.get("/x.txt")).text == "hello"


def test_app_py_serves_both_stacks_and_stops_with_sse_open(hub_process):
    """`python app.py` end to end: IPv4 + IPv6, /api/system, /api/docs, SSE, quick shutdown."""
    url = hub_process.url
    port = int(url.rsplit(":", 1)[1])
    assert httpx.get(f"http://[::1]:{port}/api/system").json()["hub"]["port"] == port
    assert httpx.get(f"{url}/api/docs").status_code == 200
    with httpx.stream("GET", f"{url}/api/events", timeout=5) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert next(r.iter_lines()) == "retry: 3000"
        t0 = time.monotonic()
        hub_process.send_signal(signal.SIGINT)
        assert hub_process.wait(timeout=8) == 0
        assert time.monotonic() - t0 < 5
    assert "Traceback" not in hub_process.stdout.read()


def test_app_py_refuses_non_loopback(tmp_path):
    (tmp_path / "config.toml").write_text('[hub]\nhost = "0.0.0.0"\n')
    r = subprocess.run(
        [sys.executable, str(REPO / "app.py")],
        env={**os.environ, "AIHUB_ROOT": str(tmp_path)}, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 2
    assert "hub.host" in r.stderr and "not loopback" in r.stderr


def test_dev_mods_dont_inherit_the_hubs_port(services_dir, hub_process):
    """A child mod must not hold the hub's listening socket: it would keep the port bound after the hub exits."""
    import re
    from urllib.parse import urlparse

    from utils.proc import _listen_inodes
    from utils.tests.conftest import free_port, wait_for

    url = hub_process.url
    toml = services_dir("fake-ok") / "fake-ok" / "service.toml"
    toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text()))
    httpx.post(url + "/api/services/rescan", timeout=10)
    r = wait_for(url + "/api/services/fake-ok", timeout=15, ok=lambda r: r.json().get("state") == "ready")
    pid = r.json()["pid"]
    hub_inodes = _listen_inodes(urlparse(url).port)
    held = set()
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith("socket:["):
            held.add(target[8:-1])
    assert hub_inodes and not (held & hub_inodes)
