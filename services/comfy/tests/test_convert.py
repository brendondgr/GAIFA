"""11.5: editor files convert to the same API graph ComfyUI's own frontend makes (graphToPrompt,
captured in the browser for each development workflow as <name>.api.json)."""

import json
from pathlib import Path

import pytest

from comfy.convert import ConvertError, is_api, to_api
from comfy.nodes import NodeCatalog

FIX = Path(__file__).parent / "fixtures"
NAMES = sorted(p.stem for p in (FIX / "workflows").glob("*.json") if not p.name.endswith(".api.json"))
IGNORED = {"filename_prefix"}        # ComfyUI's frontend fills in %date:…% here; runs set it anyway


@pytest.fixture(scope="module")
def catalog():
    return NodeCatalog(json.loads((FIX / "object_info.json").read_text()))


def comparable(graph: dict) -> dict:
    return {k: {"class_type": v["class_type"], "inputs": {i: x for i, x in v["inputs"].items() if i not in IGNORED}}
            for k, v in graph.items()}


def diff(got: dict, want: dict) -> list[str]:
    out = [f"missing node {k} ({want[k]['class_type']})" for k in want.keys() - got.keys()]
    out += [f"extra node {k} ({got[k]['class_type']})" for k in got.keys() - want.keys()]
    for k in want.keys() & got.keys():
        a, b = got[k]["inputs"], want[k]["inputs"]
        for name in a.keys() | b.keys():
            if a.get(name) != b.get(name):
                out.append(f"{k} {want[k]['class_type']}.{name}: got {a.get(name)!r}, want {b.get(name)!r}")
    return out


@pytest.mark.parametrize("name", NAMES)
def test_matches_comfyui(name, catalog):
    wf = json.loads((FIX / "workflows" / f"{name}.json").read_text())
    want = json.loads((FIX / "workflows" / f"{name}.api.json").read_text())
    got = to_api(wf, catalog)
    assert not got.missing
    assert diff(comparable(got.graph), comparable(want)) == []


def test_api_graph_passes_through(catalog):
    want = json.loads((FIX / "workflows" / "zit.api.json").read_text())
    assert is_api(want) and to_api(want, catalog).graph == want


def test_not_a_workflow(catalog):
    with pytest.raises(ConvertError):
        to_api({"hello": 1}, catalog)
    with pytest.raises(ConvertError, match="node catalog"):
        to_api({"nodes": [], "links": []}, NodeCatalog({}))
