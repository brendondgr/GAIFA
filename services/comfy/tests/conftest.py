import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfy.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    env = {"COMFY_DATA": str(tmp_path / "data"), "COMFY_OUTPUTS": str(tmp_path / "out"),
           "COMFY_WORKFLOWS": str(tmp_path / "workflows"), "COMFY_VIEW": str(tmp_path / "view"),
           "COMFY_URL": "http://127.0.0.1:1", "COMFY_CONTROL": "/bin/true", "COMFY_QUIT_ON_EXIT": "0",
           "COMFY_INPUT": str(tmp_path / "input"), "COMFY_MODELS": str(tmp_path / "models")}
    return Settings.from_env(env)


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    from comfy import control, run
    monkeypatch.setattr(control, "POLL_S", 0.05)
    monkeypatch.setattr(run, "LOOP_S", 0.1)


REAL_CONTROL = (Path(__file__).resolve().parents[1] / "bin" / "comfyui").resolve()


@pytest.fixture(autouse=True)
def never_the_real_comfyui(monkeypatch):
    """Tests must never run the real bin/comfyui: it would start or stop the user's ComfyUI."""
    from comfy import control
    real = control.Controller._script
    tried: list[str] = []

    async def guarded(self, *args, **kw):
        if Path(self.control).resolve() == REAL_CONTROL:
            tried.append(" ".join(args))
            return 1, "blocked in tests"
        return await real(self, *args, **kw)
    monkeypatch.setattr(control.Controller, "_script", guarded)
    yield
    assert not tried, f"a test tried to run the real bin/comfyui: {tried}"
