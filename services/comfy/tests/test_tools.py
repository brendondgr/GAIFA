"""11.10: the agent's tools follow the ready packs, without a restart."""

import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from comfy.server import create_app
from test_run import WAN, ZIT, env  # noqa: F401  (the fixture)

FIX = Path(__file__).parent / "fixtures"


def names(c) -> dict:
    return {t["function"]["name"]: t for t in c.get("/v1/tools").json()["tools"]}


def test_task_tools_follow_packs(env):  # noqa: F811
    c, fake, hub, s = env
    t = names(c)
    assert set(t) == {"generate_image", "animate_image", "list_workflows", "run_workflow"}
    gi = t["generate_image"]
    params = gi["function"]["parameters"]
    assert params["required"] == ["prompt"] and params["properties"]["workflow"]["enum"] == ["zimage"]
    assert {"prompt", "negative", "seed", "width", "height", "aspect"} <= set(params["properties"])
    assert gi["op"] == "POST /v1/tools/generate_image/call" and gi["job"]["status"].startswith("GET /v1/jobs/")
    assert "zimage" in gi["function"]["description"] and "[default]" in gi["function"]["description"]
    # a second text-to-image pack appears without a restart; with two, a call needs a default or a choice
    shutil.copytree(s.workflows / "zimage", s.workflows / "zimage-2")
    time.sleep(0.05)
    assert names(c)["generate_image"]["function"]["parameters"]["properties"]["workflow"]["enum"] == ["zimage", "zimage-2"]
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat"}})
    assert r.status_code == 422 and "choose a workflow" in r.json()["detail"]
    c.put("/v1/defaults", json={"defaults": {"text-to-image": "zimage-2"}})
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat", "frames": 9}}).json()
    assert r["workflow"] == "zimage-2" and r["ignored"] == ["frames"] and r["status"] == "running"
    job = c.get(f"/v1/jobs/{r['job_id']}", params={"wait": 10}).json()
    assert job["state"] == "done" and job["outputs"][0]["kind"] == "image"
    shutil.rmtree(s.workflows / "zimage-2")
    assert names(c)["generate_image"]["function"]["parameters"]["properties"]["workflow"]["enum"] == ["zimage"]


def test_list_and_run_workflow_tools(env):  # noqa: F811
    c, *_ = env
    ws = c.post("/v1/tools/list_workflows/call", json={"arguments": {}}).json()["workflows"]
    assert [w["id"] for w in ws] == ["wan", "zimage"] and "prompt" in ws[1]["inputs"]
    r = c.post("/v1/tools/run_workflow/call", json={"arguments": {"workflow": "zimage", "inputs": {"prompt": "x"}}}).json()
    assert r["status"] == "running"
    assert c.post("/v1/tools/nope/call", json={"arguments": {}}).status_code == 404


def test_aspect_labels_match_by_ratio():
    from comfy.resolve import _same_ratio

    assert _same_ratio("1:1 (Square)", ["1:1", "16:9"]) == "1:1"
    assert _same_ratio("16:9", ["1:1 (Square)", "16:9 (Widescreen)"]) == "16:9 (Widescreen)"
    assert _same_ratio("5:4", ["1:1", "16:9"]) == "5:4"
