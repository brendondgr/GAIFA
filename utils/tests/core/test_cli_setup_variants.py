"""38.2: `aihub setup` picks each setup's variant for the machine: per fixture, --accel, a setup this
machine can't run (and what needs it), untested variants, the steps' environment and the recorded choice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import cli, cli_setup, hardware
from utils.tests.core.test_cli_setup import AGENT, RELAY, FakeProbe, FakeRunner, args, block, out, root  # noqa: F401 (root is a fixture)

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"
TTS3 = block("tts-kokoro", "Kokoro", summary='"Speech"', disk_gb="14", check='"aihub check tts"', smoke='"scripts/smoke.sh"',
             _tables='[[steps]]\nrun = "aihub install tts"\nwhat = "the server venv"\n\n'
                     '[[variants]]\naccel = "rocm"\ntested = true\nenv = { TTS_FAST = "1" }\nsteps = [ { run = "scripts/install-runtime.sh --accel rocm", what = "ROCm wheels" } ]\n\n'
                     '[[variants]]\naccel = "cuda"\nos = ["linux", "wsl"]\nsteps = [ { run = "scripts/install-runtime.sh --accel cuda", what = "CUDA wheels" } ]\n\n'
                     '[[variants]]\naccel = "cpu"\nos = ["linux", "wsl", "darwin"]\ntested = ["linux"]\nnote = "slower"\nsteps = [ { run = "scripts/install-runtime.sh --accel cpu", what = "CPU wheels" } ]')
ROCM_ONLY = block("gen3d", "3D", summary='"3D"', disk_gb="5", _tables='[[variants]]\naccel = "rocm"\ntested = true')
NEEDS_3D = block("gen3d-cube", "Cube3D", summary='"Cube"', disk_gb="1", after='["gen3d"]', _tables='[[steps]]\nrun = "true"\nwhat = "x"')


class Probe(FakeProbe):
    def __init__(self, machine: str = "strix-halo", **kw) -> None:
        super().__init__(**kw)
        self.name = machine

    def machine(self):
        return hardware.from_snapshot(json.loads((FIX / f"{self.name}.json").read_text()))


@pytest.fixture
def root3(root: Path) -> Path:  # noqa: F811
    (root / "services" / "tts" / "setup" / "env.md").write_text(TTS3)
    for mod, text in (("gen3d", ROCM_ONLY), ("gen3dcube", NEEDS_3D)):
        d = root / "services" / mod / "setup"
        d.mkdir(parents=True)
        (d.parent / "service.toml").write_text(f'id = "{mod}"\n')
        (d / "env.md").write_text(text)
    return root


def plan(capsys, *targets, probe=None, **kw) -> dict:
    assert cli_setup.cmd_setup(args(*targets, plan=True, **kw), FakeRunner(), probe or Probe()) == 0
    return out(capsys)


def test_each_machine_gets_its_variant(root3, capsys):
    p = plan(capsys, "tts")
    assert [(v["setup"], v["accel"], v["untested"]) for v in p["variants"]] == [("tts-kokoro", "rocm", False)]
    assert [s["run"] for s in p["steps"]] == ["scripts/install-runtime.sh --accel rocm"]
    p = plan(capsys, "tts", probe=Probe("linux-nvidia-1gpu"))
    assert [(v["accel"], v["untested"]) for v in p["variants"]] == [("cuda", True)]
    p = plan(capsys, "tts", probe=Probe("macos-m3"))
    assert [(v["accel"], v["untested"], v["note"]) for v in p["variants"]] == [("cpu", True, "slower")]
    p = plan(capsys, "tts", "relay", probe=Probe("wsl2-intel"))
    assert {v["setup"]: v["accel"] for v in p["variants"]} == {"relay": "cpu", "tts-kokoro": "cpu"}


def test_override_and_its_refusal(root3, capsys):
    p = plan(capsys, "tts", accel=["tts=cpu"])
    assert [v["accel"] for v in p["variants"]] == ["cpu"] and p["steps"][0]["run"].endswith("--accel cpu")
    assert cli_setup.cmd_setup(args("tts", plan=True, accel=["tts-kokoro=mps"]), FakeRunner(), Probe()) == 1
    r = out(capsys)
    assert r["reason"] == "unavailable" and "no mps variant for Linux" in r["unavailable"][0]["why"]


def test_a_setup_this_machine_cant_run_and_what_needs_it(root3, capsys):
    p = plan(capsys, "gen3dcube", "relay", probe=Probe("linux-nvidia-1gpu"))
    assert p["setups"] == ["relay"]
    assert [(u["setup"], u["why"]) for u in p["unavailable"]] == [
        ("gen3d", "it needs ROCm, and this machine has CUDA, Vulkan, CPU"), ("gen3d-cube", "it needs a setup this machine can't run")]
    assert cli_setup.cmd_setup(args("gen3d", plan=True, json=False), FakeRunner(), Probe("macos-m3")) == 1
    assert "doesn't run on macOS (only Linux)" in capsys.readouterr().out


def test_the_plan_text_names_variants(root3, capsys):
    assert cli_setup.cmd_setup(args("tts", plan=True, json=False), FakeRunner(), Probe("linux-nvidia-1gpu")) == 0
    text = capsys.readouterr().out
    assert "tts-kokoro               CUDA  [untested on this kind of machine]" in text


def test_steps_run_with_the_variant_env_and_the_choice_is_recorded(root3, capsys):
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", yes=True, smoke=True), runner, Probe()) == 0
    env = next(e for c, _, e in runner.ran if c == "scripts/install-runtime.sh --accel rocm")
    assert env == {"TTS_FAST": "1", "AIHUB_ACCEL": "rocm", "AIHUB_DEVICE": "cuda", "AIHUB_GPU_ARCH": "gfx1151"}
    assert ("PUT", "/api/services/tts/config", {"accel": "rocm", "env": {"TTS_FAST": "1"}}) in runner.calls
    r = out(capsys)
    assert r["smokes"] == [{"setup": "tts-kokoro", "run": "scripts/smoke.sh", "ok": True}]
    assert any(c == "scripts/smoke.sh" for c, _, _ in runner.ran)


def test_without_the_hub_the_choice_goes_into_config_toml(root3, capsys):
    runner = FakeRunner(refuse={"/api/services/tts/config"})
    assert cli_setup.cmd_setup(args("tts", yes=True), runner, Probe("linux-nvidia-1gpu")) == 0
    text = (root3 / "config.toml").read_text()
    assert '[services.tts]\naccel = "cuda"' in text
    assert any("restart the hub" in n for n in out(capsys)["next"])
