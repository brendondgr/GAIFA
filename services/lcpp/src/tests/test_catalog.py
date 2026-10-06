import json
import os

import pytest

from lcpp.catalog import Catalog, CatalogError, suggest_id


def test_resolve_exact_nickname_and_partial(home):
    cat = Catalog.load(home)
    assert cat.resolve("gemma4-26b").id == "gemma-4-26B-it"
    assert cat.resolve("MINICPM").id == "minicpm-5-2B"
    with pytest.raises(CatalogError) as e:
        cat.resolve("gemma")
    assert "ambiguous" in str(e.value)
    with pytest.raises(CatalogError) as e:
        cat.resolve("nope")
    assert e.value.code == "model_not_found"


def test_view_with_sidecars(home):
    cat = Catalog.load(home)
    v = cat.view(cat.get("gemma-4-26B-it"), running=["g-7071"])
    assert v["ok"] and v["location"] == "models"
    assert [f["role"] for f in v["files"]] == ["model", "mmproj", "draft"]
    assert v["size_bytes"] == 2400
    assert v["capabilities"] == {"vision": True, "speculative": True, "split": False}
    assert v["overrides"]["spec-type"] == "draft-mtp"
    assert v["effective"]["ctx-size"] == 262144 and v["effective"]["gpu-layers-draft"] == 999
    assert v["running"] == ["g-7071"]


def test_split_model_files_and_missing_part(home):
    cat = Catalog.load(home)
    v = cat.view(cat.get("big-split"))
    assert v["location"] == "external" and v["capabilities"]["split"]
    assert [f.get("part") for f in v["files"]] == ["1/3", "2/3", "3/3"]
    assert v["size_bytes"] == 9010 and v["ok"]
    os.remove(home.root / "extra/Big/Big-00002-of-00003.gguf")
    v = cat.view(cat.get("big-split"))
    assert not v["ok"] and "split 2/3 file not found" in v["problems"][0]


def test_per_model_override_wins(home):
    cat = Catalog.load(home)
    assert cat.effective(cat.get("minicpm-5-2B"))["ctx-size"] == 131072
    assert cat.effective(cat.get("minicpm-5-2B"), {"ctx-size": 4096})["ctx-size"] == 4096


def test_discover_skips_known_sidecars_and_split_tails(home):
    cat = Catalog.load(home)
    found = {d["path"]: d for d in cat.discover(["models", "extra"])}
    loose = str(home.root / "extra/Loose-12B-Q4_K_M.gguf")  # outside the models folder: absolute
    assert set(found) == {"New/fresh-7B-Q8_0.gguf", loose}
    assert found[loose]["suggested_id"] == "loose-12b"


def test_discover_dedupes_symlinks_to_catalog_files(home):
    (home.root / "extra/link.gguf").symlink_to(home.root / "models/Gemma4-19B/g19.gguf")
    cat = Catalog.load(home)
    assert str(home.root / "extra/link.gguf") not in {d["path"] for d in cat.discover(["extra"])}


def test_validate_input(home):
    cat = Catalog.load(home)
    ok = cat.validate_input({"id": "fresh-7b", "nicknames": ["fresh"], "path": "models/New/fresh-7B-Q8_0.gguf"})
    assert ok["ok"] and ok["files"][0]["size_bytes"] == 800
    bad = cat.validate_input({"id": "x y", "nicknames": ["gemma4-19B"], "path": "models/none.gguf"})
    assert not bad["ok"]
    assert any("slug" in e for e in bad["errors"])
    assert any("already used by model gemma-4-19B-it" in e for e in bad["errors"])
    assert any("not found" in e for e in bad["errors"])


def test_upsert_delete_and_defaults_persist(home):
    cat = Catalog.load(home)
    entry = cat.entry_from_input({
        "id": "fresh-7b", "nicknames": ["fresh"], "path": "models/New/fresh-7B-Q8_0.gguf",
        "overrides": {"ctx-size": 8192, "mmproj": "ignored-here"},
    })
    assert entry.params == {"ctx-size": 8192}
    cat.upsert(entry)
    cat.set_defaults({**cat.defaults, "batch-size": 1024})
    raw = json.loads(home.models_file.read_text())
    assert raw["models"]["fresh-7b"]["params"] == {"ctx-size": 8192}
    assert raw["defaults"]["batch-size"] == 1024
    cat.delete("fresh-7b")
    assert "fresh-7b" not in Catalog.load(home).models


@pytest.mark.parametrize("name, expected", [
    ("Qwen3.6-27B-Q4KM.gguf", "qwen3.6-27b"),
    ("Serenity-26B-A4B-Q4_K_M.gguf", "serenity-26b-a4b"),
    ("gemma-4-19B-A4B-it-Heretic.i1-Q4_K_M.gguf", "gemma-4-19b-a4b-it-heretic"),
    ("Nemotron3-120B-Q4KM-00001-of-00003.gguf", "nemotron3-120b"),
])
def test_suggest_id(name, expected):
    assert suggest_id(name) == expected
