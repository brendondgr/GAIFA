"""What AIHub needs from gen3d: dated job folders with output.json, the status route, the stages
widget, the documented POST /v1/jobs body, the worker mounts, and the job migration."""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gen3d.config import settings
from gen3d.server import app
from gen3d.store import Store, job_folder, output_meta

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def wait(c, jid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/v1/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "canceled"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {jid} still running")


def test_a_job_lives_in_a_dated_folder_with_output_json(c):
    job = c.post("/v1/jobs", json={"prompt": "Low-poly Fox!", "stages": ["shape", "parts", "rig", "preview"],
                                   "parts": {"parts": ["head", "body"]}}).json()
    folder = settings.jobs_dir / time.strftime("%Y-%m-%d") / f"{job['id']}-low-poly-fox"
    assert folder.is_dir()
    done = wait(c, job["id"])
    meta = json.loads((folder / "output.json").read_text())
    assert meta["complete"] is True and meta["kind"] == "model3d" and meta["main"] == "rigged.glb"
    assert meta["preview"] == "preview.png" and meta["title"] == "Low-poly Fox!" and meta["prompt"] == "Low-poly Fox!"
    assert meta["source"]["job_id"] == job["id"] and meta["params"]["stages"] == ["shape", "parts", "rig", "preview"]
    assert "output.json" in done["files"]
    assert c.get(f"/v1/jobs/{job['id']}/files/rigged.glb").content[:4] == b"glTF"


def test_a_cancelled_or_failed_job_is_not_complete(c):
    job = c.post("/v1/jobs", json={"prompt": "slow thing", "stages": ["shape", "parts"], "parts": {"parts": ["a"]}}).json()
    c.post(f"/v1/jobs/{job['id']}/cancel")
    wait(c, job["id"])
    store = app.state.store
    meta = json.loads((store.job_dir(job["id"]) / "output.json").read_text())
    assert meta["complete"] is False and meta["status"] == "canceled"


def test_an_upload_goes_in_a_dated_folder_too(c):
    from gen3d.glb import boxes_glb
    glb = boxes_glb([{"name": "m", "center": (0, 0, 0), "size": (1, 1, 1)}])
    r = c.post("/v1/jobs/upload", files={"mesh": ("chair.glb", glb)}, data={"job": '{"stages": ["parts"], "parts": {"parts": ["seat"]}}'})
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    assert app.state.store.job_dir(jid).name == f"{jid}-chair"
    assert (app.state.store.job_dir(jid) / "input.glb").is_file()
    wait(c, jid)


def test_status_has_the_aihub_shape(c):
    job = c.post("/v1/jobs", json={"prompt": "status probe", "stages": ["shape"]}).json()
    s = c.get("/v1/status").json()
    assert [x["label"] for x in s["stats"]] == ["Jobs", "Queue", "Avg time", "Previews"]
    assert set(s) >= {"loaded", "busy", "idle_s", "jobs"}
    mine = [j for j in s["jobs"] if j["id"] == job["id"]]
    assert mine and mine[0]["route"] == f"#/s/gen3d/jobs?id={job['id']}" and mine[0]["state"] in ("queued", "running", "done")
    wait(c, job["id"])
    after = [j for j in c.get("/v1/status").json()["jobs"] if j["id"] == job["id"]]
    assert after and after[0]["state"] == "done" and after[0]["progress"] == 1.0


def test_the_stages_widget_is_widget_data(c):
    wait(c, c.post("/v1/jobs", json={"prompt": "widget", "stages": ["shape", "preview"]}).json()["id"])
    w = c.get("/v1/hub/widgets/stages?range=7d").json()
    assert w["unit"] == "seconds" and w["categories"]
    assert {s["name"] for s in w["series"]} <= {"shape", "parts", "rig", "preview"}
    assert all(len(s["values"]) == len(w["categories"]) for s in w["series"])
    assert c.get("/v1/hub/widgets/stages?range=1h").status_code == 422


def test_post_jobs_documents_its_body(c):
    op = c.get("/openapi.json").json()["paths"]["/v1/jobs"]["post"]
    assert "requestBody" in op
    assert c.post("/v1/jobs", json={"stages": ["shape"]}).status_code == 422  # shape needs a prompt


def test_worker_mounts_the_jobs_folder_and_the_weights_read_only(monkeypatch, tmp_path):
    from gen3d import worker
    s = settings.__class__(**{**settings.__dict__, "outputs": str(tmp_path / "out"), "weights_dir": str(tmp_path / "w")})
    monkeypatch.setattr(worker, "settings", s)
    w = worker.CubeWorker()
    w.name = "gen3d-worker-test"
    cmd = w.command()
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert f"{tmp_path / 'out'}:{tmp_path / 'out'}" in mounts
    assert f"{tmp_path / 'w'}:{tmp_path / 'w'}:ro" in mounts
    assert not any(m.startswith(str(settings.data)) for m in mounts)
    assert f"GEN3D_WEIGHTS={tmp_path / 'w'}" in cmd


def test_output_meta_picks_the_newest_glb(tmp_path):
    for f in ("mesh.glb", "parts.glb"):
        (tmp_path / f).write_bytes(b"glTF")
    job = {"id": "j_1", "title": "t", "status": "done", "created": 1.0, "request": {"stages": ["shape", "parts"]},
           "result": {"shape": {"peak_gpu_gb": 10.5}, "parts": {"peak_gpu_gb": 29.9}}}
    m = output_meta(job, tmp_path)
    assert m["main"] == "parts.glb" and m["peak_gpu_gb"] == 29.9 and "preview" not in m
    job["status"] = "failed"
    assert output_meta(job, tmp_path)["complete"] is False


def test_migration_moves_old_folders_and_rewrites_paths(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from migrate_jobs_to_outputs import migrate
    db, old, out = tmp_path / "g.db", tmp_path / "jobs", tmp_path / "outputs"
    store = Store(db_path=db, jobs_dir=old)
    created = time.mktime((2026, 9, 20, 12, 0, 0, 0, 0, -1))
    jid = "j_old0000001"
    store._q("INSERT INTO jobs (id, title, status, request, stages, result, created) VALUES (?,?,?,?,?,?,?)",
             (jid, "Pirate's Chest", "done", json.dumps({"prompt": "Pirate's Chest", "stages": ["shape", "parts"]}),
              "{}", json.dumps({"shape": {"mesh": "mesh.glb"}}), created))
    store.close()
    (old / jid / "parts").mkdir(parents=True)
    (old / jid / "mesh.glb").write_bytes(b"glTF")
    (old / jid / "parts" / "manifest.json").write_text(json.dumps({"source_mesh": str(old / jid / "mesh.glb")}))
    (old / "j_orphan").mkdir()
    child = "j_child00001"  # a parts job whose manifest points at its parent's mesh
    store = Store(db_path=db, jobs_dir=old)
    store._q("INSERT INTO jobs (id, title, status, request, stages, result, created, parent_id) VALUES (?,?,?,?,?,?,?,?)",
             (child, "parts", "done", json.dumps({"stages": ["parts"]}), "{}", "{}", created + 60, jid))
    store.close()
    (old / child / "parts").mkdir(parents=True)
    (old / child / "parts.glb").write_bytes(b"glTF")
    (old / child / "parts" / "manifest.json").write_text(json.dumps({"source_mesh": str(old / jid / "mesh.glb")}))
    r = migrate(db, old, out)
    dst = out / "2026-09-20" / f"{jid}-pirate-s-chest"
    assert r["moved"][0] == (jid, str(old / jid), str(dst)) and r["orphans"] == ["j_orphan"]
    child_dst = Path(r["moved"][1][2])
    assert json.loads((child_dst / "parts" / "manifest.json").read_text())["source_mesh"] == str(dst / "mesh.glb")
    assert json.loads((dst / "parts" / "manifest.json").read_text())["source_mesh"] == str(dst / "mesh.glb")
    meta = json.loads((dst / "output.json").read_text())
    assert meta["complete"] is True and meta["main"] == "mesh.glb" and meta["created_ts"] == created
    assert sqlite3.connect(db).execute("SELECT dir FROM jobs WHERE id=?", (jid,)).fetchone()[0] == f"2026-09-20/{jid}-pirate-s-chest"
    assert migrate(db, old, out)["moved"] == []  # a second run does nothing


def test_job_folder_name():
    assert job_folder("j_1", "A  b/c!", time.mktime((2026, 1, 2, 3, 4, 5, 0, 0, -1))) == "2026-01-02/j_1-a-b-c"
    assert job_folder("j_1", None).endswith("/j_1-job")


def test_idle_unload_never_stops_a_worker_that_is_loading(c, monkeypatch):
    """A load after a long idle spell: the idle unloader ran mid-load and killed the worker (2026-10-06)."""
    import asyncio

    r = c.app.state.runner
    r.last_activity = time.monotonic() - 10_000          # idle for hours
    seen = {}
    real_load = r.worker.load

    async def slow_load(wanted):
        await real_load(wanted)
        await r._maybe_idle_unload()                      # the idle check fires while loading
        seen["up"] = r.worker.up

    monkeypatch.setattr(r.worker, "load", slow_load)
    assert c.post("/v1/load").status_code == 200
    assert seen["up"] is True
