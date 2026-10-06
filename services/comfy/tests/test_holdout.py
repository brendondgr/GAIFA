"""11.12: the held-out workflows as regression tests.

Your own (Qwen-Image-2.1) and ComfyUI's official templates (Klein-9B) are fixtures here, with the
API graph ComfyUI's own editor makes for each. Third-party ones (Civitai, community) are read from
where they are on this machine and skipped when they're gone: they aren't committed.
"""

import json
from pathlib import Path

import pytest

from comfy import importer
from comfy.check import check
from comfy.convert import to_api
from comfy.detect import suggest
from comfy.nodes import NodeCatalog
from comfy.packs import Pack
from comfy.tasks import Tasks
from scoring import load_expected, score
from test_convert import comparable, diff

FIX = Path(__file__).parent / "fixtures"
CAT = NodeCatalog(json.loads((FIX / "object_info.json").read_text()))
OWN = ["qwen21-t2i", "qwen21-edit-multi", "qwen21-remove-bg", "klein9b-t2i", "klein9b-edit-base", "klein9b-edit-distilled"]
U, N = Path.home() / "Models/ComfyUI/user/default/workflows", Path.home() / "Models/ComfyUI-next/workflows"
THIRD = {
    "scail2-basic": U / "Scail2-Wan2.1/Wan2.1_Scail2_basic.json",
    "scail2-gguf": U / "Scail2-Wan2.1/Wan2.1_Scail2_gguf.json",
    "zimg-v7-basic": U / "ZIT/ZImgBasicV7.json",
    "krea2-simple": U / "Krea 2 Simple.json",
    "krea2-dualmode": U / "krea2TurboDualModeQwenvlWorkflow_v2NSFWSeedvr2.json",
    "zimage-aio": N / "zImageAllInOneCreatorTxt2imgImg2img_v12.zip",
    "lonecat-krea2-pro": U / "krea2ProGradeWImageEditStyle_v604StyleTransfer.zip",
}
LIVE = Path(__file__).resolve().parents[1] / "data" / "object_info.json"


def expected(name: str) -> dict:
    return load_expected(FIX / "holdout-expected" / f"{name}.toml")


def judged(name: str, manifest: dict) -> dict:
    sc = score(manifest, expected(name))
    assert not sc["wrong"], sc
    assert set(sc["missed"]) <= set(expected(name).get("missed", {})), sc
    assert sc["task_ok"] and sc["outputs_ok"], (manifest["task"], manifest["outputs"])
    return sc


@pytest.mark.parametrize("name", OWN)
def test_own_and_official_convert_exactly_and_detect(name):
    ed = json.loads((FIX / "holdout" / f"{name}.json").read_text())
    conv = to_api(ed, CAT)
    want = json.loads((FIX / "holdout" / f"{name}.api.json").read_text())
    assert diff(comparable(conv.graph), comparable(want)) == []
    judged(name, suggest(conv, CAT, ed, name).manifest)


@pytest.fixture(scope="module")
def live():
    if not LIVE.exists():
        pytest.skip("ComfyUI's node list isn't cached on this machine")
    return NodeCatalog(json.loads(LIVE.read_text()))


@pytest.mark.parametrize("name", sorted(THIRD))
def test_third_party(name, live, tmp_path):
    src = THIRD[name]
    if not src.exists():
        pytest.skip(f"{src} isn't on this machine")
    found = importer.read_all(src.name, src.read_bytes())[0]
    graph = found.editor or found.api
    conv = to_api(graph, live)
    d = tmp_path / name
    d.mkdir()
    (d / "workflow.json").write_text(json.dumps(graph))
    issues = {i.code for i in check(Pack(name, d, source=d / "workflow.json"), live, Tasks.load(), conv=conv)}
    if name == "lonecat-krea2-pro":
        assert "editor_links" in issues                   # Anything Everywhere: named, not guessed
        return
    sc = score(suggest(conv, live, graph, name).manifest, expected(name))
    assert not sc["wrong"], sc
