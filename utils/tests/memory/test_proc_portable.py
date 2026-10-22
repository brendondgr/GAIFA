"""The psutil reads behind utils/proc.py where /proc is missing (plan 35.3), checked against the
/proc reads on this machine, and the facade switching to them."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from utils import paths, proc, proc_portable

linux = pytest.mark.skipif(not Path("/proc/meminfo").exists(), reason="compares against /proc")


@linux
def test_meminfo_agrees():
    a, b = proc.meminfo(), proc_portable.meminfo()
    assert abs(a["total_bytes"] - b["total_bytes"]) < 64 * 2**20
    assert abs(a["available_bytes"] - b["available_bytes"]) < 2 * 2**30   # sampled a moment apart


@linux
def test_process_tree_and_memory_agree():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        me = os.getpid()
        assert child.pid in proc_portable.process_tree(me) and child.pid in proc.process_tree(me)
        assert abs(proc.rss_bytes(me) - proc_portable.rss_bytes(me)) < 32 * 2**20
        assert proc_portable.pss_bytes(me) > 0 and proc_portable.footprint([me]) >= proc_portable.pss_bytes(me)
        assert proc_portable.describe(child.pid)["cmdline"].endswith("time.sleep(30)")
    finally:
        child.kill()
        child.wait()


def test_port_owner_finds_this_process():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        owner = proc_portable.port_owner(s.getsockname()[1])
        assert owner and owner["pid"] == os.getpid()
    finally:
        s.close()


def test_facade_uses_psutil_without_proc(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "PROC", tmp_path / "no-proc")
    monkeypatch.setattr(proc.meminfo, "__defaults__", (proc.PROC,))
    monkeypatch.setattr(proc.rss_bytes, "__defaults__", (proc.PROC,))
    assert proc.meminfo()["total_bytes"] > 0
    assert proc.rss_bytes(os.getpid()) > 0


def test_write_atomic_without_a_folder_fsync(monkeypatch, tmp_path):
    real = os.open

    def no_dirs(p, flags, *a):
        if Path(p).is_dir():
            raise PermissionError("folders can't be opened here")
        return real(p, flags, *a)

    monkeypatch.setattr(os, "open", no_dirs)
    paths.write_atomic(tmp_path / "x.json", "{}")
    assert (tmp_path / "x.json").read_text() == "{}"
