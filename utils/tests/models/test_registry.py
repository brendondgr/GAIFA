"""3.1: registry.json storage, computed status, totals and filters."""

from __future__ import annotations

import json
import os
import time

import pytest

from utils.registry import Patch, RegistryError
from utils.registry.model import now_iso


def test_no_file_is_an_empty_registry(reg, models):
    assert reg.list()["models"] == [] and reg.list()["totals"] == {"count": 0, "size_bytes": 0, "by_kind": {}}
    assert not models.paths.registry.exists()  # reading never creates it


def test_save_is_sorted_indented_and_round_trips_unknown_keys(reg, models):
    models.put("llm/a.gguf", 10)
    models.write({"zeta": {"files": [models.file("llm/a.gguf") | {"future": 1}], "kind": "llm", "extra_key": [1, 2]},
                  "alpha": {"files": [models.file("llm/a.gguf")], "kind": "llm"}})
    reg.load()
    reg.save()
    text = models.paths.registry.read_text()
    assert text.endswith("}\n") and '\n  "models": {\n    "alpha": {' in text
    doc = json.loads(text)
    assert list(doc["models"]) == ["alpha", "zeta"] and list(doc) == ["models", "version"]
    assert doc["models"]["zeta"]["extra_key"] == [1, 2] and doc["models"]["zeta"]["files"][0]["future"] == 1
    assert "actual_sha256" not in doc["models"]["alpha"]["files"][0]


def test_invalid_entries_are_reported_and_kept(reg, models):
    models.put("a.bin")
    models.write({"good": {"files": [models.file("a.bin")]}, "bad": {"files": [{"path": "../../etc/passwd"}]}, "Bad Id": {"files": []}})
    reg.load()
    assert list(reg.entries) == ["good"]
    assert any(e.startswith("bad: path:") and "files.0.path: '../../etc/passwd' must be inside data/models" in e for e in reg.errors)
    assert any(e.startswith("Bad Id: not a valid model id") for e in reg.errors)
    reg.save()  # the bad entries survive a save untouched
    doc = models.read()["models"]
    assert doc["bad"] == {**doc["bad"], "files": [{"path": "../../etc/passwd"}]} and "Bad Id" in doc


@pytest.mark.parametrize("text, why", [("{not json", "can't be read"), ('{"version": 2, "models": {}}', "version 2"), ("[]", "must be")])
def test_unreadable_registry_is_read_only(reg, models, text, why):
    models.paths.registry.write_text(text)
    reg.load()
    assert why in reg.readonly and reg.entries == {}
    with pytest.raises(RegistryError) as e:
        reg.save()
    assert e.value.code == "registry_invalid"
    assert models.paths.registry.read_text() == text  # never overwritten


def test_reloads_when_the_file_changes_on_disk(reg, models):
    models.put("a.bin")
    assert reg.list()["models"] == []
    models.write({"one": {"files": [models.file("a.bin")]}})
    assert [m["id"] for m in reg.list()["models"]] == ["one"]  # created after the hub loaded: picked up
    models.write({"one": {"files": [models.file("a.bin")]}, "two": {"files": [models.file("a.bin")]}})
    later = time.time_ns() + 10**9
    os.utime(models.paths.registry, ns=(later, later))  # same second as the first write: force a new mtime
    assert [m["id"] for m in reg.list()["models"]] == ["one", "two"]


def status(reg, mid):
    return reg.view(mid)


def test_status_ok_unverified_missing(reg, models):
    old = time.time() - 3600
    models.put("tts/x/model.safetensors", 100, mtime=old)
    models.put("tts/x/config.json", 5, mtime=old)
    models.write({
        "ok": {"path": "tts/x", "files": [models.file("tts/x/model.safetensors", verified=True), models.file("tts/x/config.json", "config", verified=True)]},
        "unverified": {"files": [models.file("tts/x/config.json")]},
        "missing": {"files": [models.file("tts/gone.gguf")]},
    })
    reg.load()
    ok = status(reg, "ok")
    assert (ok["status"], ok["problems"], ok["size_bytes"]) == ("ok", [], 105)
    assert all(f["exists"] and f["verified"] for f in ok["files"])
    assert status(reg, "unverified")["status"] == "unverified"
    m = status(reg, "missing")
    assert m["status"] == "missing" and m["problems"] == ["File not found: tts/gone.gguf"] and m["files"][0]["size_bytes"] == 1000


def test_status_partial(reg, models):
    models.put("llm/a/one.gguf", 50)
    models.put("llm/b/short.gguf", 40)
    models.put("llm/c/dl.gguf.part", 7)
    models.put("llm/d/grown.gguf", 90)
    models.write({
        "half": {"files": [models.file("llm/a/one.gguf"), models.file("llm/a/two.gguf")]},
        "short": {"files": [models.file("llm/b/short.gguf", size_bytes=400)]},
        "downloading": {"files": [models.file("llm/c/dl.gguf", size_bytes=70)]},
        "grown": {"files": [models.file("llm/d/grown.gguf", size_bytes=80)]},
    })
    reg.load()
    assert status(reg, "half")["status"] == "partial" and status(reg, "half")["problems"] == ["File not found: llm/a/two.gguf"]
    assert status(reg, "short")["problems"] == ["Incomplete: llm/b/short.gguf is 40 B of 400 B"]
    d = status(reg, "downloading")
    assert d["status"] == "partial" and d["problems"][0].startswith("Downloading: llm/c/dl.gguf (7 B of 70 B")
    assert status(reg, "grown")["problems"] == ["Changed size: llm/d/grown.gguf was 80 B, now 90 B"]


