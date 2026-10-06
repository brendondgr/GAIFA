"""11.7: running packs against a fake ComfyUI (and a fake AIHub for memory and outputs)."""

import json
import random
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from comfy.config import Settings
from comfy.packs import load_pack
from comfy.resolve import InputError, resolve
from comfy.server import create_app
from fakecomfy import FakeComfy, FakeHub, fake_control

FIX = Path(__file__).parent / "fixtures"
INFO = json.loads((FIX / "object_info.json").read_text())
ZIT = (Path(__file__).parent / "test_packs.py").read_text().split('ZIT_TOML = """', 1)[1].split('"""', 1)[0]
WAN = """name = "Wan i2v"
task = "image-to-video"
[inputs.prompt]
node = "7"
field = "text"
[inputs.image]
node = "10"
field = "image"
[inputs.seed]
node = "15"
field = "seed"
[inputs.frames]
node = "14"
field = "length"
[inputs.fps]
node = "17"
field = "fps"
[outputs.video]
node = "18"
"""


@pytest.fixture
def env(tmp_path):
    out = tmp_path / "outputs" / "comfy"
    with FakeComfy(INFO, up=True, outputs=out) as fake, FakeHub() as hub:
        s = Settings.from_env({"COMFY_DATA": str(tmp_path / "data"), "COMFY_OUTPUTS": str(out),
                               "COMFY_WORKFLOWS": str(tmp_path / "wf"), "COMFY_VIEW": str(tmp_path / "view"),
                               "COMFY_INPUT": str(tmp_path / "input"), "COMFY_MODELS": str(tmp_path / "models"),
                               "COMFY_URL": fake.url, "AIHUB_URL": hub.url,
                               "COMFY_CONTROL": str(fake_control(tmp_path / "comfyui", fake.url))})
        for pid, fx, toml in (("zimage", "zit-workflow", ZIT), ("wan", "wan21-i2v", WAN)):
            d = s.workflows / pid
            d.mkdir(parents=True)
            shutil.copyfile(FIX / "workflows" / f"{fx}.json", d / "workflow.json")
            (d / "workflow.toml").write_text(toml)
        with TestClient(create_app(s)) as c:
            t0 = time.monotonic()
            while not c.app.state.catalog and time.monotonic() - t0 < 5:   # fetched from the fake
                time.sleep(0.05)
            yield c, fake, hub, s


def run(c, body, wait=10, headers=None):
    r = c.post("/v1/run", json=body, headers=headers or {})
    assert r.status_code == 202, r.json()
    return c.get(f"/v1/jobs/{r.json()['id']}", params={"wait": wait}).json()


def test_text_to_image_run(env):
    c, fake, hub, s = env
    job = run(c, {"workflow": "zimage", "inputs": {"prompt": "a red fox", "aspect": "16:9"}})
    assert job["state"] == "done" and job["progress"] == 1.0, job
    g = fake.prompts[-1]["prompt"]
    assert g["67"]["inputs"]["text"] == "a red fox"
    assert (g["68"]["inputs"]["width"], g["68"]["inputs"]["height"]) == (1328, 752)
    seed = g["70"]["inputs"]["seed"]
    assert seed != -1 and job["inputs"]["seed"] == seed
    prefix = g["77"]["inputs"]["filename_prefix"]
    assert prefix.split("/")[1].endswith("-a-red-fox") and len(prefix.split("/")[0]) == 10
    out = job["outputs"][0]
    f = s.outputs.parent / out["path"]
    assert f.exists() and out["kind"] == "image" and out["path"].startswith("comfy/")
    side = json.loads(f.with_name(f.name + ".json").read_text())
    assert side["prompt"] == "a red fox" and side["seed"] == seed and side["source"]["workflow"] == "zimage"
    assert hub.acquires[-1]["service"] == "comfy" and hub.acquires[-1]["needs_bytes"] > 0
    assert c.get(f"/v1/files/{out['path']}").content == b"fake"
    st = c.get("/v1/status").json()
    assert st["jobs"][0]["state"] == "done" and {x["label"]: x["value"] for x in st["stats"]}["Made today"] == 1


def test_bad_inputs_and_drafts(env):
    c, *_ = env
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "x", "colour": "red", "steps": "many"}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"
    assert len(r.json()["data"]["errors"]) == 2
    assert c.post("/v1/run", json={"workflow": "nope"}).status_code == 422
    (c.app.state.settings.workflows / "wan" / "workflow.toml").unlink()
    r = c.post("/v1/run", json={"workflow": "wan", "inputs": {"prompt": "x"}})
    assert r.status_code == 422 and "draft" in r.json()["detail"]


def test_upload_and_output_inputs(env):
    c, fake, hub, s = env
    up = c.post("/v1/uploads", files={"file": ("cat photo.png", b"PNG", "image/png")}).json()
    job = run(c, {"workflow": "wan", "inputs": {"prompt": "it walks", "image": up["value"], "frames": 33}})
    assert job["state"] == "done" and job["outputs"][0]["kind"] == "video"
    g = fake.prompts[-1]["prompt"]
    assert g["10"]["inputs"]["image"] == f"aihub/{up['name']}" and g["14"]["inputs"]["length"] == 33
    hub.files["o42"] = ("comfy/2026-10-06/x.png", b"OUT")
    run(c, {"workflow": "wan", "inputs": {"prompt": "again", "image": "output:o42"}})
    assert fake.prompts[-1]["prompt"]["10"]["inputs"]["image"] == "aihub/o42-x.png"
    assert (s.input / "aihub" / "o42-x.png").read_bytes() == b"OUT"
    r = c.post("/v1/run", json={"workflow": "wan", "inputs": {"prompt": "x", "image": "output:missing"}})
    assert r.status_code == 422
    first = run(c, {"workflow": "zimage", "inputs": {"prompt": "a still"}})["outputs"][0]["path"]   # "Use as input"
    run(c, {"workflow": "wan", "inputs": {"prompt": "moves", "image": first}})
    assert fake.prompts[-1]["prompt"]["10"]["inputs"]["image"] == "aihub/" + first.rsplit("/", 1)[1]
    assert c.post("/v1/run", json={"workflow": "wan", "inputs": {"prompt": "x", "image": "../etc/passwd"}}).status_code == 422


