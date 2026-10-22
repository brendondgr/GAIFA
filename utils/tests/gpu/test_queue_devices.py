"""36.3: one GPU slot per device; the GPU a lease is for; the environment that shows a mod one GPU."""

from __future__ import annotations

import json
from pathlib import Path

from utils import hardware
from utils.events import EventBus
from utils.gpu import GpuQueue

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"


def machine(name: str) -> hardware.Machine:
    return hardware.from_snapshot(json.loads((FIX / f"{name}.json").read_text()))


def test_two_devices_run_two_jobs():
    q = GpuQueue(EventBus())
    a = q.register("comfy", label="image", device=0)
    b = q.register("gen3d", label="mesh", device=1)
    c = q.register("tts", label="speech", device=0)
    assert (a.state, b.state, c.state) == ("held", "held", "waiting")
    assert q.groups == {0: "comfy", 1: "gen3d"} and q.group == "comfy"
    assert [x["service"] for x in q.ahead_of(c)] == ["comfy"]            # gen3d's card isn't in its way
    v = q.view()
    assert v["holder"]["group"] == "comfy" and [x["service"] for x in v["waiting"]] == ["tts"]
    assert v["devices"] == [{"device": 1, "holder": {"group": "gen3d", "leases": [q.lease_view(b)]}, "waiting": []}]
    q.release(a.id)
    assert c.state == "held" and q.groups == {0: "tts", 1: "gen3d"}
    q.release(b.id)
    assert q.groups == {0: "tts"} and "devices" not in q.view()


def test_nested_work_stays_on_its_parents_device():
    q = GpuQueue(EventBus())
    parent = q.register("gen3d", label="make 3D", device=1)
    child = q.register("comfy", label="TRELLIS", parent=parent.id)          # no device: its parent's
    assert child.state == "held" and child.device == 1
    assert q.view()["holder"] is None


def test_renew_reregisters_on_its_device():
    q = GpuQueue(EventBus())
    q.register("comfy", label="image", device=1)
    lease = q.renew("gl_lost", {"service": "tts", "class": "job", "label": "speech", "device": 0})
    assert lease.state == "held" and lease.device == 0


def test_one_device_is_the_old_queue():
    q = GpuQueue(EventBus())
    a, b = q.register("comfy"), q.register("gen3d")
    assert (a.state, b.state, q.group) == ("held", "waiting", "comfy") and "devices" not in q.view()


def test_visible_env_per_vendor():
    two = machine("linux-nvidia-2gpu")
    assert two.visible_env(1) == {"AIHUB_GPU_INDEX": "1", "CUDA_VISIBLE_DEVICES": "1"}
    assert two.visible_env(2) == {"AIHUB_GPU_INDEX": "2", "ONEAPI_DEVICE_SELECTOR": "level_zero:0", "ZE_AFFINITY_MASK": "0"}
    assert [g.index for g in two.compute_gpus()] == [0, 1]                 # the iGPU has no Level Zero
    strix = machine("strix-halo")
    assert strix.visible_env(0) == {"AIHUB_GPU_INDEX": "0", "HIP_VISIBLE_DEVICES": "0"} and len(strix.compute_gpus()) == 1
    assert strix.visible_env(5) == {}


from utils.tests.services.conftest import rig  # noqa: E402,F401 (a fixture)


def test_launch_env_only_with_a_choice(rig):  # noqa: F811
    from utils import config, manifest as mf

    rig.add("fake-ok")
    rig.config("[services.fake-ok]\ngpu = 1\n")
    rig.write_config()
    cfg = config.load(rig.root / "config.toml")
    paths = config.build_paths(cfg, rig.root)
    mod = next(m for m in mf.discover([rig.root / "services"]) if m.id == "fake-ok")
    env = mf.launch_spec(mod, cfg, paths, 7000, machine=machine("linux-nvidia-2gpu")).env
    assert env["CUDA_VISIBLE_DEVICES"] == "1" and env["AIHUB_GPU_INDEX"] == "1"
    env = mf.launch_spec(mod, cfg, paths, 7000, machine=machine("strix-halo")).env
    assert "HIP_VISIBLE_DEVICES" not in env and "AIHUB_GPU_INDEX" not in env       # one GPU: nothing to choose
    assert mf.effective(mod, cfg).as_dict().get("gpu") is None                    # not part of ServiceConfig
