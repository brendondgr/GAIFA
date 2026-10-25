"""Hardware detection (plan 35.1): every recorded machine replays to the expected Machine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from utils import hardware
from utils.hardware.source import Snapshot

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


def machine(name: str) -> hardware.Machine:
    return hardware.from_snapshot(load(name))


@pytest.mark.parametrize("name, os_, wsl, accels, gpus", [
    ("strix-halo", "linux", False, ["rocm", "vulkan", "cpu"], [("amd", "gfx1151", "unified")]),
    ("linux-nvidia-1gpu", "linux", False, ["cuda", "vulkan", "cpu"], [("nvidia", "sm_89", "dedicated")]),
    ("linux-nvidia-2gpu", "linux", False, ["cuda", "vulkan", "cpu"], [("nvidia", "sm_86", "dedicated"), ("nvidia", "sm_86", "dedicated"), ("intel", "i915", "unified")]),
    ("linux-intel-arc", "linux", False, ["xpu", "vulkan", "cpu"], [("intel", "i915", "dedicated")]),
    ("wsl2-nvidia", "linux", True, ["cuda", "cpu"], [("nvidia", "sm_89", "dedicated")]),
    ("wsl2-intel", "linux", True, ["xpu", "cpu"], [("intel", "", "unknown")]),
    ("macos-m3", "darwin", False, ["mps", "cpu"], [("apple", "m3", "unified")]),
    ("linux-cpu", "linux", False, ["cpu"], []),
])
def test_fixtures(name, os_, wsl, accels, gpus):
    m = machine(name)
    assert (m.os, m.wsl, m.accels) == (os_, wsl, accels)
    assert [(g.vendor, g.arch, g.memory) for g in m.gpus] == gpus
    assert [g.index for g in m.gpus] == list(range(len(gpus)))


def test_strix_halo_details():
    m = machine("strix-halo")
    g = m.gpus[0]
    assert g.name == "AMD Radeon 8060S Graphics" and g.pci == "0000:c4:00.0" and g.driver == "amdgpu"
    assert g.vram_bytes == 130446364672        # unified: what it may address (GTT), not the 4 GiB carve-out
    assert g.runtimes == {"rocm": "7.1", "vulkan": "yes"} and not g.problems
    assert m.unified and m.pkg == "dnf" and m.distro["id"] == "fedora" and m.ram_bytes > 120e9


def test_two_nvidia_cards_count_per_vendor():
    m = machine("linux-nvidia-2gpu")
    assert [(g.vendor, g.vendor_index) for g in m.gpus] == [("nvidia", 0), ("nvidia", 1), ("intel", 0)]
    assert m.gpus[0].vram_bytes == 24576 * 2**20 and m.gpus[0].runtimes["cuda"] == "12.4"
    assert "Level Zero" in m.gpus[2].problems[0]      # the iGPU without Intel's compute runtime: no xpu
    assert not m.unified


def test_nvidia_without_driver():
    d = load("linux-nvidia-1gpu")
    d["which"]["nvidia-smi"] = None
    d["links"]["/sys/bus/pci/devices/0000:01:00.0/driver"] = "../../../../bus/pci/drivers/nouveau"
    m = hardware.from_snapshot(d)
    assert m.accels == ["cpu"]                         # nouveau's Vulkan doesn't count
    assert "nouveau" in m.gpus[0].problems[0] and m.gpus[0].driver == "nouveau"


def test_amd_without_kfd():
    d = load("strix-halo")
    d["dirs"]["/dev"] = [x for x in d["dirs"]["/dev"] if x != "kfd"]
    m = hardware.from_snapshot(d)
    assert m.accels == ["vulkan", "cpu"] and "/dev/kfd" in m.gpus[0].problems[0]


def test_wsl_without_dxg():
    d = load("wsl2-nvidia")
    d["dirs"]["/dev"] = ["null"]
    m = hardware.from_snapshot(d)
    assert m.accels == ["cpu"] and "dxg" in m.gpus[0].problems[-1]


def test_intel_mac_has_no_gpu():
    d = load("macos-m3")
    d["platform"]["machine"] = "x86_64"
    assert hardware.from_snapshot(d).accels == ["cpu"]


def test_snapshot_round_trip_and_dict():
    m = machine("linux-nvidia-1gpu")
    d = m.to_dict()
    assert d["unified"] is False and d["gpus"][0]["accels"] == ["cuda", "vulkan"]
    assert hardware.Machine.from_dict(json.loads(json.dumps(d))) == m
    assert Snapshot({"platform": {"system": "linux"}}).read("/missing") is None


def test_device_strings():
    assert hardware.DEVICE["rocm"] == "cuda" and hardware.DEVICE["vulkan"] == "cpu" and hardware.DEVICE["mps"] == "mps"


def test_fixture_env(monkeypatch):
    monkeypatch.setenv("GAIFA_HARDWARE_FIXTURE", str(FIX / "macos-m3.json"))
    assert hardware.detect(refresh=True).os == "darwin"
    monkeypatch.delenv("GAIFA_HARDWARE_FIXTURE")
    hardware.detect(refresh=True)


@pytest.mark.linux
@pytest.mark.skipif(not Path("/sys/class/kfd").exists(), reason="this machine's own check (Strix Halo)")
def test_this_machine_matches_its_fixture():
    live, ref = hardware.detect_from(hardware.Source()), machine("strix-halo")
    assert live.accels == ref.accels
    assert [(g.vendor, g.arch, g.memory, g.name) for g in live.gpus] == [(g.vendor, g.arch, g.memory, g.name) for g in ref.gpus]


@pytest.mark.skipif(sys.platform != "linux", reason="records the live machine")
def test_record_replays_identically():
    m, snap = hardware.record()
    assert hardware.from_snapshot(json.loads(json.dumps(snap))) == m
