import time

import pytest
from fastapi.testclient import TestClient

from comfy.config import Settings
from comfy.server import create_app
from fakecomfy import FakeComfy, fake_control

INFO = {"KSampler": {"input": {"required": {"seed": ["INT", {"default": 0}]}}, "output": ["LATENT"], "output_node": False}}


@pytest.fixture
def fake():
    with FakeComfy(INFO, up=False) as f:
        yield f


def make(tmp_path, fake, **env) -> Settings:
    return Settings.from_env({"COMFY_DATA": str(tmp_path / "data"), "COMFY_OUTPUTS": str(tmp_path / "out"),
                              "COMFY_WORKFLOWS": str(tmp_path / "wf"), "COMFY_VIEW": str(tmp_path / "view"), "COMFY_URL": fake.url,
                              "COMFY_CONTROL": str(fake_control(tmp_path / "comfyui", fake.url)), **env})


def wait(cond, secs=5):
    t = time.monotonic()
    while time.monotonic() - t < secs:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_load_unload_and_status(tmp_path, fake):
    s = make(tmp_path, fake)
    with TestClient(create_app(s)) as c:
        assert c.get("/v1/status").json()["loaded"] is False
        assert c.post("/v1/load").json() == {"loaded": True}
        assert fake.up
        st = c.get("/v1/status").json()
        assert st["loaded"] is True and st["busy"] is False and st["idle_s"] is not None
        assert [x["label"] for x in st["stats"]] == ["Workflows", "Drafts", "Queue"]
        # the node catalog is fetched at load and cached on disk
        assert (s.data / "object_info.json").exists() and c.app.state.catalog.has("KSampler")
        assert c.post("/v1/unload").json() == {"loaded": False}
        assert fake.freed == 1 and not fake.up
        assert c.get("/v1/status").json()["loaded"] is False


def test_adopts_a_running_comfyui_and_reports_its_queue(tmp_path, fake):
    fake.up = True
    fake.queue_running = [[1, "abc", {}, {}, []]]
    with TestClient(create_app(make(tmp_path, fake))) as c:
        assert wait(lambda: (lambda s: s["loaded"] and s["busy"])(c.get("/v1/status").json()))
        st = c.get("/v1/status").json()
        assert st["busy"] is True and st["jobs"][0]["state"] == "running"
        assert {x["label"]: x["value"] for x in st["stats"]}["Queue"] == 1
    assert fake.up, "a busy ComfyUI is left running when the adapter stops"


def test_idle_unload(tmp_path, fake):
    fake.up = True
    with TestClient(create_app(make(tmp_path, fake, COMFY_IDLE_UNLOAD_S="0.3"))) as c:
        assert wait(lambda: fake.freed == 1 and not fake.up, secs=8)
        assert c.get("/v1/status").json()["loaded"] is False


def test_quits_an_idle_comfyui_when_the_adapter_stops(tmp_path, fake):
    fake.up = True
    with TestClient(create_app(make(tmp_path, fake))):
        pass
    assert not fake.up


def test_load_failure_is_reported(tmp_path, fake):
    s = make(tmp_path, fake)
    (tmp_path / "comfyui").write_text("#!/bin/sh\necho boom\nexit 3\n")
    with TestClient(create_app(s)) as c:
        r = c.post("/v1/load")
        assert r.status_code == 503 and "boom" in r.json()["detail"]
