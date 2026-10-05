"""5.6: idle unload stays inside the mods; AIHub passes `idle_unload_s` in the mod's env (0 = never)."""

from __future__ import annotations

import tomllib

import httpx

from utils import config
from utils.manifest import discover, effective, launch_spec

MOD = """
id = "tts"
[run]
command = ["python3", "x.py"]
port = 5040
[memory]
estimate_gb = 9
load = "POST /v1/load"
unload = "POST /v1/unload"
idle_unload_s = 180
idle_unload_env = "LOCALTTS_IDLE_UNLOAD_S"
"""


def spec(tmp_path, cfg_text: str = "", mod: str = MOD):
    (tmp_path / "services/tts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services/tts/service.toml").write_text(mod)
    (tmp_path / "config.toml").write_text(cfg_text)
    cfg = config.load(tmp_path / "config.toml")
    [m] = discover([tmp_path / "services"])
    assert not m.errors, m.errors
    return effective(m, cfg), launch_spec(m, cfg, config.build_paths(cfg, tmp_path), 7000).env


def test_the_mods_default_reaches_its_env(tmp_path):
    eff, env = spec(tmp_path)
    assert eff.idle_unload_s == 180
    assert env["LOCALTTS_IDLE_UNLOAD_S"] == "180" and env["AIHUB_IDLE_UNLOAD_S"] == "180"


def test_config_overrides_and_zero_means_never(tmp_path):
    eff, env = spec(tmp_path, "[services.tts]\nidle_unload_s = 600\n")
    assert eff.idle_unload_s == 600 and env["LOCALTTS_IDLE_UNLOAD_S"] == "600"
    eff, env = spec(tmp_path, "[services.tts]\nidle_unload_s = 0\n")
    assert eff.idle_unload_s is None and env["LOCALTTS_IDLE_UNLOAD_S"] == "0"
    eff, env = spec(tmp_path, '[services.tts]\nenv = { LOCALTTS_IDLE_UNLOAD_S = "5" }\n')  # an explicit env wins
    assert env["LOCALTTS_IDLE_UNLOAD_S"] == "5"


def test_mods_without_memory_get_nothing_and_bad_names_are_errors(tmp_path):
    _, env = spec(tmp_path, mod='id = "tts"\n[run]\ncommand = ["x"]\nport = 5040\n')
    assert "AIHUB_IDLE_UNLOAD_S" not in env
    (tmp_path / "services/tts/service.toml").write_text(MOD.replace('"LOCALTTS_IDLE_UNLOAD_S"', '"BAD NAME"'))
    [m] = discover([tmp_path / "services"])
    assert any("not an environment variable name" in e for e in m.errors)


async def test_never_from_the_settings_tab(rig, serve):
    d = rig.add("fake-mem")
    with (d / "service.toml").open("a") as f:
        f.write('idle_unload_s = 300\nidle_unload_env = "FAKE_IDLE"\n')
    hub = await serve()
    cfg_file = rig.root / "config.toml"
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-mem/config", json={"idle_unload_s": None})  # the "Never" box
        assert r.json()["config"]["idle_unload_s"] is None and r.json()["restart_required"] is True
        assert tomllib.loads(cfg_file.read_text())["services"]["fake-mem"]["idle_unload_s"] == 0
        r = await c.put("/api/services/fake-mem/config", json={"idle_unload_s": 300})  # back to the default: no key
        assert r.json()["config"]["idle_unload_s"] == 300
        assert "idle_unload_s" not in tomllib.loads(cfg_file.read_text()).get("services", {}).get("fake-mem", {})
