"""Plan 45.3: a job's `live`: stages with their state and time left, the running stage's steps, and the cut-out
then the rendered views as its preview; on /v1/jobs/{id} and the status jobs."""

import time
from pathlib import Path

from gen3d.live import live_of
from test_gaifa import c, wait  # noqa: F401 - the fixture


def test_live_of_a_running_image_job(tmp_path: Path):
    job = {"id": "j_1", "status": "running", "stages": {"shape": {"state": "running", "step": 30, "total": 100}, "preview": {"state": "pending"}}}
    sched = {"eta_s": 42.0, "by_stage": {"shape": 30.0, "preview": 12.0}}
    (tmp_path / "input_rgba.png").write_bytes(b"x")
    lv = live_of(job, sched, tmp_path)
    assert lv["stage"] == "shape" and (lv["step"], lv["steps"]) == (30, 100) and lv["eta_s"] == 42.0
    assert lv["stages"] == [{"id": "shape", "label": "Shape", "state": "running", "eta_s": 30.0},
                            {"id": "preview", "label": "Views", "state": "waiting", "eta_s": 12.0}]
    assert lv["preview"] == {"url": "/v1/jobs/j_1/files/input_rgba.png", "seq": 1}
    (tmp_path / "preview.png").write_bytes(b"x")
    assert live_of(job, sched, tmp_path)["preview"] == {"url": "/v1/jobs/j_1/files/preview.png", "seq": 2}
    assert live_of({**job, "status": "queued"}, None, None)["stage"] == "queued"
    assert live_of({**job, "status": "done"}, sched, tmp_path) is None


def test_a_jobs_live_through_the_api(c):  # noqa: F811
    jid = c.post("/v1/jobs", json={"prompt": "a fox", "stages": ["shape", "preview"]}).json()["id"]
    seen, end = None, time.time() + 20
    while time.time() < end and seen is None:
        j = c.get(f"/v1/jobs/{jid}").json()
        if j.get("live"):
            seen = j["live"]
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert seen and {s["id"] for s in seen["stages"]} == {"shape", "preview"}
    done = wait(c, jid)
    assert "live" not in done
