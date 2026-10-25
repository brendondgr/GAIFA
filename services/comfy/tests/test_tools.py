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
    assert t["list_workflows"]["view"]["rows"] == "workflows"        # plan 46.4: drawn as a table in Chat
    gi = t["generate_image"]
    params = gi["function"]["parameters"]
    assert params["required"] == ["prompt"] and params["properties"]["workflow"]["enum"] == ["zimage"]
    assert {"prompt", "negative", "seed", "width", "height", "aspect"} <= set(params["properties"])
    assert gi["op"] == "POST /v1/tools/generate_image/call" and gi["job"]["status"].startswith("GET /v1/jobs/")
    wf = params["properties"]["workflow"]["x-options"]                # plan 20.3: what each pack is, in the schema
    assert wf["zimage"]["default"] and wf["zimage"]["label"] and "excludes" not in wf["zimage"]   # no references here
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
    c, fake, hub, s = env
    ws = c.post("/v1/tools/list_workflows/call", json={"arguments": {}}).json()["workflows"]
    assert [w["id"] for w in ws] == ["wan", "zimage"] and "prompt" in ws[1]["inputs"]
    r = c.post("/v1/tools/run_workflow/call", json={"arguments": {"workflow": "zimage", "inputs": {"prompt": "x"}}})
    assert r.status_code == 422 and "call generate_image with workflow='zimage'" in r.json()["detail"]   # plan 20.5: its task tool runs it
    toml = s.workflows / "zimage" / "workflow.toml"
    toml.write_text(toml.read_text().replace('task = "text-to-image"', 'task = "custom"'))
    time.sleep(0.05)
    r = c.post("/v1/tools/run_workflow/call", json={"arguments": {"workflow": "zimage", "inputs": {"prompt": "x"}}}).json()
    assert r["status"] == "running"                       # a custom pack has no task tool: run_workflow is its way in
    assert c.post("/v1/tools/nope/call", json={"arguments": {}}).status_code == 404


def test_aspect_labels_match_by_ratio():
    from comfy.resolve import _same_ratio

    assert _same_ratio("1:1 (Square)", ["1:1", "16:9"]) == "1:1"
    assert _same_ratio("16:9", ["1:1 (Square)", "16:9 (Widescreen)"]) == "16:9 (Widescreen)"
    assert _same_ratio("5:4", ["1:1", "16:9"]) == "5:4"


def test_missing_reference_images_reuse_the_main_one():
    from comfy.api_run import fill_references

    assert fill_references(["image", "image_2", "prompt"], {"image": "output:abc", "prompt": "night"}) == {"image_2": "output:abc"}
    assert fill_references(["image", "image_2"], {"image": "a", "image_2": "b"}) == {}
    assert fill_references(["image_2"], {"prompt": "x"}) == {}


def test_task_tools_take_presets(env):  # noqa: F811
    c, fake, hub, s = env
    before = names(c)["generate_image"]["function"]["parameters"]["properties"].get("preset", {}).get("enum", [])
    assert "fast" not in before
    toml = s.workflows / "zimage" / "workflow.toml"
    toml.write_text(toml.read_text() + "\n[presets.fast]\nwidth = 512\nheight = 512\n")
    time.sleep(0.05)
    gi = names(c)["generate_image"]
    assert gi["function"]["parameters"]["properties"]["preset"]["enum"] == sorted(before + ["fast"])
    props = gi["function"]["parameters"]["properties"]
    assert "fast" in props["workflow"]["x-options"]["zimage"]["allows"]["preset"] and "preset" in gi["ask"]
    assert props["preset"]["x-depends-on"] == "workflow" and props["preset"]["x-options"]["fast"]["quality"] == "full"
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat", "preset": "fast"}}).json()
    assert r["preset"] == "fast" and "ignored" not in r
    job = c.get(f"/v1/jobs/{r['job_id']}", params={"wait": 10}).json()
    assert job["state"] == "done" and job["inputs"]["width"] == 512 and job["inputs"]["height"] == 512
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat", "preset": "huge"}})
    assert r.status_code == 422 and "no preset 'huge'" in r.json()["detail"] and "fast" in r.json()["detail"]


