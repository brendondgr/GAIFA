"""3.1: the model routes, and deleting a model's files safely."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from utils.registry import RegistryError
from utils.tests.models.conftest import Models


@pytest.fixture
async def seeded(root, client):
    m = Models(root)
    m.put("llm/G/g.gguf", 64)
    m.put("llm/G/mmproj-g.gguf", 8)
    m.write({"g": {"name": "G", "kind": "llm", "format": "gguf", "path": "llm/G", "files": [m.file("llm/G/g.gguf"), m.file("llm/G/mmproj-g.gguf", "mmproj")], "services": ["lcpp"]}})
    return m


async def test_list_get_put(seeded, client):
    r = await client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["count"] == 1 and body["models"][0]["status"] == "unverified" and body["models"][0]["size_bytes"] == 72
    assert "progress" not in body["models"][0]
    assert (await client.get("/api/models", params={"kind": "vae"})).json()["models"] == []
    r = await client.get("/api/models", params={"kind": "nope"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert (await client.get("/api/models", params={"status": "bogus"})).status_code == 422
    r = await client.get("/api/models/nope")
    assert (r.status_code, r.json()["code"], r.headers["x-aihub-error"]) == (404, "model_not_found", "model_not_found")
    r = await client.put("/api/models/g", json={"notes": "fast", "tags": ["x"]})
    assert r.status_code == 200 and (r.json()["notes"], r.json()["tags"]) == ("fast", ["x"])
    assert seeded.read()["models"]["g"]["notes"] == "fast"
    r = await client.put("/api/models/g", json={"kind": "spaceship"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    r = await client.put("/api/models/g", json={"path": "elsewhere"})  # not editable
    assert r.status_code == 422


async def test_delete_registry_only_keeps_files(seeded, client):
    r = await client.delete("/api/models/g")
    assert r.status_code == 204
    assert seeded.read()["models"] == {}
    assert (seeded.dir / "llm/G/g.gguf").exists()
    assert (await client.delete("/api/models/g")).status_code == 404


async def test_delete_files_removes_them_and_empty_folders_only(seeded, client):
    seeded.put("llm/other.gguf", 4)  # a neighbour: untouched
    r = await client.delete("/api/models/g", params={"files": 1})
    assert r.status_code == 204
    assert not (seeded.dir / "llm/G").exists()
    assert (seeded.dir / "llm/other.gguf").exists() and seeded.paths.registry.exists()


async def test_delete_keeps_unlisted_files_and_their_folder(root, client):
    m = Models(root)
    m.put("tts/x/model.safetensors")
    m.put("tts/x/notes.txt")  # not part of the model
    m.write({"x": {"path": "tts/x", "files": [m.file("tts/x/model.safetensors")]}})
    assert (await client.delete("/api/models/x?files=1")).status_code == 204
    assert sorted(p.name for p in (m.dir / "tts/x").iterdir()) == ["notes.txt"]


async def test_symlinks_never_reach_outside(root, client, tmp_path_factory):
    m = Models(root)
    outside = tmp_path_factory.mktemp("outside")
    (outside / "real.gguf").write_bytes(b"precious")
    (outside / "sub").mkdir()
    (outside / "sub" / "w.gguf").write_bytes(b"precious")
    (m.dir / "llm").mkdir()
    (m.dir / "llm/link.gguf").symlink_to(outside / "real.gguf")  # a file linked from elsewhere
    (m.dir / "llm/dirlink").symlink_to(outside / "sub")  # a folder that leads outside
    m.write({"a": {"files": [{"path": "llm/link.gguf"}]}, "b": {"files": [{"path": "llm/dirlink/w.gguf"}]}})
    assert (await client.delete("/api/models/a?files=1")).status_code == 204
    assert not (m.dir / "llm/link.gguf").is_symlink() and (outside / "real.gguf").read_bytes() == b"precious"
    r = await client.delete("/api/models/b?files=1")
    assert r.status_code == 500 and "leads outside data/models" in r.json()["detail"]
    assert (outside / "sub" / "w.gguf").exists() and "b" in m.read()["models"]


async def test_hf_cache_blobs_go_with_their_snapshot_links(root, client):
    m = Models(root)
    base = "hf-cache/hub/models--org--name"
    blob = m.put(f"{base}/blobs/abc123", 20)
    m.put(f"{base}/refs/main", b"rev1")
    snap = m.dir / base / "snapshots/rev1"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").symlink_to("../../blobs/abc123")
    m.write({"n": {"path": base, "files": [{"path": f"{base}/snapshots/rev1/model.safetensors"}, {"path": f"{base}/refs/main", "role": "ref"}]}})
    assert (await client.get("/api/models/n")).json()["files"][0]["size_bytes"] == 20  # size through the link
    assert (await client.delete("/api/models/n?files=1")).status_code == 204
    assert not blob.exists() and not (m.dir / "hf-cache").exists()


def _svc(id, state="ready", load="n/a", busy=False):
    return SimpleNamespace(id=id, state=state, load=load, busy=busy, in_flight=0, mod=SimpleNamespace(name=id.title()))


@pytest.mark.parametrize(
    "svc, blocked",
    [
        (_svc("lcpp", load="loaded"), True),
        (_svc("lcpp", load="loading"), True),
        (_svc("lcpp", load="unloading"), True),
        (_svc("lcpp", load="unloaded", busy=True), True),
        (_svc("lcpp", load="n/a"), True),  # running with no [memory]: may have the files open
        (_svc("lcpp", load="unloaded"), False),
        (_svc("lcpp", state="stopped", load="n/a"), False),
        (_svc("lcpp", state="failed", load="loaded"), False),
        (_svc("other", load="loaded"), False),  # doesn't use the model
    ],
)
async def test_in_use_blocks_file_deletes(seeded, app, client, svc, blocked):
    app.state.hub.registry.services = SimpleNamespace(services={svc.id: svc}, list=lambda: [])
    r = await client.delete("/api/models/g?files=1")
    if blocked:
        assert r.status_code == 409 and r.json()["code"] == "model_in_use"
        assert r.json()["detail"] == "Lcpp is running and uses G. Stop or unload it first." and r.json()["data"] == {"services": ["lcpp"]}
        assert (seeded.dir / "llm/G/g.gguf").exists()
        assert (await client.delete("/api/models/g")).status_code == 204  # registry-only is always allowed
    else:
        assert r.status_code == 204


async def test_a_broken_registry_refuses_changes(root, client, app):
    m = Models(root)
    m.paths.registry.write_text("{oops")
    r = await client.get("/api/models")
    assert r.status_code == 200 and r.json()["models"] == []
    r = await client.put("/api/models/x", json={"notes": "n"})
    assert r.status_code == 404
    reg = app.state.hub.registry
    with pytest.raises(RegistryError):
        reg.save()
    assert m.paths.registry.read_text() == "{oops"
