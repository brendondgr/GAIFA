"""Phase 39: each mod's real setup doc picks the right variant on every recorded machine. One row per
setup doc that has variants; a missing entry means "not available on this machine"."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import cli_setup_variant as cv, hardware, setupdocs
from utils.tests.conftest import REPO

FIX = REPO / "utils" / "tests" / "hardware" / "fixtures"
MACHINES = ["strix-halo", "linux-nvidia-1gpu", "linux-nvidia-2gpu", "linux-intel-arc", "wsl2-nvidia", "wsl2-intel", "macos-m3", "linux-cpu"]

# setup id → {machine: accel} (absent: unavailable there)
EXPECTED: dict[str, dict[str, str]] = {
    "lcpp": {"strix-halo": "vulkan", "linux-nvidia-1gpu": "vulkan", "linux-nvidia-2gpu": "vulkan", "linux-intel-arc": "vulkan",
             "wsl2-nvidia": "cuda", "wsl2-intel": "cpu", "macos-m3": "mps", "linux-cpu": "cpu"},
    **{m: {k: "cpu" for k in MACHINES} for m in ("agent", "relay", "web", "searxng", "opencode", "workspace")},
}


def envs() -> dict[str, setupdocs.Env]:
    from utils import cli_setup

    offered, _ = cli_setup.choices(REPO)
    return offered


def machine(name: str) -> hardware.Machine:
    return hardware.from_snapshot(json.loads((FIX / f"{name}.json").read_text()))


@pytest.mark.parametrize("setup_id", sorted(EXPECTED))
def test_each_machine_gets_the_expected_variant(setup_id):
    e = envs()[setup_id]
    got = {}
    for name in MACHINES:
        v, _ = cv.pick(e, machine(name))
        if v is not None:
            got[name] = v.accel
    assert got == EXPECTED[setup_id]


def test_this_machine_keeps_its_backends():
    """Strix Halo picks what it runs today, for every setup doc."""
    m = machine("strix-halo")
    for e in envs().values():
        v, why = cv.pick(e, m)
        assert v is not None, (e.id, why)
        assert m.accels.index(v.accel) is not None and "linux" in v.tested, (e.id, v.accel)
