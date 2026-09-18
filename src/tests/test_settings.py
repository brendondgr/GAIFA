import json

import pytest

from lcpp import settings
from lcpp.settings import SettingsError


def test_load_merges_defaults(home):
    s = settings.load(home)
    assert s["daemon"]["port"] == 7700
    assert s["llama"]["server_params"]["jinja"] is True
    assert s["relay"]["url"] == "http://127.0.0.1:4000"
    assert s["scan_dirs"] == ["models", "extra"]


def test_missing_file_gives_defaults(home):
    home.settings_file.unlink()
    assert settings.load(home) == settings.DEFAULTS


@pytest.mark.parametrize("patch, field", [
    ({"daemon": {"port": 80}}, "daemon.port"),
    ({"ports": {"start": 9000, "end": 8000}}, "ports"),
    ({"relay": {"url": "localhost:4000"}}, "relay.url"),
    ({"scan_dirs": "models"}, "scan_dirs"),
    ({"hostname": "0.0.0.0"}, "hostname"),
])
def test_validation_errors(home, patch, field):
    raw = json.loads(home.settings_file.read_text())
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(raw.get(k), dict):
            raw[k].update(v)
        else:
            raw[k] = v
    with pytest.raises(SettingsError) as e:
        settings.validate(raw)
    assert e.value.field == field


def test_save_roundtrip_is_atomic_and_normalized(home):
    s = settings.load(home)
    s["relay"]["url"] = "http://127.0.0.1:4001/"
    s["llama"]["server_params"]["--threads"] = 8
    saved = settings.save(home, s)
    assert saved["relay"]["url"] == "http://127.0.0.1:4001"
    assert saved["llama"]["server_params"]["threads"] == 8
    assert settings.load(home) == saved
    assert not list(home.data.glob(".*.tmp"))
