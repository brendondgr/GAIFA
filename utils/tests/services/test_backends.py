"""2.2: both backends pass the same contract. systemd runs only where a user manager answers."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

from utils.backends.base import BackendError
from utils.backends.subprocess import SubprocessBackend
from utils.backends.systemd import SystemdBackend, available
from utils.manifest import LaunchSpec
from utils.tests.conftest import FAKE_MODS, free_port

PY = "python3"  # on PATH for both the hub and the systemd user manager

BACKENDS = [
    pytest.param("subprocess", id="subprocess"),
    pytest.param(
        "systemd",
        id="systemd",
        marks=[pytest.mark.systemd, pytest.mark.skipif(not available(), reason="no systemd user manager")],
    ),
]


@pytest.fixture(params=BACKENDS)
async def backend(request):
    if request.param == "subprocess":
        b = SubprocessBackend()
    else:
        b = SystemdBackend(prefix=f"gaifatest{os.getpid()}-")
    yield b
    for sid in await b.list_ours():
        await b.stop(sid, 5)
    await b.close()


def spec(tmp_path: Path, sid: str, argv: list[str], env: dict[str, str] | None = None, stop_s: float = 5, port: int = 0) -> LaunchSpec:
    return LaunchSpec(
        id=sid, argv=argv, cwd=tmp_path, env={"PYTHONUNBUFFERED": "1", **(env or {})},
        port=port, stop_timeout_s=stop_s, outputs=tmp_path / "out",
    )


def fake(tmp_path: Path, mode: str, sid: str = "fake", **env: str) -> LaunchSpec:
    port = free_port()
    return spec(
        tmp_path, sid, [PY, str(FAKE_MODS / "_fakemod.py"), mode],
        {"FAKE_PORT": str(port), "FAKE_OUTPUTS": str(tmp_path / "out"), **env}, port=port,
    )


async def until(fn, timeout: float = 10, every: float = 0.1):
    deadline = time.monotonic() + timeout
    while True:
        value = await fn()
        if value:
            return value
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(every)


async def healthy(port: int) -> bool:
    try:
        async with httpx.AsyncClient() as c:
            return (await c.get(f"http://127.0.0.1:{port}/health", timeout=1)).status_code == 200
    except httpx.TransportError:
        return False


async def test_start_state_logs_stop(backend, tmp_path):
    s = fake(tmp_path, "ok")
    st = await backend.start(s)
    assert st.active == "active" and st.pid and st.started_ts and abs(st.started_ts - time.time()) < 30
    await until(lambda: healthy(s.port))
    assert await backend.list_ours() == ["fake"]

    async def listening():
        return [ln for ln in await backend.logs("fake", 50) if "listening on 127.0.0.1" in ln["text"]]

    [line] = await until(listening)
    assert line["stream"] in ("stdout", "stderr") and line["ts"] > 0

    await backend.stop("fake", 5)
    assert (await backend.state("fake")).active == "inactive"
    assert await backend.list_ours() == []
    assert not await healthy(s.port)


async def test_crash_is_failed_with_status(backend, tmp_path):
    await backend.start(fake(tmp_path, "crash", FAKE_CRASH_S="0.3"))

    async def failed():
        st = await backend.state("fake")
        return st if st.active == "failed" else None

    st = await until(failed)
    assert st.exit_status == 1 and st.result == "exit-code"
    assert st.describe_exit() == "exited with status 1"
    assert await backend.list_ours() == []
    await backend.stop("fake", 5)  # clears the failed state
    assert (await backend.state("fake")).active == "inactive"


async def test_env_and_cwd_reach_the_process(backend, tmp_path):
    code = "import os; print('ENV', os.environ['GAIFA_X'], os.getcwd(), flush=True); import time; time.sleep(30)"
    await backend.start(spec(tmp_path, "envcheck", [PY, "-c", code], {"GAIFA_X": "with space=and equals"}))

    async def printed():
        return [ln for ln in await backend.logs("envcheck", 20) if ln["text"].startswith("ENV ")]

    [line] = await until(printed)
    assert line["text"] == f"ENV with space=and equals {tmp_path}"


async def test_follow_sees_new_lines(backend, tmp_path):
    s = fake(tmp_path, "ok", FAKE_VERBOSE="1")
    await backend.start(s)
    await until(lambda: healthy(s.port))
    got: list[str] = []

    async def collect():
        async for ln in backend.follow("fake"):
            got.append(ln["text"])
            if any("/v1/status" in t for t in got):
                return

    task = asyncio.create_task(collect())
    await asyncio.sleep(1)  # journalctl -f needs a moment to attach
    async with httpx.AsyncClient() as c:
        for _ in range(3):
            await c.get(f"http://127.0.0.1:{s.port}/v1/status")
    await asyncio.wait_for(task, 10)
    assert any("GET /v1/status" in t for t in got)


async def test_stop_kills_a_process_that_ignores_sigterm(backend, tmp_path):
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('up', flush=True); time.sleep(120)"
    await backend.start(spec(tmp_path, "stubborn", [PY, "-c", code], stop_s=1))
    await until(lambda: _has(backend, "stubborn", "up"))
    t0 = time.monotonic()
    await backend.stop("stubborn", 1)
    assert time.monotonic() - t0 < 10
    assert (await backend.state("stubborn")).active == "inactive"


async def test_stop_takes_the_children_too(backend, tmp_path):
    pidfile = tmp_path / "child.pid"
    await backend.start(spec(tmp_path, "parent", ["/bin/sh", "-c", f"sleep 120 & echo $! > {pidfile}; echo up; wait"]))
    await until(lambda: _exists(pidfile))
    child = int(pidfile.read_text())
    assert _alive(child)
    await backend.stop("parent", 2)
    await until(lambda: _dead(child), timeout=5)


async def test_pids_cover_the_mod_and_its_memory(backend, tmp_path):
    """5.1: the memory sampler counts every process of the mod (systemd: the unit's cgroup)."""
    from utils import proc

    pidfile = tmp_path / "child.pid"
    script = f"python3 -c 'b = bytearray(48 << 20); import time; time.sleep(120)' & echo $! > {pidfile}; wait"
    await backend.start(spec(tmp_path, "mem", ["/bin/sh", "-c", script]))
    await until(lambda: _exists(pidfile))
    child = int(pidfile.read_text())
    pids = await backend.pids("mem")
    assert pids
    assert child in pids or child in proc.process_tree(pids[0])
    await asyncio.sleep(0.3)
    assert proc.footprint(pids) >= 48 << 20
    await backend.stop("mem", 2)
    assert await backend.pids("mem") == []
    assert await backend.pids("never-started") == []


async def test_start_twice_is_an_error(backend, tmp_path):
    s = fake(tmp_path, "ok")
    await backend.start(s)
    with pytest.raises(BackendError):
        await backend.start(s)


async def test_stop_and_state_of_unknown_ids(backend):
    await backend.stop("never-started", 1)
    assert (await backend.state("never-started")).active == "inactive"
    assert await backend.logs("never-started", 10) == []


async def test_missing_executable(backend, tmp_path):
    s = spec(tmp_path, "nope", [str(tmp_path / "does-not-exist")])
    try:
        await backend.start(s)
    except BackendError as e:  # subprocess: refused up front
        assert "does-not-exist" in str(e) or "No such file" in str(e)
        return

    async def failed():  # systemd: the unit starts, then fails to exec (status 203)
        return (await backend.state("nope")).active == "failed"

    await until(failed)


async def test_subprocess_close_stops_children(tmp_path):
    b = SubprocessBackend()
    s = fake(tmp_path, "ok")
    await b.start(s)
    await until(lambda: healthy(s.port))
    await b.close()
    assert await b.list_ours() == []
    assert not await healthy(s.port)


async def test_subprocess_long_lines_and_ring(tmp_path):
    b = SubprocessBackend(ring=10)
    code = "import sys; [print(i) for i in range(30)]; print('x' * 200000); sys.stdout.write('tail-no-newline')"
    await b.start(spec(tmp_path, "chatty", [sys.executable, "-c", code]))
    await until(lambda: _has(b, "chatty", "tail-no-newline"))
    lines = await b.logs("chatty", 100)
    assert len(lines) == 10 and lines[-1]["text"] == "tail-no-newline"
    assert sum(len(ln["text"]) for ln in lines if set(ln["text"]) == {"x"}) == 200000
    await b.close()


async def _has(backend, sid: str, text: str) -> bool:
    return any(text in ln["text"] for ln in await backend.logs(sid, 200))


async def _exists(p: Path) -> bool:
    return p.exists() and p.read_text().strip() != ""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); count it as dead.
    if not Path("/proc/self").exists():      # macOS (plan 37.5)
        import psutil

        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


async def _dead(pid: int) -> bool:
    return not _alive(pid)
