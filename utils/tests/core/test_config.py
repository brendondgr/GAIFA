from pathlib import Path

import pytest

from utils import config
from utils.config import Config, ConfigError

ROOT_CONFIG = Path(__file__).resolve().parents[3] / "config.toml"


def test_missing_file_gives_defaults(tmp_path):
    cfg = config.load(tmp_path / "config.toml")
    assert cfg == Config()
    assert cfg.hub.port == 7000 and cfg.hub.host == "127.0.0.1"
    assert cfg.memory.never_unload == ["lcpp"]
    assert cfg.ports.new_mods == (5100, 5199)


def test_shipped_config_is_valid():
    cfg = config.load(ROOT_CONFIG)
    assert cfg.services.overrides["tts"].idle_unload_s == 180
    assert cfg.services.order[0] == "relay"


@pytest.mark.parametrize(
    "toml, key",
    [
        ("[hub]\nport = 70000\n", "hub.port"),
        ("[memory]\nreserve_gb = 'lots'\n", "memory.reserve_gb"),
        ("[ui]\ntheme = 'neon'\n", "ui.theme"),
        ("[services.tts]\nport = 'x'\n", "services.tts.port"),
        ("[services.tts]\nidle_unlaod_s = 5\n", "services.tts.idle_unlaod_s"),
        ("[ports]\nnew_mods = [5199, 5100]\n", "ports.new_mods"),
        ("[bogus]\nx = 1\n", "bogus"),
    ],
)
def test_invalid_values_name_the_key(tmp_path, toml, key):
    f = tmp_path / "config.toml"
    f.write_text(toml)
    with pytest.raises(ConfigError) as e:
        config.load(f)
    assert f"{key}:" in str(e.value)
    assert str(e.value).startswith("config.toml: ")


def test_bad_toml(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("[hub\n")
    with pytest.raises(ConfigError, match="not valid TOML"):
        config.load(f)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
def test_non_loopback_host_refused(tmp_path, host):
    f = tmp_path / "config.toml"
    f.write_text(f'[hub]\nhost = "{host}"\n')
    with pytest.raises(ConfigError, match="hub.host: .*not loopback"):
        config.load(f)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_loopback_hosts_accepted(tmp_path, host):
    f = tmp_path / "config.toml"
    f.write_text(f'[hub]\nhost = "{host}"\n')
    assert config.load(f).hub.host == host


def test_save_round_trip_keeps_comments_and_order(tmp_path):
    f = tmp_path / "config.toml"
    original = ROOT_CONFIG.read_text()
    f.write_text(original)
    cfg = config.save(f, {"memory": {"reserve_gb": 16}, "services": {"tts": {"autostart": False}}})
    assert cfg.memory.reserve_gb == 16
    assert cfg.services.overrides["tts"].autostart is False
    text = f.read_text()
    assert "# loopback only; anything else is refused at startup" in text
    assert "reserve_gb = 16" in text
    # Only the changed lines differ.
    diff = [(a, b) for a, b in zip(original.splitlines(), text.splitlines()) if a != b]
    assert diff == [("reserve_gb = 12", "reserve_gb = 16"), ("autostart = true", "autostart = false")]


def test_save_adds_new_tables(tmp_path):
    f = tmp_path / "config.toml"
    cfg = config.save(f, {"services": {"lcpp": {"port": 7711}}})
    assert cfg.services.overrides["lcpp"].port == 7711
    assert config.load(f) == cfg


def test_save_invalid_leaves_file_unchanged(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("# keep me\n[hub]\nport = 7000\n")
    before = f.read_text()
    with pytest.raises(ConfigError, match="hub.host"):
        config.save(f, {"hub": {"host": "0.0.0.0"}})
    assert f.read_text() == before


def test_service_override_merges_over_manifest():
    cfg = config.validate(
        {"services": {"tts": {"port": 5041, "env": {"B": "2"}, "autostart": False}}}
    )
    manifest = {"port": 5040, "env": {"A": "1", "B": "1"}, "enabled": True, "autostart": True}
    merged = cfg.service_override("tts", manifest)
    assert merged == {"port": 5041, "env": {"A": "1", "B": "2"}, "enabled": True, "autostart": False}
    assert manifest["env"] == {"A": "1", "B": "1"}  # defaults untouched
    assert cfg.service_override("gen3d", manifest) == manifest


def test_build_paths_rejects_outside_root(tmp_path):
    cfg = config.validate({"paths": {"models": "/mnt/elsewhere"}})
    with pytest.raises(ConfigError, match="paths.models"):
        config.build_paths(cfg, tmp_path)


def test_save_none_removes_and_replace_swaps_tables(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('# top\n[services.tts]  # tts\nidle_unload_s = 180\nenv = { A = "1", B = "2" }\n')
    config.save(p, {"services": {"tts": {"idle_unload_s": None, "env": config.Replace({"C": "3"})}}})
    text = p.read_text()
    assert "# top" in text and "# tts" in text
    cfg = config.load(p)
    ov = cfg.services.overrides["tts"]
    assert ov.idle_unload_s is None and ov.env == {"C": "3"}
    config.save(p, {"services": {"tts": {"env": config.Replace(None), "missing": None}}})
    assert "tts" not in config.load(p).services.overrides  # its last key went, so the table did too
    assert "[services.tts]" not in p.read_text() and "# top" in p.read_text()
    config.save(p, {"services": {"new": {"enabled": None}}})
    assert "[services.new]" not in p.read_text()  # no empty tables
