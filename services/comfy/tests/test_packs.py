"""11.5: packs load from folders, drafts, ComfyUI's view of them, checks, schemas, routes and the CLI."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from comfy import cli
from comfy.check import check
from comfy.library import Library
from comfy.nodes import NodeCatalog
from comfy.packs import Packs, sync_comfy_view
from comfy.server import create_app
from comfy.tasks import Tasks

FIX = Path(__file__).parent / "fixtures"
CAT = NodeCatalog(json.loads((FIX / "object_info.json").read_text()))
ZIT_TOML = """name = "Z-Image Turbo"
task = "text-to-image"
description = "Fast photoreal text-to-image"
[inputs.prompt]
node = "67"
field = "text"
[inputs.negative]
node = "71"
field = "text"
[inputs.seed]
node = "70"
field = "seed"
[inputs.width]
node = "68"
field = "width"
[inputs.height]
title = "EmptySD3LatentImage"
field = "height"
[outputs.image]
node = "77"
[presets.portrait]
width = 832
height = 1216
"""


def make_pack(root: Path, pid: str, fixture: str = "zit-workflow", toml: str | None = ZIT_TOML) -> Path:
    d = root / pid
    d.mkdir(parents=True)
    shutil.copyfile(FIX / "workflows" / f"{fixture}.json", d / "workflow.json")
    if toml is not None:
        (d / "workflow.toml").write_text(toml)
    return d


@pytest.fixture
def lib(tmp_path):
    packs = Packs(tmp_path / "workflows", tmp_path / "view")
    return Library(packs, CAT, Tasks.load())


def test_pack_ready_with_schema_and_presets(lib, tmp_path):
    make_pack(tmp_path / "workflows", "zimage")
    lib.packs.scan()
    p = lib.packs.get("zimage")
    d = lib.detail(p)
    assert d["state"] == "ready" and d["task"] == "text-to-image", d["issues_list"]
    props = d["schema"]["properties"]
    assert props["prompt"]["type"] == "string" and props["prompt"]["x-multiline"]
    assert props["prompt"]["default"].startswith("young woman")          # the graph's value is the default
    assert props["seed"] == {**props["seed"], "type": "integer", "default": -1, "minimum": -1}
    assert props["width"]["default"] == 1024 and props["width"]["minimum"] == 16
    assert {"aspect", "megapixels"} <= set(props)                         # derived from width + height
    assert d["schema"]["required"] == ["prompt"]
    assert d["presets"] == {"portrait": {"width": 832, "height": 1216}}


def test_manifest_errors_and_drafts(lib, tmp_path):
    root = tmp_path / "workflows"
    make_pack(root, "typo", toml='name = "x"\ntask = "text-to-image"\n[inputs.prompt]\nnode = "67"\nfeild = "text"\n')
    make_pack(root, "draft", toml=None)
    make_pack(root, "Bad_Name", toml=None)
    lib.packs.scan()
    typo = lib.brief(lib.packs.get("typo"))
    assert typo["state"] == "broken"
    assert any("feild" in i["detail"] for i in lib.detail(lib.packs.get("typo"))["issues_list"])
    assert lib.brief(lib.packs.get("draft"))["state"] == "draft"
    assert lib.packs.get("Bad_Name").errors
    assert lib.packs.count_drafts() == 2 and lib.packs.count_ready() == 0


def test_check_finds_missing_nodes_models_and_mapping_errors(lib, tmp_path):
    root = tmp_path / "workflows"
    d = make_pack(root, "zimage", toml=ZIT_TOML.replace('node = "67"', 'node = "999"'))
    wf = json.loads((d / "workflow.json").read_text())
    for n in wf["nodes"]:
        if n["type"] == "UNETLoader":
            n["widgets_values"][0] = "gone.safetensors"
            n.setdefault("properties", {})["models"] = [{"name": "gone.safetensors", "url": "https://hf.co/x/gone.safetensors", "directory": "diffusion_models"}]
        if n["type"] == "LoraLoaderModelOnly":
            n["type"] = "LoraLoaderPlus"
            n["properties"] = {"cnr_id": "comfyui-lora-plus"}
    (d / "workflow.json").write_text(json.dumps(wf))
    lib.packs.scan()
    issues = {i.code: i for i in check(lib.packs.get("zimage"), CAT, lib.tasks)}
    assert issues["missing_model"].data["url"] == "https://hf.co/x/gone.safetensors"
    assert "data/models/comfyui/diffusion_models/" in issues["missing_model"].fix
    assert issues["missing_node"].data == {"type": "LoraLoaderPlus", "package": "comfyui-lora-plus"}
    assert "999" in issues["input_unmapped"].detail
    assert "task_input_missing" not in issues                # prompt is mapped (to a node that's gone)


def test_task_requirements(lib, tmp_path):
    make_pack(tmp_path / "workflows", "edit", toml=ZIT_TOML.replace("text-to-image", "image-edit"))
    lib.packs.scan()
    codes = [i["code"] for i in lib.detail(lib.packs.get("edit"))["issues_list"]]
    assert "task_input_missing" in codes            # image-edit needs an image input


def test_comfy_view_symlinks_saves_and_cleanup(tmp_path):
    root, view = tmp_path / "workflows", tmp_path / "view"
    make_pack(root, "zimage")
    packs = Packs(root, view)
    packs.scan()
    link = view / "zimage.json"
    assert link.is_symlink() and json.loads(link.read_text())["nodes"]
    # ComfyUI saves: a temporary file renamed over the symlink
    tmp = view / "tmpXYZ"
    tmp.write_text(json.dumps({"nodes": [], "links": [], "saved": "in comfy"}))
    os.replace(tmp, link)
    assert not link.is_symlink()
    assert packs.scan()
    assert json.loads((root / "zimage" / "workflow.json").read_text())["saved"] == "in comfy"
    assert link.is_symlink()
    # a pack removed: its symlink goes, other files stay
    (view / "mine.json").write_text("{}")
    shutil.rmtree(root / "zimage")
    packs.scan()
    assert not link.exists() and (view / "mine.json").exists()


def test_loose_drafts_and_adopt(tmp_path):
    root, view = tmp_path / "workflows", tmp_path / "view"
    (view / "Krea2").mkdir(parents=True)
    shutil.copyfile(FIX / "workflows" / "krea2-txt2img.json", view / "Krea2" / "01_krea2-turbo_txt2img.json")
    shutil.copyfile(FIX / "workflows" / "zit.json", view / "My Portrait.json")
    packs = Packs(root, view)
    packs.scan()
    ids = sorted(p.id for p in packs.all())
    assert ids == ["krea2-01-krea2-turbo-txt2img", "my-portrait"]
    p = packs.adopt("my-portrait", "portrait")
    assert p.source == root / "portrait" / "workflow.json" and (view / "portrait.json").is_symlink()
    assert not (view / "My Portrait.json").exists()


def test_routes_and_live_edits(tmp_path, settings):
    make_pack(settings.workflows, "zimage")
    with TestClient(create_app(settings)) as c:
        c.app.state.catalog.info = CAT.info
        c.app.state.catalog.version += 1
        ws = c.get("/v1/workflows").json()["workflows"]
        assert [(w["id"], w["state"]) for w in ws] == [("zimage", "ready")]
        assert c.get("/v1/workflows/zimage").json()["schema"]["properties"]["prompt"]
        assert c.get("/v1/workflows/nope").status_code == 404
        assert c.get("/v1/tasks").json()["tasks"]["text-to-image"]["tool"] == "generate_image"
        toml = settings.workflows / "zimage" / "workflow.toml"
        time.sleep(0.01)
        toml.write_text(ZIT_TOML.replace("Z-Image Turbo", "Z-Image Fast"))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2:
            if c.get("/v1/workflows").json()["workflows"][0]["name"] == "Z-Image Fast":
                break
            time.sleep(0.1)
        assert c.get("/v1/workflows").json()["workflows"][0]["name"] == "Z-Image Fast"
        assert c.get("/v1/status").json()["stats"][0] == {"label": "Workflows", "value": 1}


def test_cli_new_copy_list_check(tmp_path, settings, monkeypatch, capsys):
    monkeypatch.setenv("COMFY_WORKFLOWS", str(settings.workflows))
    monkeypatch.setenv("COMFY_VIEW", str(settings.comfy_view))
    monkeypatch.setenv("COMFY_DATA", str(settings.data))
    monkeypatch.setenv("AIHUB_URL", "http://127.0.0.1:1")
    settings.data.mkdir(parents=True)
    (settings.data / "object_info.json").write_text((FIX / "object_info.json").read_text())
    assert cli.main(["new", "zimage", "--from", str(FIX / "workflows" / "zit-workflow.json")]) == 0
    (settings.workflows / "zimage" / "workflow.toml").write_text(ZIT_TOML)
    assert cli.main(["check", "zimage"]) == 0
    assert cli.main(["copy", "zimage", "zimage-2"]) == 0
    assert cli.main(["new", "api", "--from", str(FIX / "workflows" / "zit.api.json")]) == 0
    assert (settings.workflows / "api" / "workflow.api.json").exists()
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "zimage-2" in out and "ready" in out and "draft" in out
    assert cli.main(["new", "Bad", "--from", "x"]) == 2


def test_suggest_route_and_cli_accept(tmp_path, settings, monkeypatch, capsys):
    make_pack(settings.workflows, "wan", fixture="wan21-i2v", toml=None)
    with TestClient(create_app(settings)) as c:
        c.app.state.catalog.info = CAT.info
        c.app.state.catalog.version += 1
        r = c.get("/v1/workflows/wan/suggest").json()
        assert r["manifest"]["task"] == "image-to-video" and "[inputs.frames]" in r["toml"]
    for k, v in {"COMFY_WORKFLOWS": settings.workflows, "COMFY_VIEW": settings.comfy_view, "COMFY_DATA": settings.data}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setenv("AIHUB_URL", "http://127.0.0.1:1")
    (settings.data / "object_info.json").write_text((FIX / "object_info.json").read_text())
    assert cli.main(["new", "zimage", "--from", str(FIX / "workflows" / "zit-workflow.json"), "--accept"]) == 0
    out = capsys.readouterr().out
    assert "wrote workflows/zimage/workflow.toml" in out and "zimage: ready" in out
    assert cli.main(["suggest", "zimage", "--write"]) == 1          # never overwrites
