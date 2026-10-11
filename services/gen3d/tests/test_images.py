"""Image engines (plan 17.4): a picture in, a mesh out of the shape stage, with the fake worker."""

import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gen3d.images import cutout, prepare
from gen3d.server import app
from test_api import wait


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def png(size=(64, 48), white_bg=True) -> bytes:
    im = Image.new("RGB", size, (255, 255, 255) if white_bg else (30, 30, 30))
    for x in range(20, 44):
        for y in range(10, 38):
            im.putpixel((x, y), (200, 40, 40))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_cutout_from_white_or_alpha(tmp_path):
    info = prepare(png(), tmp_path)
    a = Image.open(tmp_path / "input_rgba.png").getchannel("A")
    assert info["size"] == [64, 48] and a.getpixel((30, 20)) == 255 and a.getpixel((2, 2)) == 0
    rgba = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    rgba.putpixel((5, 5), (9, 9, 9, 255))
    assert cutout(rgba) is not rgba and cutout(rgba).getchannel("A").getpixel((5, 5)) == 255


def test_an_empty_picture_is_refused(tmp_path):
    b = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(b, "PNG")
    with pytest.raises(ValueError, match="empty"):
        prepare(b.getvalue(), tmp_path)


@pytest.mark.parametrize("engine", ["hunyuan21", "sam3d_objects"])
def test_local_image_engine_end_to_end(c, engine):
    r = c.post("/v1/jobs/image", files={"image": ("vase.png", png(), "image/png")},
               data={"job": json.dumps({"engine": engine, "stages": ["shape", "preview"]})})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["title"].endswith("· vase") and job["request"]["preset"] == "fast" and job["request"]["image"] == "upload"
    assert job["eta"]["eta_s"] > 0 and job["eta"]["by_stage"]["shape"] > 0
    done = wait(c, job["id"])
    assert done["status"] == "done", done
    assert {"input.png", "input_rgba.png", "mesh.glb", "preview.png", "output.json"} <= set(done["files"])
    assert done["result"]["shape"]["engine"] == engine
    meta = json.loads(c.get(f"/v1/jobs/{job['id']}/files/output.json").content)
    assert meta["params"]["engine"] == engine and meta["main"] == "mesh.glb" and meta["complete"] is True
    # a retry reads the original job's picture; parts on the image mesh work as for Cube3D's
    retry = c.post(f"/v1/jobs/{job['id']}/retry", json={"new_seed": True}).json()
    assert retry["parent_id"] == job["id"] and retry["request"][engine]["seed"] == job["request"][engine]["seed"] + 1
    assert wait(c, retry["id"])["status"] == "done"
    split = c.post("/v1/jobs", json={"parent_id": job["id"], "stages": ["parts"], "parts": {"parts": ["body"]}}).json()
    assert wait(c, split["id"])["status"] == "done"


def test_image_jobs_need_a_picture(c):
    assert c.post("/v1/jobs", json={"engine": "hunyuan21"}).status_code == 422
    assert c.post("/v1/jobs", json={"engine": "hunyuan21", "image": "upload"}).status_code == 422
    r = c.post("/v1/jobs/image", files={"image": ("x.png", png(), "image/png")}, data={"job": json.dumps({"prompt": "x"})})
    assert r.status_code == 422 and "image engine" in r.text
    r = c.post("/v1/jobs/image", files={"image": ("x.png", b"not a picture", "image/png")},
               data={"job": json.dumps({"engine": "hunyuan21"})})
    assert r.status_code == 422 and "picture" in r.json()["detail"]
    # output:<id> pictures come from AIHub: without it, the job is refused rather than failing later
    r = c.post("/v1/jobs", json={"engine": "hunyuan21", "image": "output:o_123"})
    assert r.status_code == 422 and "AIHub" in r.json()["detail"]


def test_switching_engines_stops_the_other_worker(c):
    pool = app.state.runner.worker
    j1 = c.post("/v1/jobs/image", files={"image": ("a.png", png(), "image/png")}, data={"job": json.dumps({"engine": "hunyuan21", "stages": ["shape"]})}).json()
    wait(c, j1["id"])
    assert pool.workers["img3d"].up
    j2 = wait(c, c.post("/v1/jobs", json={"prompt": "fox", "stages": ["shape"]}).json()["id"])
    assert j2["status"] == "done" and pool.workers["cube"].up and not pool.workers["img3d"].up