def test_a_task_can_describe_a_shared_input_its_own_way():
    """remove_background's prompt is "what to keep", not text to make an image from (the agent left it out)."""
    from comfy.tasks import Tasks

    t = Tasks.load()
    assert "What to keep" in t.get("remove-background").notes["prompt"]
    assert t.get("text-to-image").notes == {} and t.inputs["prompt"]["description"] == "What to make, in plain words"


def test_a_pack_can_be_kept_from_the_agent(env):  # noqa: F811
    """`agent = false`: the page and API still run it; the task tools, list_workflows and run_workflow don't offer it."""
    c, fake, hub, s = env
    shutil.copytree(s.workflows / "zimage", s.workflows / "zimage-base")
    toml = s.workflows / "zimage-base" / "workflow.toml"
    toml.write_text("agent = false\n" + toml.read_text())
    time.sleep(0.05)
    assert names(c)["generate_image"]["function"]["parameters"]["properties"]["workflow"]["enum"] == ["zimage"]
    assert "zimage-base" not in names(c)["run_workflow"]["function"]["parameters"]["properties"]["workflow"]["enum"]
    assert [w["id"] for w in c.post("/v1/tools/list_workflows/call", json={"arguments": {}}).json()["workflows"]] == ["wan", "zimage"]
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat", "workflow": "zimage-base"}})
    assert r.status_code == 422 and "isn't a ready" in r.json()["detail"]
    r = c.post("/v1/tools/run_workflow/call", json={"arguments": {"workflow": "zimage-base", "inputs": {"prompt": "x"}}})
    assert r.status_code == 422 and "isn't offered to the agent" in r.json()["detail"]
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "a cat"}}).json()
    assert r["workflow"] == "zimage"                          # the only pack the agent sees: no default needed
    w = {x["id"]: x for x in c.get("/v1/workflows").json()["workflows"]}
    assert w["zimage-base"]["agent"] is False and w["zimage"]["agent"] is True
    r = c.post("/v1/run", json={"workflow": "zimage-base", "inputs": {"prompt": "on the page"}})
    assert r.status_code == 202                               # the page and API still run it



EDIT_TOML = """name = "An edit"
task = "image-edit"
edit = "{edit}"
[inputs.prompt]
node = "67"
field = "text"
[inputs.image]
node = "71"
field = "text"
[inputs.image_2]
node = "68"
field = "width"
type = "string"
[presets.fast]
quality = "fast"
[outputs.image]
node = "77"
"""


def _edit_pack(s, pid: str, edit: str | None) -> None:
    d = s.workflows / pid
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(s.workflows / "zimage", d)
    toml = EDIT_TOML.format(edit=edit or "")
    (d / "workflow.toml").write_text(toml if edit else toml.replace('edit = ""\n', ""))


def test_edit_packs_declare_their_style_and_references(env):  # noqa: F811
    """plan 20.3: an edit pack says what kind of edit it is; references fill image_2…; one style, no `edit` parameter."""
    c, fake, hub, s = env
    _edit_pack(s, "ed-plain", None)                      # no style: kept from the agent
    _edit_pack(s, "ed-words", "instruction")
    time.sleep(0.05)
    ei = names(c)["edit_image"]["function"]["parameters"]
    props = ei["properties"]
    assert props["workflow"]["enum"] == ["ed-words"] and "edit" not in props
    o = props["workflow"]["x-options"]["ed-words"]
    assert o["kind"] == "instruction" and o["default"] and "excludes" not in o
    assert props["references"]["maxItems"] == 1 and props["references"]["x-kind"] == "image"
    assert props["preset"]["x-options"]["fast"] == {"label": "Fast", "quality": "fast", "when": "only when the user asks for a quick, rough, draft or preview result"}
    s.input.mkdir(parents=True, exist_ok=True)
    (s.input / "a.png").write_bytes(b"PNG")
    r = c.post("/v1/tools/edit_image/call", json={"arguments": {"prompt": "add a hat", "image": "a.png", "references": ["b.png"]}}).json()
    assert r["workflow"] == "ed-words"
    job = c.get(f"/v1/jobs/{r['job_id']}", params={"wait": 10}).json()
    assert job["inputs"]["image_2"] == "b.png"
    r = c.post("/v1/tools/edit_image/call", json={"arguments": {"prompt": "x", "image": "a.png", "references": ["b", "c"]}})
    assert r.status_code == 422 and "takes 1 reference picture" in r.json()["detail"]
    issues = c.get("/v1/workflows/ed-plain").json()["issues_list"]
    assert any(i["code"] == "capability_missing" for i in issues)


