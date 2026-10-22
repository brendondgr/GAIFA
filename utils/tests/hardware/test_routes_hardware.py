"""`GET /api/system/hardware` and `aihub hardware` (plan 35.2)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from utils import cli, cli_hardware, hardware

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def nvidia2(monkeypatch):
    monkeypatch.setenv("AIHUB_HARDWARE_FIXTURE", str(FIX / "linux-nvidia-2gpu.json"))
    hardware.detect(refresh=True)
    yield
    monkeypatch.delenv("AIHUB_HARDWARE_FIXTURE")
    hardware.detect(refresh=True)


async def test_route_answers_the_machine(client, nvidia2):
    r = await client.get("/api/system/hardware")
    assert r.status_code == 200
    m = r.json()
    assert m["accels"] == ["cuda", "vulkan", "cpu"] and m["unified"] is False
    assert [(g["vendor"], g["vendor_index"]) for g in m["gpus"]] == [("nvidia", 0), ("nvidia", 1), ("intel", 0)]
    assert m["gpus"][2]["vram_bytes"] == m["ram_bytes"]          # an iGPU may address the system's memory


async def test_route_refresh(client, monkeypatch, nvidia2):
    monkeypatch.setenv("AIHUB_HARDWARE_FIXTURE", str(FIX / "macos-m3.json"))
    assert (await client.get("/api/system/hardware")).json()["os"] == "linux"          # cached
    assert (await client.get("/api/system/hardware?refresh=true")).json()["os"] == "darwin"


def run(argv: list[str]) -> int:
    args = cli.parser().parse_args(argv)
    return args.fn(args)


def test_cli_json_and_text(capsys, nvidia2):
    assert run(["hardware", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["gpus"][0]["arch"] == "sm_86"
    assert run(["hardware"]) == 0
    out = capsys.readouterr().out
    assert "GPU 1     NVIDIA GeForce RTX 3090 (sm_86) · 24.0 GiB VRAM" in out and "problem: libze_loader" in out
    assert out.rstrip().endswith("Accels    cuda, vulkan, cpu")


def test_cli_replays_a_snapshot(capsys):
    assert run(["hardware", "--from", str(FIX / "wsl2-intel.json")]) == 0
    out = capsys.readouterr().out
    assert "(WSL2)" in out and "Intel GPU (through WSL)" in out and "Accels    xpu, cpu" in out


@pytest.mark.skipif(not Path("/proc/meminfo").exists(), reason="records the live machine")
def test_cli_snapshot_replays(tmp_path, capsys):
    snap = tmp_path / "me.json"
    assert run(["hardware", "--snapshot", str(snap)]) == 0
    capsys.readouterr()
    assert hardware.from_snapshot(json.loads(snap.read_text())) == hardware.detect_from(hardware.Source())
    assert run(["hardware", "--from", str(snap), "--json"]) == 0


def test_summary_without_gpu():
    m = hardware.from_snapshot(json.loads((FIX / "linux-cpu.json").read_text()))
    assert "GPU       none found: everything runs on the CPU" in cli_hardware.summary(m)
