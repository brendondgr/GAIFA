"""36.1: the pools a machine has, and each mod's share, read from fake nvidia-smi output and sysfs."""

from __future__ import annotations

import json
from pathlib import Path

from utils import hardware
from utils.memory.pools import PoolReader

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"
MIB = 2**20


def machine(name: str) -> hardware.Machine:
    return hardware.from_snapshot(json.loads((FIX / f"{name}.json").read_text()))


def test_unified_machines_have_no_gpu_pools():
    for name in ("strix-halo", "macos-m3", "linux-cpu", "wsl2-intel"):
        assert PoolReader(machine(name)).read({"x": [1]}) == ([], {}), name


def test_two_nvidia_cards():
    calls = []

    def smi(args):
        calls.append(args[0])
        if args[0].startswith("--query-gpu"):
            return "0, 24576, 20000\n1, 24576, 1000\n"
        return "101, 00000000:01:00.0, 19000\n202, 00000000:02:00.0, 800\n303, 00000000:01:00.0, 50\n"

    tree = {10: [10, 101], 20: [20, 202]}
    r = PoolReader(machine("linux-nvidia-2gpu"), smi=smi, tree=lambda p: tree.get(p, [p]))
    pools, use = r.read({"comfy": [10], "tts": [20]})
    assert [(p.id, p.total_bytes, p.used_bytes, p.available_bytes) for p in pools] == [
        ("gpu:0", 24576 * MIB, 20000 * MIB, 4576 * MIB), ("gpu:1", 24576 * MIB, 1000 * MIB, 23576 * MIB)]
    assert use == {"comfy": {"gpu:0": 19000 * MIB}, "tts": {"gpu:1": 800 * MIB}}     # pid 303 is no mod's
    assert pools[0].name == "NVIDIA GeForce RTX 3090"
    assert r.available("gpu:1") == 23576 * MIB


def test_nvidia_smi_silent():
    r = PoolReader(machine("linux-nvidia-1gpu"), smi=lambda a: "")
    pools, use = r.read({"comfy": [10]})
    assert [(p.id, p.total_bytes, p.used_bytes) for p in pools] == [("gpu:0", 24564 * MIB, 0)] and use == {}


def test_amd_card_from_sysfs_and_fdinfo(tmp_path):
    m = machine("strix-halo")
    g = m.gpus[0]
    g.memory, g.vram_bytes, g.pci = "dedicated", 16 * 2**30, "0000:03:00.0"
    dev = tmp_path / "0000:03:00.0"
    dev.mkdir()
    (dev / "mem_info_vram_total").write_text(str(16 * 2**30))
    (dev / "mem_info_vram_used").write_text(str(6 * 2**30))
    drm = lambda pids: {"0000:03:00.0": 5 * 2**30, "0000:09:00.0": 1} if pids == [7] else {}
    pools, use = PoolReader(m, sys_pci=tmp_path, drm=drm).read({"lcpp": [7], "web": [8]})
    assert [(p.id, p.used_bytes, p.available_bytes) for p in pools] == [("gpu:0", 6 * 2**30, 10 * 2**30)]
    assert use == {"lcpp": {"gpu:0": 5 * 2**30}}
