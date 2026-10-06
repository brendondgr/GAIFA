import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfy.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    env = {"COMFY_DATA": str(tmp_path / "data"), "COMFY_OUTPUTS": str(tmp_path / "out"),
           "COMFY_WORKFLOWS": str(tmp_path / "workflows"), "COMFY_VIEW": str(tmp_path / "view"),
           "COMFY_URL": "http://127.0.0.1:1"}
    return Settings.from_env(env)


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    from comfy import control
    monkeypatch.setattr(control, "POLL_S", 0.05)