def test_status_mismatch_changed_and_verifying(reg, models):
    old = time.time() - 3600
    models.put("vae/a.safetensors", 30, mtime=old)
    models.put("vae/b.safetensors", 30)
    bad = models.file("vae/a.safetensors", verified=True)
    bad["actual_sha256"] = "0" * 64
    changed = models.file("vae/b.safetensors", verified=True, verified_at="2026-01-01T00:00:00+00:00")
    models.write({"bad": {"files": [bad]}, "changed": {"files": [changed]}, "busy": {"files": [models.file("vae/a.safetensors")]}})
    reg.load()
    b = status(reg, "bad")
    assert b["status"] == "checksum_mismatch" and b["problems"][0].startswith("Checksum mismatch: sha256 of vae/a.safetensors is 000000000000…")
    c = status(reg, "changed")
    assert c["status"] == "unverified" and c["problems"] == ["Changed since it was verified: vae/b.safetensors"]
    reg.progress["busy"] = 0.25
    v = status(reg, "busy")
    assert (v["status"], v["progress"]) == ("verifying", 0.25)
    assert "progress" not in status(reg, "bad")


def test_a_folder_or_dangling_symlink_is_not_a_file(reg, models):
    (models.dir / "dir.gguf").mkdir()
    (models.dir / "link.gguf").symlink_to(models.dir / "nowhere")
    models.write({"d": {"files": [{"path": "dir.gguf"}]}, "l": {"files": [{"path": "link.gguf"}]}, "empty": {"path": "x", "files": []}})
    reg.load()
    assert status(reg, "d")["problems"] == ["Not a file: dir.gguf"] and status(reg, "d")["status"] == "missing"
    assert status(reg, "l")["status"] == "missing"
    assert status(reg, "empty")["status"] == "missing" and status(reg, "empty")["problems"] == ["No files are listed for this model"]


def test_totals_and_filters(reg, models):
    models.put("llm/a.gguf", 100)
    models.put("llm/b.gguf", 50)
    models.put("vae/v.safetensors", 7)
    models.write({
        "gemma": {"name": "Gemma 4", "kind": "llm", "files": [models.file("llm/a.gguf")], "services": ["lcpp"], "tags": ["default"]},
        "mini": {"name": "MiniCPM", "kind": "llm", "files": [models.file("llm/b.gguf")]},
        "gone": {"name": "Gone", "kind": "llm", "files": [models.file("llm/gone.gguf")]},
        "vae": {"name": "Wan VAE", "kind": "vae", "files": [models.file("vae/v.safetensors")], "services": ["comfy"]},
    })
    reg.load()
    r = reg.list()
    assert r["totals"] == {"count": 4, "size_bytes": 157, "by_kind": {"llm": {"count": 3, "size_bytes": 150}, "vae": {"count": 1, "size_bytes": 7}}}
    assert r["disk"]["total_bytes"] > 0
    ids = lambda **f: [m["id"] for m in reg.list(**f)["models"]]  # noqa: E731
    assert ids(kind="vae") == ["vae"] and ids(kind="llm,vae") == ["gemma", "gone", "mini", "vae"]
    assert ids(service="lcpp") == ["gemma"] and ids(status="missing") == ["gone"]
    assert ids(q="DEFAULT") == ["gemma"] and ids(q="vae/") == ["vae"] and ids(q="nothing") == []
    assert reg.list(kind="vae")["totals"]["count"] == 4  # totals always cover everything


async def test_update_validates_and_saves(reg, models, bus):
    models.put("a.bin")
    models.write({"m": {"files": [models.file("a.bin")]}})
    reg.load()
    sub = bus.subscribe()
    v = await reg.update("m", Patch(name="New", tags=[" a ", "a", "", "b"], services=["tts"], source={"type": "huggingface", "repo": "o/r", "revision": "abc"}))
    assert (v["name"], v["tags"], v["services"], v["source"]) == ("New", ["a", "b"], ["tts"], {"type": "huggingface", "repo": "o/r", "revision": "abc"})
    stored = models.read()["models"]["m"]
    assert stored["source"] == {"type": "huggingface", "repo": "o/r", "revision": "abc"} and stored["name"] == "New"
    assert sub.queue.get_nowait()["model"]["name"] == "New"
    with pytest.raises(RegistryError) as e:
        await reg.update("m", Patch(services=["Not An Id"]))
    assert e.value.status == 422 and "services" in e.value.detail
    v = await reg.update("m", Patch(source=None))
    assert v["source"] is None
    with pytest.raises(RegistryError) as e:
        await reg.update("nope", Patch(name="x"))
    assert e.value.code == "model_not_found"


def test_now_iso_has_a_timezone():
    assert now_iso()[-6] in "+-"
