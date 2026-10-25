"""The sandbox (plan 27.5), with real podman and the built image: no network unless asked for (and
then the internet works), the folder writable only at Run, the rest of $HOME absent, the folder at
the same path (a .venv made inside it keeps working), timeout, cancel, limits, the toolchain."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest

import sandbox
from sandbox import Run, Sandbox, new_id

pytestmark = pytest.mark.podman


def _image_ok() -> bool:
    try:
        return subprocess.run(["podman", "image", "exists", sandbox.IMAGE], timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


if not _image_ok():
    pytest.skip(f"podman or the image {sandbox.IMAGE} isn't there (build it: podman build -t {sandbox.IMAGE} sandbox/)",
                allow_module_level=True)


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path / "state")


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "data.txt").write_text("hello\n")
    return d


def run(sb: Sandbox, folder: Path, command: str, writable: bool = True, network: bool = False, timeout: int = 60,
        disconnected=None) -> Run:
    r = Run(new_id(), command, "sandbox", str(folder), network=network, writable=writable, timeout_s=timeout)
    return asyncio.run(sb.run(r, folder, [(folder, "rw" if writable else "ro")], disconnected=disconnected))


def test_runs_in_the_folder_at_the_same_path(sb, folder):
    r = run(sb, folder, "pwd; cat data.txt; id -u")
    assert r.state == "done" and r.exit_code == 0, r.stderr
    lines = r.stdout.split()
    assert lines[0] == str(folder) and lines[1] == "hello" and lines[2] == str(__import__("os").getuid())
    rec = sb.records.get(r.id)
    assert rec["exit_code"] == 0 and rec["ms"] > 0 and (sb.records.dir / f"{r.id}.out").read_text().startswith(str(folder))


def test_the_toolchain(sb, folder):
    r = run(sb, folder, "python -V && uv --version && node -v && git --version && rg --version | head -1 && gcc --version | head -1 && "
                        "python -c 'import numpy, pandas, matplotlib, openpyxl, pptx, docx, pypdfium2; print(\"libs\")'")
    assert r.exit_code == 0, r.stderr
    assert "Python 3.12" in r.stdout and "uv " in r.stdout and "v24." in r.stdout and "git version" in r.stdout and "libs" in r.stdout


def test_no_network_by_default(sb, folder):
    r = run(sb, folder, "python -c \"import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)\"")
    assert r.exit_code != 0 and ("resolution" in r.stderr or "unreachable" in r.stderr or "Errno" in r.stderr)


def test_full_internet_with_network(sb, folder):
    r = run(sb, folder, "python -c \"import urllib.request; print(urllib.request.urlopen('https://pypi.org/simple/six/', timeout=15).status)\"",
            network=True)
    assert r.exit_code == 0 and r.stdout.strip() == "200", r.stderr


def test_the_folder_is_writable_only_at_run(sb, folder):
    rw = run(sb, folder, "echo new > made.txt && echo ok")
    assert rw.exit_code == 0 and (folder / "made.txt").read_text() == "new\n"
    ro = run(sb, folder, "echo again > made2.txt", writable=False)
    assert ro.exit_code != 0 and "Read-only file system" in ro.stderr and not (folder / "made2.txt").exists()


def test_the_rest_of_home_is_absent_and_caches_are_not_written_back(sb, folder):
    home = Path.home()
    r = run(sb, folder, f"ls -A {home}; ls {home}/.ssh 2>&1; ls {home}/Agents 2>&1; touch {home}/x; "
                        f"test -d {home}/.cache/uv && touch {home}/.cache/uv/gaifa-sandbox-probe && echo cache-writable; true")
    assert r.exit_code == 0, r.stderr
    assert ".ssh" not in r.stdout.split("\n")[0] and "No such file" in r.stdout
    assert not (home / "x").exists() and not (home / ".cache" / "uv" / "gaifa-sandbox-probe").exists()
    assert not (home / "Agents" / "GAIFA").exists() or "GAIFA" not in r.stdout


def test_a_venv_made_inside_the_folder_keeps_working(sb, folder):
    made = run(sb, folder, "uv venv -q .venv && .venv/bin/python -c 'import sys; print(sys.prefix)'")
    assert made.exit_code == 0 and made.stdout.strip() == str(folder / ".venv"), made.stderr
    assert (folder / ".venv" / "pyvenv.cfg").exists()
    again = run(sb, folder, ".venv/bin/python -c 'import sys; print(sys.executable)'")   # a later run: same paths
    assert again.exit_code == 0 and again.stdout.strip() == str(folder / ".venv" / "bin" / "python")


def test_timeout(sb, folder):
    t0 = time.time()
    r = run(sb, folder, "sleep 30", timeout=2)
    assert r.state == "timeout" and r.exit_code is None and "timeout" in r.note and time.time() - t0 < 25


def test_cancel(sb, folder):
    async def go():
        r = Run(new_id(), "echo started; sleep 30", "sandbox", str(folder), timeout_s=60)
        task = asyncio.create_task(sb.run(r, folder, [(folder, "rw")]))
        for _ in range(100):
            await asyncio.sleep(0.2)
            if r.id in sb.live and (sb.records.dir / f"{r.id}.out").exists() and (sb.records.dir / f"{r.id}.out").read_text():
                break
        assert await sb.cancel(r.id)
        return await task
    t0 = time.time()
    r = asyncio.run(go())
    assert r.state == "cancelled" and r.exit_code is None and "started" in r.stdout and time.time() - t0 < 30


def test_the_caller_leaving_cancels(sb, folder):
    calls = {"n": 0}

    async def gone() -> bool:
        calls["n"] += 1
        return calls["n"] > 3
    r = run(sb, folder, "sleep 30", disconnected=gone)
    assert r.state == "cancelled" and "went away" in r.note


def test_limits(sb, folder):
    r = run(sb, folder, "cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max")
    mem, pids = r.stdout.split()
    assert int(mem) == 8 * 1024 ** 3 and int(pids) == sandbox.PIDS
    bomb = run(sb, folder, "python -c \"import os\nfor i in range(5000):\n    if os.fork() == 0:\n        import time; time.sleep(5); os._exit(0)\" ; echo done",
               timeout=60)
    assert "Resource temporarily unavailable" in bomb.stderr or "BlockingIOError" in bomb.stderr


def test_a_missing_program_suggests_the_host(sb, folder):
    r = run(sb, folder, "cargo build")
    assert r.exit_code == 127 and "where=\"host\"" in r.note


def test_records_list(sb, folder):
    a = run(sb, folder, "true")
    listed = sb.records.list()
    assert listed[0]["id"] == a.id and "stdout" not in listed[0]


def test_the_routes(client):
    img = client.get("/v1/sandbox").json()
    assert img["exists"] and img["image"] == sandbox.IMAGE and img["size_mb"] > 100 and not img["building"]
    assert client.get("/v1/runs").json() == {"runs": []}
    assert client.get("/v1/runs/run_nope").status_code == 404
    assert client.post("/v1/runs/run_nope/cancel").json() == {"cancelled": False}
