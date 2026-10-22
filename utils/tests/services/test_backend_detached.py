"""37.1: the detached backend: mods that outlive the hub without systemd, adopted after a restart."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from utils import config as cfgmod
from utils.backends.detached import DetachedBackend
from utils.backends.subprocess import SubprocessBackend
from utils.manifest import LaunchSpec
from utils.server import Options, default_backend

SLEEPER = "import sys, time\nprint('hello', flush=True)\nprint('oops', file=sys.stderr, flush=True)\ntime.sleep(60)\n"
STUBBORN = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(60)\n"


def spec(tmp_path: Path, code: str, sid: str = "m") -> LaunchSpec:
    return LaunchSpec(id=sid, argv=[sys.executable, "-c", code], cwd=tmp_path, env={"X": "1"}, port=5199,
                      stop_timeout_s=5, outputs=tmp_path / "out")


async def wait_for(fn, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if await fn():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


async def test_start_state_logs_stop(tmp_path):
    b = DetachedBackend(tmp_path / "pids", poll_s=0.05)
    st = await b.start(spec(tmp_path, SLEEPER))
    try:
        assert st.active == "active" and st.pid
        rec = json.loads((tmp_path / "pids" / "m.json").read_text())
        assert rec["pid"] == st.pid and rec["cwd"] == str(tmp_path) and rec["port"] == 5199
        assert await b.list_ours() == ["m"] and await b.pids("m") == [st.pid] and await b.workdir("m") == str(tmp_path)
        await wait_for(lambda: _has(b, "oops"))
        assert [x["text"] for x in await b.logs("m", 10)] == ["hello", "oops"]
    finally:
        await b.stop("m", 3)
    assert (await b.state("m")).active == "inactive" and not (tmp_path / "pids" / "m.json").exists()


async def _has(b, text):
    return any(x["text"] == text for x in await b.logs("m", 10))


async def test_a_new_hub_adopts_a_running_mod(tmp_path):
    first = DetachedBackend(tmp_path / "pids")
    st = await first.start(spec(tmp_path, SLEEPER))
    await first.close()                                  # the hub stops: the mod keeps running
    second = DetachedBackend(tmp_path / "pids")          # a new hub on the same folder
    try:
        again = await second.state("m")
        assert again.active == "active" and again.pid == st.pid and await second.list_ours() == ["m"]
    finally:
        await second.stop("m", 3)
    assert (await second.state("m")).active == "inactive"
    first._children.clear()


async def test_stale_pidfile_and_pid_reuse(tmp_path):
    d = tmp_path / "pids"
    d.mkdir()
    (d / "gone.json").write_text(json.dumps({"pid": 999999, "create_time": 1.0, "cwd": "/x"}))
    (d / "reused.json").write_text(json.dumps({"pid": os.getpid(), "create_time": 1.0, "cwd": "/x"}))   # a live pid, another start time
    b = DetachedBackend(d)
    assert (await b.state("gone")).result == "gone" and not (d / "gone.json").exists()
    assert (await b.state("reused")).active == "failed" and await b.list_ours() == []


async def test_a_mod_that_ignores_sigterm_is_killed(tmp_path):
    b = DetachedBackend(tmp_path / "pids", poll_s=0.05)
    await b.start(spec(tmp_path, STUBBORN))
    await wait_for(lambda: _has(b, "ready"))
    t = time.monotonic()
    await b.stop("m", 0.5)
    assert time.monotonic() - t < 3 and (await b.state("m")).active == "inactive"


async def test_exit_codes_and_follow(tmp_path):
    b = DetachedBackend(tmp_path / "pids", poll_s=0.05)
    await b.start(spec(tmp_path, "import time; time.sleep(0.3); print('bye', flush=True); raise SystemExit(3)"))
    seen = []

    async def collect():
        async for line in b.follow("m"):
            seen.append(line["text"])
            if line["text"] == "bye":
                return

    await asyncio.wait_for(collect(), 5)
    await wait_for(lambda: _done(b))
    st = await b.state("m")
    assert (st.active, st.result, st.exit_status) == ("failed", "exit-code", 3) and seen == ["bye"]


async def _done(b):
    return (await b.state("m")).active != "active"


async def test_missing_executable(tmp_path):
    from utils.backends.base import BackendError

    b = DetachedBackend(tmp_path / "pids")
    with pytest.raises(BackendError):
        await b.start(LaunchSpec(id="m", argv=[str(tmp_path / "nope")], cwd=tmp_path, env={}, port=1, stop_timeout_s=1, outputs=tmp_path))


def test_choosing_the_backend(tmp_path, monkeypatch):
    from utils.backends import systemd

    paths = cfgmod.build_paths(cfgmod.Config(), tmp_path)

    def pick(backend: str, dev: bool = False, has_systemd: bool = True):
        monkeypatch.setattr(systemd, "available", lambda: has_systemd)
        return type(default_backend(Options(dev=dev), cfgmod.Config(hub={"backend": backend}), paths)).__name__

    assert pick("auto") == "SystemdBackend"
    assert pick("auto", has_systemd=False) == "DetachedBackend"
    assert pick("detached") == "DetachedBackend" and pick("subprocess") == "SubprocessBackend"
    assert pick("auto", dev=True) == "SubprocessBackend"
    assert isinstance(default_backend(Options(dev=True)), SubprocessBackend)


async def test_a_fake_mod_survives_a_hub_restart(rig, tmp_path):
    """The hub's own adoption path (state machine, health) with the detached backend."""
    from utils.tests.services.conftest import until

    class Detached(DetachedBackend):
        async def really_close(self) -> None:
            for sid in await self.list_ours():
                await self.stop(sid, 3)

    rig.backend = Detached(rig.root / "data" / "state" / "hub" / "pids", poll_s=0.05)
    rig.add("fake-ok")
    first = await rig.manager()
    await first.start("fake-ok", wait=True)
    pid = first.get("fake-ok").pid
    await first.close()
    second = await rig.manager(autostart=True)
    svc = second.get("fake-ok")
    await until(lambda: svc.state == "ready")
    assert svc.pid == pid
    await second.stop("fake-ok", wait=True)
    assert await rig.backend.list_ours() == []
