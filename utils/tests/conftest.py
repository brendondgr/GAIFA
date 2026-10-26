"""Shared test fixtures.

- `root`: a temporary project root (GAIFA_ROOT), with an empty `services/`.
- `make_app` / `app` / `client`: the hub app on that root with its lifespan
  running, and an `httpx.AsyncClient` over ASGI.
- `fake_mod`: starts a fake mod from `fixtures/mods/` on a free port.
- `hub_process`: `python app.py` as a real process on a free port.

`make_app` passes a `SubprocessBackend`, so tests never touch systemd (the
systemd backend has its own marked tests).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from utils import config
from utils.backends.subprocess import SubprocessBackend
from utils.server import Options, create_app

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_MODS = FIXTURES / "mods"
OPENAPI = FIXTURES / "openapi"


def needs_mods(*sids: str) -> pytest.MarkDecorator:
    """Skip a test that reads these mods' files when their folders aren't checked out: relay, lcpp,
    tts and gen3d are submodules (plan mod-repos 2.3), empty in a clone made without them."""
    missing = [s for s in sids if not (REPO / "services" / s / "service.toml").is_file()]
    verb = "isn't" if len(missing) == 1 else "aren't"
    return pytest.mark.skipif(bool(missing), reason=", ".join(f"services/{s}" for s in missing)
                              + f" {verb} checked out: git submodule update --init " + " ".join(f"services/{s}" for s in missing))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 10, ok: Callable[[httpx.Response], bool] = lambda r: True) -> httpx.Response:
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = httpx.get(url, timeout=1)
            if ok(r):
                return r
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"{url} did not answer within {timeout}s")
        time.sleep(0.05)


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory, monkeypatch):
    """Every test gets a throwaway GAIFA_ROOT and a closed GAIFA_URL, so nothing (a CLI
    subprocess included) can touch the real repo's services/ or the installed hub."""
    scratch = tmp_path_factory.mktemp("isolated-root")
    (scratch / "services").mkdir()
    monkeypatch.setenv("GAIFA_ROOT", str(scratch))
    monkeypatch.setenv("GAIFA_URL", "http://127.0.0.1:1")
    from utils.tools import judge as judge_mod      # the judge and screening never reach the real relay

    real = judge_mod.config_from
    monkeypatch.setattr(judge_mod, "config_from", lambda cfg: judge_mod.JudgeConfig(
        **{**real(cfg).__dict__, "url": "http://127.0.0.1:1"}))


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    (tmp_path / "services").mkdir()
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def make_app(root):
    def make(cfg: config.Config | None = None, backend=None, **opts):
        cfg = cfg or config.load(root / "config.toml")
        opts.setdefault("extra_hosts", ("hub",))  # the ASGI clients' base_url http://hub (production: loopback only)
        return create_app(config.build_paths(cfg, root), cfg, backend=backend or SubprocessBackend(), options=Options(**opts))

    return make


@pytest.fixture
async def app(make_app):
    app = make_app(port=7000)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as c:
        yield c


@dataclass
class FakeMod:
    mode: str
    port: int
    outputs: Path
    proc: subprocess.Popen

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def fake_mod(tmp_path):
    """`fake_mod("ok", FAKE_MEM_MB="8")` → a running FakeMod (listening; maybe not yet healthy)."""
    started: list[FakeMod] = []

    def start(mode: str, **env: str) -> FakeMod:
        port = free_port()
        outputs = tmp_path / "outputs" / f"fake-{mode}"
        proc = subprocess.Popen(
            [sys.executable, str(FAKE_MODS / "_fakemod.py"), mode],
            env={**os.environ, "FAKE_PORT": str(port), "FAKE_OUTPUTS": str(outputs), **env},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        mod = FakeMod(mode, port, outputs, proc)
        started.append(mod)
        wait_for(mod.url + "/openapi.json", timeout=10)
        return mod

    yield start
    for mod in started:
        if mod.proc.poll() is None:
            mod.proc.kill()
        mod.proc.wait(5)


@pytest.fixture
def hub_process(root):
    """Run `python app.py --port <free> --dev` on the temp root; yields its base URL."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "app.py"), "--port", str(port), "--dev"],  # --dev: never touch real systemd units
        env={**os.environ, "GAIFA_ROOT": str(root)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(url + "/api/system", timeout=20, ok=lambda r: r.status_code == 200)
    except TimeoutError:
        proc.kill()
        pytest.fail("hub did not start:\n" + proc.communicate()[0])
    proc.url = url  # type: ignore[attr-defined]
    yield proc
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def services_dir(root):
    """Copy fake mods into the temp root's `services/`: `services_dir("fake-ok", ...)`."""

    def copy(*ids: str) -> Path:
        for helper in FAKE_MODS.glob("_*.py"):          # _fakemod.py and its parts (_fakews.py)
            shutil.copy(helper, root / "services" / helper.name)
        for i in ids:
            shutil.copytree(FAKE_MODS / i, root / "services" / i)
        return root / "services"

    return copy
