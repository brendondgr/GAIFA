"""38.3: the hub passes a mod its variant: GAIFA_ACCEL, GAIFA_DEVICE, GAIFA_GPU_ARCH, `[run.variants.<accel>]`
env; and a mod whose variant this machine can't run is unavailable instead of failing to start."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import config, hardware, manifest as mf
from utils.services.model import ServiceError

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"


def machine(name: str) -> hardware.Machine:
    return hardware.from_snapshot(json.loads((FIX / f"{name}.json").read_text()))


def spec(rig, conf: str, machine_name: str = "strix-halo", variants: str = "") -> dict[str, str]:
    d = rig.add("fake-ok")
    if variants:
        text = (d / "service.toml").read_text().replace("[run]\n", "[run]\n", 1)
        (d / "service.toml").write_text(text + variants)
    rig.config(conf)
    rig.write_config()
    cfg = config.load(rig.root / "config.toml")
    mod = next(m for m in mf.discover([rig.services]) if m.id == "fake-ok")
    assert not mod.errors, mod.errors
    return mf.launch_spec(mod, cfg, config.build_paths(cfg, rig.root), 7000, machine=machine(machine_name)).env


def test_the_variant_reaches_the_mod(rig):
    env = spec(rig, '[services.fake-ok]\naccel = "rocm"\n', variants='\n[run.variants.rocm]\nenv = { FAKE_FAST = "1" }\n\n[run.variants.cpu]\nenv = { FAKE_FAST = "0" }\n')
    assert (env["GAIFA_ACCEL"], env["GAIFA_DEVICE"], env["GAIFA_GPU_ARCH"], env["FAKE_FAST"]) == ("rocm", "cuda", "gfx1151", "1")


def test_cpu_variant_and_none(rig):
    env = spec(rig, '[services.fake-ok]\naccel = "cpu"\n')
    assert (env["GAIFA_ACCEL"], env["GAIFA_DEVICE"]) == ("cpu", "cpu") and "GAIFA_GPU_ARCH" not in env


def test_nothing_recorded_nothing_passed(rig):
    env = spec(rig, "")
    assert "GAIFA_ACCEL" not in env and "GAIFA_DEVICE" not in env


def test_cuda_on_nvidia(rig):
    env = spec(rig, '[services.fake-ok]\naccel = "cuda"\n', machine_name="linux-nvidia-1gpu")
    assert (env["GAIFA_DEVICE"], env["GAIFA_GPU_ARCH"]) == ("cuda", "sm_89")


def test_bad_variant_key_is_a_manifest_error(rig):
    d = rig.add("fake-ok", as_id="fake-bad")
    (d / "service.toml").write_text((d / "service.toml").read_text() + '\n[run.variants.metal]\nenv = {}\n')
    mod = next(m for m in mf.discover([rig.services]) if m.id == "fake-bad")
    assert mod.errors and "variants" in mod.errors[0]


async def test_a_variant_this_machine_lacks_is_unavailable(rig, monkeypatch):
    monkeypatch.setattr(hardware, "detect", lambda refresh=False: machine("strix-halo"))
    rig.add("fake-ok")
    rig.config('[services.fake-ok]\naccel = "cuda"\n')
    mgr = await rig.manager(autostart=True)
    svc = mgr.get("fake-ok")
    from utils.tests.services.conftest import until
    await until(lambda: svc.last_error is not None)          # autostart runs in the background
    assert svc.state == "stopped" and svc.last_error.startswith("unavailable: its variant (cuda)")
    with pytest.raises(ServiceError) as e:
        await mgr.start("fake-ok")
    assert e.value.code == "unavailable" and e.value.status == 409
    from utils.services.views import summary
    s = summary(mgr, svc)
    assert s["accel"] == "cuda" and "gaifa setup fake-ok" in s["unavailable"]