def test_two_edit_styles_add_an_edit_parameter(env):  # noqa: F811
    c, fake, hub, s = env
    _edit_pack(s, "ed-words", "instruction")
    _edit_pack(s, "ed-style", "restyle")
    time.sleep(0.05)
    props = names(c)["edit_image"]["function"]["parameters"]["properties"]
    assert props["edit"]["enum"] == ["instruction", "restyle"] and props["edit"]["x-options"]["restyle"]["allows"]["workflow"] == ["ed-style"]
    assert props["workflow"]["x-depends-on"] == "edit"
    s.input.mkdir(parents=True, exist_ok=True)
    (s.input / "a.png").write_bytes(b"PNG")
    r = c.post("/v1/tools/edit_image/call", json={"arguments": {"prompt": "x", "image": "a.png"}}).json()
    assert r["workflow"] == "ed-words"                   # instruction is the default style
    r = c.post("/v1/tools/edit_image/call", json={"arguments": {"prompt": "x", "image": "a.png", "edit": "restyle"}}).json()
    assert r["workflow"] == "ed-style"


def test_a_pack_of_another_task_names_its_tool(env):  # noqa: F811
    """thread t_4c33b4436139: an edit pack passed to generate_image got "did you mean" a text-to-image pack."""
    c, fake, hub, s = env
    _edit_pack(s, "ed-words", "instruction")
    time.sleep(0.05)
    r = c.post("/v1/tools/generate_image/call", json={"arguments": {"prompt": "x", "workflow": "ed-words"}})
    assert r.status_code == 422 and "is an image-edit workflow, not text-to-image: call edit_image" in r.json()["detail"]


def test_a_pack_that_needs_another_accel_isnt_offered(env, monkeypatch):  # noqa: F811
    """39.6: `requires` in workflow.toml against the mod's variant (GAIFA_ACCEL)."""
    c, fake, hub, s = env
    toml = s.workflows / "zimage" / "workflow.toml"
    toml.write_text(toml.read_text().replace("[inputs", 'requires = ["cuda"]\n\n[inputs', 1))
    time.sleep(0.05)
    monkeypatch.setenv("GAIFA_ACCEL", "rocm")
    assert "generate_image" not in names(c)                                     # its only pack runs on CUDA
    monkeypatch.setenv("GAIFA_ACCEL", "cuda")
    assert names(c)["generate_image"]["function"]["parameters"]["properties"]["workflow"]["enum"] == ["zimage"]
    monkeypatch.delenv("GAIFA_ACCEL")
    assert "generate_image" in names(c)                                         # no variant recorded: anything runs


def test_status_tools_rev_follows_the_tools(env):  # noqa: F811
    """51.2: status's tools_rev changes when /v1/tools would, and only then."""
    c, fake, hub, s = env
    rev = c.get("/v1/status").json()["tools_rev"]
    assert isinstance(rev, str) and 0 < len(rev) <= 64
    assert c.get("/v1/status").json()["tools_rev"] == rev          # nothing changed
    shutil.copytree(s.workflows / "zimage", s.workflows / "zimage-2")   # a second ready text-to-image pack
    time.sleep(0.05)
    rev2 = c.get("/v1/status").json()["tools_rev"]
    assert rev2 != rev
    shutil.rmtree(s.workflows / "zimage-2")
    time.sleep(0.05)
    assert c.get("/v1/status").json()["tools_rev"] == rev          # the same tools as before, the same revision
