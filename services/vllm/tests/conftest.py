"""Shared fixtures: settings in a temporary folder, two small profiles, a fake hub, and engines that run
the fake vLLM (`vllm_mod.fake_engine`) as a process instead of a container."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest

from vllm_mod.engine import Engine
from vllm_mod.hubclient import Hub
from vllm_mod.settings import Settings

PROFILE = 'name = "{name}"\nmodel = "org/{id}"\nserved_name = "{id}"\nalias = "{name}"\nmemory_gb = {gb}\nmax_model_len = 4096\n'


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "small.toml").write_text(PROFILE.format(id="small", name="Small", gb=2))
    (profiles / "big.toml").write_text(PROFILE.format(id="big", name="Big", gb=30))
    monkeypatch.setenv("FAKE_VLLM_STARTUP_S", "0.3")
    for k in ("FAKE_VLLM_FAIL", "FAKE_VLLM_CRASH_S"):
        monkeypatch.delenv(k, raising=False)
    return Settings(port=free_port(), engine_port=free_port(), state_dir=tmp_path / "state", hf_home=tmp_path / "hf",
                    profiles_dir=profiles, hub_url="http://hub", fake=True, start_timeout_s=20, overhead_gb=1,
                    relay_url="")       # never the live relay; tests that need one pass a fake


class FakeHub:
    """Records acquire calls; `room = False` answers 409 needs_room like the hub."""

    def __init__(self):
        self.calls: list[dict] = []
        self.models: list[dict] = []
        self.room = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path == "/api/memory/acquire":
            self.calls.append({**body, "make_room": request.url.params.get("make_room")})
            if not self.room:
                plan = {"needs_bytes": body["needs_bytes"], "available_bytes": 1, "enough": False, "unload": []}
                return httpx.Response(409, json={"detail": "Not enough memory for vLLM", "code": "needs_room",
                                                 "data": {"plan": plan}})
            return httpx.Response(200, json={"granted": True, "freed": []})
        if request.url.path == "/api/models":
            if any(m["path"] == body["path"] for m in self.models):
                return httpx.Response(409, json={"detail": "exists", "code": "model_exists"})
            self.models.append(body)
            return httpx.Response(201, json={"id": "m"})
        return httpx.Response(404, json={"detail": "not found", "code": "not_found"})


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def make_engine(settings, hub):
    made: list[Engine] = []

    def make(**kw) -> Engine:
        e = Engine(settings, Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)),
                   gtt_total=130_446_385_152, poll_s=0.05, **kw)
        made.append(e)
        return e

    yield make
    for e in made:     # never leave a fake engine running
        asyncio.run(_kill(e))


async def _kill(e: Engine) -> None:
    for f in await e.c.list():
        await e.c.remove(f.name)


def run(coro):
    return asyncio.run(coro)


class FakeFetch:
    """Stands in for snapshot_download: writes a blob and a snapshot like the HF cache, slowly enough
    to watch progress; `fail` makes it raise."""

    def __init__(self, size: int = 4000, chunks: int = 4, delay: float = 0.3):
        self.size, self.chunks, self.delay = size, chunks, delay
        self.calls: list[str] = []
        self.fail: str | None = None

    def __call__(self, repo: str, revision: str, cache_dir: Path) -> str:
        import time
        self.calls.append(repo)
        if self.fail:
            raise OSError(self.fail)
        base = cache_dir / ("models--" + repo.replace("/", "--"))
        (base / "blobs").mkdir(parents=True, exist_ok=True)
        blob = base / "blobs" / "abc123"
        with open(blob, "wb") as f:
            for _ in range(self.chunks):
                f.write(b"x" * (self.size // self.chunks))
                f.flush()
                time.sleep(self.delay / self.chunks)
        snap = base / "snapshots" / "c0ffee"
        snap.mkdir(parents=True, exist_ok=True)
        for name in ("model.safetensors", "config.json", "tokenizer.json"):
            link = snap / name
            if not link.exists():
                link.symlink_to(Path("../../blobs/abc123"))
        return str(snap)


@pytest.fixture
def fetch() -> FakeFetch:
    return FakeFetch()


@pytest.fixture
def make_downloads(settings, hub, fetch):
    from vllm_mod.downloads import Downloads

    def make(engine: Engine) -> Downloads:
        return Downloads(settings, engine.hub, fetch=fetch, remote_size=lambda repo, rev: fetch.size)
    return make