def test_cancel_and_failure(env):
    c, fake, *_ = env
    fake.hold = True
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "slow"}}).json()
    time.sleep(0.3)
    assert c.post(f"/v1/queue/{r['id']}/cancel").json()["state"] == "cancelled"
    assert fake.interrupted[-1] == {"prompt_id": fake.prompts[-1]["id"]}
    fake.hold = False
    fake.fail_node = "70"
    job = run(c, {"workflow": "zimage", "inputs": {"prompt": "breaks"}})
    assert job["state"] == "failed" and "boom" in job["error"] and "KSampler" in job["error"]


def test_needs_room_is_relayed(env):
    c, fake, hub, _ = env
    hub.room = False
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "x"}})
    assert r.status_code == 409 and r.json()["code"] == "needs_room" and r.json()["data"]["plan"]["unload"] == ["gen3d"]
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "x"}}, headers={"X-AIHub-Make-Room": "1"})
    assert r.status_code == 202 and hub.acquires[-1]["make_room"] == "1"


def test_missed_end_is_reconciled_from_history(env):
    c, fake, *_ = env
    st = c.app.state
    job = run(c, {"workflow": "zimage", "inputs": {"prompt": "x"}})
    st.db.update_run(job["id"], state="running", outputs=None)        # as if the adapter missed the end
    st.runner.by_prompt[job["prompt_id"]] = job["id"]
    t0 = time.monotonic()
    while c.get(f"/v1/jobs/{job['id']}").json()["state"] != "done" and time.monotonic() - t0 < 6:
        time.sleep(0.1)
    assert c.get(f"/v1/jobs/{job['id']}").json()["outputs"]


def test_defaults(env):
    c, *_ = env
    assert c.put("/v1/defaults", json={"defaults": {"text-to-image": "zimage"}}).json()["defaults"] == {"text-to-image": "zimage"}
    assert c.put("/v1/defaults", json={"defaults": {"text-to-image": "wan"}}).status_code == 422
    assert c.get("/v1/workflows").json()["defaults"] == {"text-to-image": "zimage"}


def test_resolve_presets_and_derived(tmp_path):
    d = tmp_path / "wan"
    d.mkdir()
    (d / "workflow.json").write_text("{}")
    (d / "workflow.toml").write_text(WAN + '\n[presets.short]\nframes = 17\n')
    pack = load_pack(d)
    schema = {"properties": {"prompt": {"type": "string"}, "frames": {"type": "integer", "default": 81, "minimum": 1},
                             "fps": {"type": "integer", "default": 16}, "seconds": {"type": "number"},
                             "seed": {"type": "integer", "default": -1, "minimum": -1}}, "required": ["prompt"]}
    v = resolve(pack, schema, {"prompt": "x", "seconds": 3}, rng=random.Random(1))
    assert v["frames"] == 49 and "seconds" not in v and 0 <= v["seed"] < 2**32
    assert resolve(pack, schema, {"prompt": "x"}, preset="short")["frames"] == 17
    with pytest.raises(InputError):
        resolve(pack, schema, {"prompt": "x"}, preset="long")
    with pytest.raises(InputError, match="required"):
        resolve(pack, schema, {})


def test_widget_and_stats(env):
    c, *_ = env
    run(c, {"workflow": "zimage", "inputs": {"prompt": "one"}})
    w = c.get("/v1/hub/widgets/made", params={"range": "7d"}).json()
    assert len(w["categories"]) == 7 and w["series"][0]["values"][-1] == 1 and w["series"][1]["values"][-1] == 0
    st = c.get("/v1/stats", params={"range": "7d"}).json()
    assert st["workflows"][0]["id"] == "zimage" and st["workflows"][0]["done"] == 1 and st["recent"]
    assert c.get("/v1/stats", params={"range": "1y"}).status_code == 422


def test_a_mapped_aspect_is_passed_as_it_is(tmp_path):
    """Qwen-Image-2.1's ResolutionSelector takes aspect + megapixels itself (held-out, 11.12)."""
    d = tmp_path / "q"
    d.mkdir()
    (d / "workflow.json").write_text("{}")
    (d / "workflow.toml").write_text('task = "text-to-image"\n[inputs.prompt]\nnode = "7"\nfield = "prompt"\n'
                                     '[inputs.aspect]\nnode = "6"\nfield = "aspect_ratio"\n[inputs.megapixels]\nnode = "6"\nfield = "megapixels"\n')
    schema = {"properties": {"prompt": {"type": "string"}, "aspect": {"type": "string", "enum": ["1:1 (Square)", "16:9 (Wide)"]},
                             "megapixels": {"type": "number", "default": 1.0}}}
    v = resolve(load_pack(d), schema, {"prompt": "x", "aspect": "16:9 (Wide)", "megapixels": 2})
    assert v == {"prompt": "x", "aspect": "16:9 (Wide)", "megapixels": 2.0}
