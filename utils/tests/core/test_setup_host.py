"""37.3: `gaifa setup host` per machine: the GPU checks that apply, fixes for its package manager, and
nothing run (fixes are text)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import cli_platform, cli_setup_host, cli_setup_pkgs, hardware

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"


class Probe(cli_setup_host.Probe):
    def __init__(self, machine: str, have=("uv", "git"), groups=("video", "render"), edit=None) -> None:
        data = json.loads((FIX / f"{machine}.json").read_text())
        if edit:
            edit(data)
        self.m, self.have, self.grps = hardware.from_snapshot(data), set(have), set(groups)

    def machine(self): return self.m
    def cmdline(self) -> str: return "amdgpu.gttsize=131072 ttm.pages_limit=33554432"
    def groups(self) -> set[str]: return self.grps
    def which(self, cmd: str) -> bool: return cmd in self.have
    def free_gb(self, path: Path) -> float: return 500.0
    def gtt_bytes(self) -> int: return 130_000_000_000
    def mem_bytes(self) -> int: return 130_000_000_000
    def linger(self) -> bool: return True


@pytest.fixture(autouse=True)
def wsl_systemd_on(monkeypatch):
    monkeypatch.setattr(cli_platform, "systemd_running", lambda: True)


def ids(found) -> list[str]:
    return [c.id for c in found]


def by_id(found) -> dict:
    return {c.id: c for c in found}


def test_this_machine_unchanged(tmp_path):
    found = cli_setup_host.checks(Probe("strix-halo"), Path.home())
    assert ids(found) == ["kernel-gtt", "iommu-on", "gtt-size", "gpu-groups", "uv", "needs:git", "clone-under-home", "linger", "disk"]


def test_nvidia_on_ubuntu(tmp_path):
    found = by_id(cli_setup_host.checks(Probe("linux-nvidia-1gpu"), tmp_path, {"ffmpeg", "podman", "toolbox"}))
    assert found["nvidia-driver"].ok and "CUDA 12.8" in found["nvidia-driver"].detail
    assert not found["nvidia-cdi"].ok and "nvidia-ctk cdi generate" in found["nvidia-cdi"].fix and found["nvidia-cdi"].needs_root
    assert found["needs:ffmpeg"].fix == "sudo apt install ffmpeg" and found["needs:toolbox"].fix == "sudo apt install podman-toolbox"
    assert "kernel-gtt" not in found and "clone-under-home" not in found          # Strix Halo's own checks don't apply
    no_driver = Probe("linux-nvidia-1gpu", edit=lambda d: d["which"].update({"nvidia-smi": None}))
    c = by_id(cli_setup_host.checks(no_driver, tmp_path))["nvidia-driver"]
    assert not c.ok and c.fix.startswith("sudo ubuntu-drivers install") and c.gpu and c.needs_root


def test_two_nvidia_cards_and_an_igpu(tmp_path):
    found = cli_setup_host.checks(Probe("linux-nvidia-2gpu"), tmp_path)
    assert [c.id for c in found if c.gpu] == ["nvidia-driver", "nvidia-driver", "gpu-groups", "intel-runtime"]
    rt = by_id(found)["intel-runtime"]
    assert not rt.ok and rt.fix == "sudo apt install intel-opencl-icd libze1 libze-intel-gpu1"
    assert cli_setup_host.blocking(found, gpu=False) == []          # GPU problems don't block CPU-only plans


def test_intel_arc(tmp_path):
    found = by_id(cli_setup_host.checks(Probe("linux-intel-arc", groups=("video",)), tmp_path))
    assert found["intel-runtime"].ok and not found["gpu-groups"].ok and "usermod -aG render" in found["gpu-groups"].fix


def test_wsl(tmp_path, monkeypatch):
    found = by_id(cli_setup_host.checks(Probe("wsl2-nvidia"), tmp_path))
    assert found["wsl-systemd"].ok and found["wsl-gpu"].ok and found["wsl-clone"].ok
    assert "WSL uses it" not in found["nvidia-driver"].fix                       # ok: no fix
    monkeypatch.setattr(cli_platform, "systemd_running", lambda: False)
    found = by_id(cli_setup_host.checks(Probe("wsl2-intel"), Path("/mnt/c/Users/me/GAIFA")))
    assert not found["wsl-systemd"].ok and "wsl --shutdown" in found["wsl-systemd"].fix
    assert not found["wsl-clone"].ok and found["intel-runtime"].ok and "gpu-groups" not in found
    no_driver = Probe("wsl2-nvidia", edit=lambda d: d["which"].update({"nvidia-smi": None}) or d["dirs"].update({"/usr/lib/wsl/lib": []}))
    c = by_id(cli_setup_host.checks(no_driver, tmp_path))["nvidia-driver"]
    assert not c.ok and "on Windows" in c.fix and not c.needs_root


def test_macos(tmp_path):
    found = by_id(cli_setup_host.checks(Probe("macos-m3", have=("uv", "git")), tmp_path, {"espeak-ng", "toolbox"}))
    assert found["apple-silicon"].ok and not found["homebrew"].ok
    assert found["needs:espeak-ng"].fix == "brew install espeak-ng" and not found["needs:espeak-ng"].needs_root
    assert "isn't available" in found["needs:toolbox"].fix
    assert "linger" not in found and "kernel-gtt" not in found


def test_no_gpu(tmp_path):
    found = by_id(cli_setup_host.checks(Probe("linux-cpu"), tmp_path))
    assert found["gpu"].ok and "CPU variant" in found["gpu"].detail


def test_package_names():
    assert cli_setup_pkgs.fix("node", "dnf") == ("sudo dnf install nodejs22", True)
    assert cli_setup_pkgs.fix("ffmpeg", "dnf")[0].endswith("(the full ffmpeg is in RPM Fusion: host.md §3)")
    assert cli_setup_pkgs.fix("node", "pacman") == ("sudo pacman -S nodejs", True)
    assert cli_setup_pkgs.fix("espeak-ng", "") == ("install espeak-ng with your system's package manager", True)
