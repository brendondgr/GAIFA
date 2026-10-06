"""5.1: /proc and /sys facts: meminfo, the GPU, process trees, RSS + DRM memory, cgroups, units and containers."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from utils import proc

KIB = 1024


def test_meminfo(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal:       126920436 kB\nMemFree:  1 kB\nMemAvailable:   100000000 kB\nHugePages_Total: 0\n")
    assert proc.meminfo(tmp_path) == {"total_bytes": 126920436 * KIB, "used_bytes": 26920436 * KIB, "available_bytes": 100000000 * KIB}
    assert proc.meminfo(tmp_path / "missing") == {"total_bytes": 0, "used_bytes": 0, "available_bytes": 0}


def test_real_meminfo_and_gpu():
    m = proc.meminfo()
    assert m["total_bytes"] > 0 and 0 < m["available_bytes"] <= m["total_bytes"]
    g = proc.gpu()
    assert g is None or (g["gtt_total_bytes"] > 0 and g["name"])


def test_gpu_from_sysfs(tmp_path):
    dev = tmp_path / "class/drm/card1/device"
    dev.mkdir(parents=True)
    (tmp_path / "class/drm/card0").mkdir()  # no mem_info files: skipped
    for name, v in {"mem_info_gtt_total": "1000", "mem_info_gtt_used": "400", "mem_info_vram_total": "512",
                    "mem_info_vram_used": "128", "vendor": "0x1002\n", "device": "0xffff\n"}.items():
        (dev / name).write_text(v)
    g = proc.gpu(tmp_path)
    assert g == {"name": "GPU 1002:ffff", "vram_total_bytes": 512, "vram_used_bytes": 128, "gtt_total_bytes": 1000, "gtt_used_bytes": 400}
    assert proc.gpu(tmp_path / "none") is None


def fake_proc(root, pid: int, rss_kib: int, children=(), fdinfo: dict[str, str] | None = None) -> None:
    d = root / str(pid)
    (d / "task" / str(pid)).mkdir(parents=True)
    (d / "status").write_text(f"Name:\tx\nVmRSS:\t  {rss_kib} kB\n")
    (d / "task" / str(pid) / "children").write_text(" ".join(map(str, children)))
    (d / "fdinfo").mkdir()
    for fd, text in (fdinfo or {}).items():
        (d / "fdinfo" / fd).write_text(text)


def test_pss_is_preferred_to_rss_so_shared_pages_count_once(tmp_path):
    fake_proc(tmp_path, 20, 4000, children=[21])
    fake_proc(tmp_path, 21, 4000)
    for pid in (20, 21):  # a forked worker: both show 4000 kB resident, 3000 kB of it shared
        (tmp_path / str(pid) / "smaps_rollup").write_text(f"Rss:\t4000 kB\nPss:\t2500 kB\n")
    assert proc.pss_bytes(20, tmp_path) == 2500 * KIB
    assert proc.footprint([20], tmp_path) == 5000 * KIB


def drm(client: int, gtt_kib: int, vram_kib: int = 0) -> str:
    return f"pos:\t0\ndrm-driver:\tamdgpu\ndrm-client-id:\t{client}\ndrm-memory-gtt:\t{gtt_kib} KiB\ndrm-memory-vram:\t{vram_kib} KiB\n"


def test_footprint_counts_rss_and_each_drm_client_once(tmp_path):
    fake_proc(tmp_path, 10, 1000, children=[11, 12], fdinfo={"3": drm(7, 5000, 100), "4": drm(7, 5000, 100), "5": "pos: 0\n"})
    fake_proc(tmp_path, 11, 200, fdinfo={"3": drm(7, 5000, 100)})  # the same client, shared after fork
    fake_proc(tmp_path, 12, 300, children=[13], fdinfo={"9": drm(8, 2000)})
    fake_proc(tmp_path, 13, 50)
    assert sorted(proc.process_tree(10, tmp_path)) == [10, 11, 12, 13]
    assert proc.rss_bytes(10, tmp_path) == 1000 * KIB
    assert proc.gpu_bytes(10, proc=tmp_path) == 5100 * KIB
    total = (1000 + 200 + 300 + 50) * KIB + (5100 + 2000) * KIB
    assert proc.footprint([10], tmp_path) == total
    assert proc.footprint([10, 12, 99], tmp_path) == total  # overlapping trees and a gone pid count once / not at all


def test_real_process_tree_and_footprint():
    child = subprocess.Popen([sys.executable, "-c", "import time; b = bytearray(64 << 20); time.sleep(30)"])
    try:
        time.sleep(0.5)
        me = os.getpid()
        assert child.pid in proc.process_tree(me)
        assert proc.footprint([child.pid]) >= 60 << 20
    finally:
        child.kill()
        child.wait()


def test_cgroup_pids_include_sub_cgroups(tmp_path):
    cg = tmp_path / "user.slice/app.slice/aihub-x.service"
    (cg / "sub").mkdir(parents=True)
    (cg / "cgroup.procs").write_text("100\n101\n")
    (cg / "sub" / "cgroup.procs").write_text("102\n")
    assert sorted(proc.cgroup_pids("/user.slice/app.slice/aihub-x.service", tmp_path)) == [100, 101, 102]
    assert proc.cgroup_pids("/nope", tmp_path) == []


def test_units_and_containers(monkeypatch):
    calls = []

    def fake_cmd(*args):
        calls.append(args)
        if args[:3] == ("systemctl", "--user", "list-units"):
            return "lcpp-gemma.service loaded active running x\nlcpp-qwen.service loaded active running y\n"
        if args[:3] == ("systemctl", "--user", "show"):
            return "/user.slice/x.service\n" if args[3] == "ok.service" else "\n"
        if args[:2] == ("podman", "inspect"):
            return {"comfyui": "4242\n", "stopped": "0\n"}.get(args[-1])
        return None

    monkeypatch.setattr(proc, "_cmd", fake_cmd)
    assert proc.units_matching("lcpp-*.service") == ["lcpp-gemma.service", "lcpp-qwen.service"]
    assert proc.unit_cgroup("ok.service") == "/user.slice/x.service" and proc.unit_cgroup("gone.service") is None
    assert proc.container_pid("comfyui") == 4242
    assert proc.container_pid("stopped") is None and proc.container_pid("missing") is None


def test_real_cmd_failures_are_none():
    assert proc._cmd("definitely-not-a-command-aihub") is None
    assert proc._cmd(sys.executable, "-c", "raise SystemExit(3)") is None
