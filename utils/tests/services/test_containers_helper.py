"""37.4: the template's container helper (services/_template/containers.py): the GPU flags per vendor and
runtime, for every recorded machine; and the runtime the hub passes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from utils import hardware

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "utils" / "tests" / "hardware" / "fixtures"
spec = importlib.util.spec_from_file_location("tpl_containers", REPO / "services" / "_template" / "containers.py")
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def m(name: str) -> dict:
    return hardware.from_snapshot(json.loads((FIX / f"{name}.json").read_text())).to_dict()


@pytest.fixture(autouse=True)
def no_index(monkeypatch):
    monkeypatch.delenv("GAIFA_GPU_INDEX", raising=False)


def test_amd():
    assert ct.gpu_args(m("strix-halo"), "podman", selinux=True) == ["--device", "/dev/kfd", "--device", "/dev/dri", "--group-add", "keep-groups",
                                                                   "--security-opt", "label=disable"]
    assert ct.gpu_args(m("strix-halo"), "docker", selinux=True) == ["--device", "/dev/kfd", "--device", "/dev/dri", "--group-add", "video", "--group-add", "render"]


def test_nvidia():
    assert ct.gpu_args(m("linux-nvidia-1gpu"), "podman", selinux=False) == ["--device", "nvidia.com/gpu=all"]
    assert ct.gpu_args(m("linux-nvidia-1gpu"), "docker", selinux=False) == ["--gpus", "all"]
    two = m("linux-nvidia-2gpu")
    assert ct.gpu_args(two, "podman", index=1, selinux=False) == ["--device", "nvidia.com/gpu=1"]
    assert ct.gpu_args(two, "docker", index=1, selinux=False) == ["--gpus", "device=1"]


def test_index_from_the_environment(monkeypatch):
    monkeypatch.setenv("GAIFA_GPU_INDEX", "0")
    assert ct.gpu_args(m("linux-nvidia-2gpu"), "podman", selinux=False) == ["--device", "nvidia.com/gpu=0"]


def test_intel_wsl_mac_and_none():
    assert ct.gpu_args(m("linux-intel-arc"), "podman", selinux=False) == ["--device", "/dev/dri", "--group-add", "keep-groups"]
    assert ct.gpu_args(m("wsl2-intel"), "podman", selinux=False) == ["--device", "/dev/dxg", "-v", "/usr/lib/wsl:/usr/lib/wsl:ro"]
    assert ct.gpu_args(m("wsl2-nvidia"), "docker", selinux=False) == ["--gpus", "all"]
    assert ct.gpu_args(m("macos-m3"), "podman") == [] and ct.gpu_args(m("linux-cpu"), "podman") == [] and ct.gpu_args(None) == []


def test_runtime(monkeypatch):
    monkeypatch.setenv("GAIFA_CONTAINER_RUNTIME", "docker")
    assert ct.runtime() == "docker"
    monkeypatch.delenv("GAIFA_CONTAINER_RUNTIME")
    monkeypatch.setattr(ct.shutil, "which", lambda c: "/usr/bin/docker" if c == "docker" else None)
    assert ct.runtime() == "docker"
    monkeypatch.setattr(ct.shutil, "which", lambda c: "/usr/bin/" + c)
    assert ct.runtime() == "podman"
    assert ct.hardware(url="http://127.0.0.1:9") is None        # no hub there


def test_the_hub_passes_the_runtime(rig, tmp_path):
    from utils import config, manifest as mf

    tmp_path = rig.root
    rig.add("fake-ok")
    rig.config('[containers]\nruntime = "docker"\n')
    rig.write_config()
    cfg = config.load(tmp_path / "config.toml")
    mod = next(x for x in mf.discover([rig.services]) if x.id == "fake-ok")
    env = mf.launch_spec(mod, cfg, config.build_paths(cfg, tmp_path), 7000).env
    assert env["GAIFA_CONTAINER_RUNTIME"] == "docker"
