"""The page's settings (prefs.py): GET/PUT /v1/settings validates and saves the preview device in
settings.json, the saved choice beats GEN3D_PREVIEW_DEVICE, and the next preview uses it without a restart.
Blender never runs: the subprocess is replaced."""

import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from gen3d import prefs, preview
from gen3d.server import app


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "settings", replace(prefs.settings, state_dir=str(tmp_path / "state" / "gen3d"),
                                                   preview_device="cpu"))
    return tmp_path / "state" / "gen3d" / "settings.json"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def test_nothing_saved_means_cpu(c, state):
    assert c.get("/v1/settings").json() == {"preview_device": "cpu", "saved": False, "default": "cpu", "choices": ["cpu", "gpu"]}
    stat = {s["label"]: s["value"] for s in c.get("/v1/status").json()["stats"]}
    assert stat["Previews"] == "CPU"
    assert not state.exists()


@pytest.mark.parametrize("body", [{"preview_device": "cuda"}, {"preview_device": 1}, {"preview_device": "gpu", "x": 1}, []])
def test_bad_values_are_refused_and_nothing_is_written(c, state, body):
    assert c.put("/v1/settings", json=body).status_code == 422
    assert not state.exists()


def test_a_choice_is_saved_and_can_be_forgotten(c, state):
    r = c.put("/v1/settings", json={"preview_device": "gpu"})
    assert r.status_code == 200 and r.json()["preview_device"] == "gpu" and r.json()["saved"] is True
    assert json.loads(state.read_text()) == {"preview_device": "gpu"}
    assert [p.name for p in state.parent.iterdir()] == ["settings.json"]          # no temporary file left
    assert c.get("/v1/settings").json()["preview_device"] == "gpu"
    assert {s["label"]: s["value"] for s in c.get("/v1/status").json()["stats"]}["Previews"] == "GPU"
    assert c.put("/v1/settings", json={}).json()["preview_device"] == "gpu"      # nothing to change
    r = c.put("/v1/settings", json={"preview_device": None})
    assert r.json() == {"preview_device": "cpu", "saved": False, "default": "cpu", "choices": ["cpu", "gpu"]}
    assert json.loads(state.read_text()) == {}


def test_saved_choice_beats_the_env_default_and_a_broken_file_does_not(state, monkeypatch):
    monkeypatch.setattr(prefs, "settings", replace(prefs.settings, preview_device="gpu"))   # GEN3D_PREVIEW_DEVICE=gpu
    assert prefs.preview_device() == "gpu"
    state.parent.mkdir(parents=True)
    state.write_text('{"preview_device": "cpu"}')
    assert prefs.preview_device() == "cpu"
    for junk in ("{not json", '["gpu"]', '{"preview_device": "cuda"}', " " * (prefs.MAX_BYTES + 1)):
        state.write_text(junk)
        assert prefs.preview_device() == "gpu"


def test_next_preview_uses_the_saved_device_without_a_restart(c, state, tmp_path, monkeypatch):
    runs = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def spawn(*cmd, env=None, **kw):
        runs.append((list(cmd), env))
        (tmp_path / "preview.png").write_bytes(b"png")
        return Proc()

    monkeypatch.setattr(preview, "blender", lambda: "/bin/blender")
    monkeypatch.setattr(preview.asyncio, "create_subprocess_exec", spawn)
    glb = tmp_path / "mesh.obj"
    glb.write_text("v 0 0 0\n")

    def render():
        asyncio.run(preview.render_preview(tmp_path, glb, tmp_path / "preview.png"))
        cmd, env = runs[-1]
        return cmd[cmd.index("--device") + 1], env

    device, env = render()
    assert device == "cpu" and env["LIBGL_ALWAYS_SOFTWARE"] == "1" and "--gpu-backend" in runs[-1][0]
    c.put("/v1/settings", json={"preview_device": "gpu"})
    device, env = render()
    assert device == "gpu" and "--gpu-backend" not in runs[-1][0]
    c.put("/v1/settings", json={"preview_device": "cpu"})
    assert render()[0] == "cpu"
