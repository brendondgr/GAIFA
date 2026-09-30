import io
import time

import pytest
from fastapi.testclient import TestClient

from gen3d.glb import boxes_glb
from gen3d.server import app

PARTS = ["base", "torso cushion", "head cushion", "left arm board"]


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
    raise AssertionError(f"job {jid} still {j['status']}")


def test_health_and_options(c):
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["fake_worker"] is True
    assert c.get("/v1/options").json()["max_parts"] == 8


def test_full_pipeline_in_new_chat(c):
    r = c.post("/v1/jobs", json={"prompt": "surgeon chair", "chat_id": "new",
                                 "stages": ["shape", "parts", "rig", "preview"], "parts": {"parts": PARTS}})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["eta"]["eta_s"] > 0 and job["chat_id"].startswith("c_")
    done = wait(c, job["id"])
    assert done["status"] == "done", done
    assert {"mesh.glb", "parts.glb", "rigged.glb", "rig.json", "preview.png"} <= set(done["files"])
    assert [p["name"] for p in done["result"]["parts"]["parts"]] == PARTS
    assert all(v["state"] == "done" for v in done["stages"].values())
    assert c.get(f"/v1/jobs/{job['id']}/files/mesh.glb").content[:4] == b"glTF"
    z = c.get(f"/v1/jobs/{job['id']}/download")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    chat = c.get(f"/v1/chats/{job['chat_id']}").json()
    assert chat["title"] == "surgeon chair" and chat["jobs"][0]["id"] == job["id"]


def test_continue_from_parent_splits_its_mesh(c):
    shape = wait(c, c.post("/v1/jobs", json={"prompt": "robot", "stages": ["shape"]}).json()["id"])
    child = c.post("/v1/jobs", json={"parent_id": shape["id"], "stages": ["parts", "rig"],
                                     "parts": {"parts": ["head", "body"]}}).json()
    done = wait(c, child["id"])
    assert done["status"] == "done", done
    assert "mesh.glb" not in done["files"] and "rigged.glb" in done["files"]


def test_upload_mesh(c):
    glb = boxes_glb([{"name": "m", "center": (0, 0, 0), "size": (1, 1, 1)}])
    r = c.post("/v1/jobs/upload", files={"mesh": ("thing.glb", io.BytesIO(glb), "model/gltf-binary")},
               data={"job": '{"stages": ["parts"], "parts": {"parts": ["top", "bottom"]}}'})
    assert r.status_code == 201, r.text
    done = wait(c, r.json()["id"])
    assert done["status"] == "done" and done["title"] == "thing" and "input.glb" in done["files"]


def test_upload_rejects_shape_stage_and_bad_type(c):
    r = c.post("/v1/jobs/upload", files={"mesh": ("a.glb", io.BytesIO(b"x"))}, data={"job": '{"stages": ["shape"], "prompt": "x"}'})
    assert r.status_code == 422
    assert c.post("/v1/jobs/upload", files={"mesh": ("a.exe", io.BytesIO(b"x"))}).status_code == 400


def test_parts_without_mesh_fails_cleanly(c):
    job = c.post("/v1/jobs", json={"stages": ["parts"], "parts": {"parts": ["a"]}}).json()
    done = wait(c, job["id"])
    assert done["status"] == "failed" and "no mesh" in done["error"]


def test_cancel_queued_and_running(c):
    a = c.post("/v1/jobs", json={"prompt": "a", "stages": ["shape", "parts"], "parts": {"parts": ["x"] * 8, "steps": 150}}).json()
    b = c.post("/v1/jobs", json={"prompt": "b"}).json()
    assert c.get(f"/v1/jobs/{b['id']}").json()["eta"]["queue_position"] >= 1
    assert c.post(f"/v1/jobs/{b['id']}/cancel").json()["status"] == "canceled"
    for _ in range(200):  # wait until a is running
        if c.get(f"/v1/jobs/{a['id']}").json()["status"] == "running":
            break
        time.sleep(0.01)
    c.post(f"/v1/jobs/{a['id']}/cancel")
    assert wait(c, a["id"])["status"] == "canceled"


def test_retry_bumps_seed(c):
    j = wait(c, c.post("/v1/jobs", json={"prompt": "cup", "stages": ["shape"], "shape": {"seed": 5}}).json()["id"])
    r = c.post(f"/v1/jobs/{j['id']}/retry", json={"new_seed": True}).json()
    assert r["request"]["shape"]["seed"] == 6


def test_validation_and_404s(c):
    assert c.post("/v1/jobs", json={"stages": ["shape"]}).status_code == 422
    assert c.get("/v1/jobs/nope").status_code == 404
    j = wait(c, c.post("/v1/jobs", json={"prompt": "x", "stages": ["shape"]}).json()["id"])
    assert c.get(f"/v1/jobs/{j['id']}/files/../../gen3d.db").status_code == 404


def test_estimate_and_chats_crud(c):
    e = c.post("/v1/estimate", json={"prompt": "x", "stages": ["shape", "parts"], "parts": {"parts": ["a"]}}).json()
    assert e["own_s"] > 0 and [p["stage"] for p in e["plan"]][-1] == "parts"
    chat = c.post("/v1/chats", json={"title": "Props"}).json()
    assert c.patch(f"/v1/chats/{chat['id']}", json={"title": "Props 2"}).json()["title"] == "Props 2"
    wait(c, c.post("/v1/jobs", json={"prompt": "x", "stages": ["shape"], "chat_id": chat["id"]}).json()["id"])
    d = c.delete(f"/v1/chats/{chat['id']}").json()
    assert len(d["jobs"]) == 1 and c.get(f"/v1/chats/{chat['id']}").status_code == 404
