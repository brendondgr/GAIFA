from fastapi.testclient import TestClient

from comfy.db import DB
from comfy.server import create_app


def test_health_and_status(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").json() == {"status": "ok"}
        s = c.get("/v1/status").json()
        assert set(s) >= {"loaded", "busy", "idle_s", "stats", "jobs"}
    assert settings.db.exists()


def test_db_runs_and_defaults(tmp_path):
    db = DB(tmp_path / "c.db")
    db.add_run("r1", "zimage", "a fox", {"prompt": "a fox"})
    db.update_run("r1", state="done", peak_gb=17.5, finished=1.0, outputs=[{"path": "x.png", "kind": "image"}])
    r = db.run("r1")
    assert r["inputs"] == {"prompt": "a fox"} and r["outputs"][0]["kind"] == "image"
    assert db.peak_gb("zimage") == 17.5
    assert [x["id"] for x in db.runs(states=("done",))] == ["r1"]
    db.set_default("text-to-image", "zimage")
    assert db.defaults() == {"text-to-image": "zimage"}
    db.set_default("text-to-image", None)
    assert db.defaults() == {}
