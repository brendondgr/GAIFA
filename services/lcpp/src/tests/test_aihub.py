"""lcpp as AIHub's `lcpp` mod: the models folder (LCPP_MODELS_DIR), memory acquire before a launch,
downloads registered in AIHub, and /api/status. Without AIHUB_URL none of it does anything."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from lcpp import aihub
from lcpp.catalog import Catalog
from lcpp.instances import LcppError
from lcpp.paths import Paths


def test_catalog_paths_are_relative_to_the_models_folder(tmp_path):
    root, models = tmp_path / "lcpp", tmp_path / "elsewhere/llm"
    (models / "M").mkdir(parents=True)
    (models / "M/m.gguf").write_bytes(b"\0" * 10)
    (root / "data").mkdir(parents=True)
    (root / "data/models.json").write_text(json.dumps({"defaults": {}, "models": {"m": {"path": "models/M/m.gguf"}}}))
    p = Paths(root=root, state=tmp_path / "st", models=models)
    cat = Catalog.load(p)
    # the old repo-relative form is rewritten once, and resolves into the models folder
    assert json.loads((root / "data/models.json").read_text())["models"]["m"]["path"] == "M/m.gguf"
    v = cat.view(cat.get("m"))
    assert v["ok"] and v["location"] == "models" and v["files"][0]["path"] == "M/m.gguf"
    assert p.model("M/m.gguf") == models / "M/m.gguf" == p.model("models/M/m.gguf")
    assert p.scan_dir("models") == models and p.scan_dir("extra") == root / "extra"
    assert p.display_model(tmp_path / "x.gguf") == str(tmp_path / "x.gguf")  # outside: absolute, reads back
    assert p.model(p.display_model(tmp_path / "x.gguf")) == tmp_path / "x.gguf"


def test_models_folder_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LCPP_MODELS_DIR", str(tmp_path / "llm"))
    assert Paths.default().models_dir == tmp_path / "llm"
    monkeypatch.delenv("LCPP_MODELS_DIR")
    assert Paths.default().models_dir == Paths.default().root / "models"


def _hub(handler):
    return httpx.MockTransport(handler)


def test_acquire_is_a_no_op_without_aihub(monkeypatch):
    monkeypatch.delenv("AIHUB_URL", raising=False)
    assert asyncio.run(aihub.acquire(10, False, "x")) is None


def test_acquire_asks_aihub_and_turns_a_409_into_needs_room(monkeypatch):
    monkeypatch.setenv("AIHUB_URL", "http://hub")
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, dict(req.url.params), json.loads(req.content)))
        if req.url.params.get("make_room"):
            return httpx.Response(200, json={"granted": True, "freed": ["tts"], "plan": None})
        return httpx.Response(409, json={"detail": "Needs 20 GB", "code": "needs_room",
                                         "data": {"plan": {"unload": [{"id": "tts", "frees_bytes": 13e9}], "enough": True}}})
    with pytest.raises(LcppError) as e:
        asyncio.run(aihub.acquire(20_000, False, "launch a", transport=_hub(handler)))
    assert e.value.code == "needs_room" and e.value.status == 409 and e.value.data["plan"]["unload"][0]["id"] == "tts"
    assert asyncio.run(aihub.acquire(20_000, True, "launch a", transport=_hub(handler)))["freed"] == ["tts"]
    assert seen[0][0] == "/api/memory/acquire" and seen[0][2] == {"service": "lcpp", "needs_bytes": 20000, "reason": "launch a"}
    assert seen[1][1] == {"make_room": "1"}


def test_an_unreachable_hub_does_not_block_a_launch(monkeypatch):
    monkeypatch.setenv("AIHUB_URL", "http://hub")

    def handler(req):
        raise httpx.ConnectError("refused")
    assert asyncio.run(aihub.acquire(1, False, "x", transport=_hub(handler))) is None


def test_a_download_is_registered_in_aihub(monkeypatch, tmp_path):
    models = tmp_path / "data/models"
    dest = models / "llm/Mini-1B"
    dest.mkdir(parents=True)
    monkeypatch.setenv("AIHUB_URL", "http://hub")
    monkeypatch.setenv("AIHUB_MODELS", str(models))
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(201, json={"id": "mini-1b"})
    warn = asyncio.run(aihub.register_download(dest, model_id="Mini-1B", name="Mini-1B", repo="o/Mini-GGUF", revision="main",
                                               files=[(dest / "Mini-1B.Q4_K_M.gguf", "ab" * 32), (dest / "mmproj.gguf", None)],
                                               transport=_hub(handler)))
    assert warn is None
    b = bodies[0]
    assert b["path"] == "llm/Mini-1B" and b["kind"] == "llm" and b["services"] == ["lcpp"] and b["id"] == "mini-1b"
    assert b["source"] == {"type": "huggingface", "repo": "o/Mini-GGUF", "revision": "main"}
    assert b["files"][0] == {"path": "llm/Mini-1B/Mini-1B.Q4_K_M.gguf", "role": "weights", "sha256": "ab" * 32}
    assert b["files"][1] == {"path": "llm/Mini-1B/mmproj.gguf", "role": "sidecar"}

    def refuse(req):
        return httpx.Response(409, json={"detail": "already registered", "code": "conflict"})
    assert "already registered" in asyncio.run(aihub.register_download(dest, model_id=None, name="x", repo="o/r", revision="main",
                                                                      files=[], transport=_hub(refuse)))


def test_the_relay_links_to_the_aihub_page(monkeypatch):
    monkeypatch.setenv("AIHUB_URL", "http://127.0.0.1:7000")
    assert aihub.page_url() == "http://127.0.0.1:7000/#/s/lcpp"
    monkeypatch.delenv("AIHUB_URL")
    assert aihub.page_url() is None


def test_status_and_needs_room_through_the_api(fake_home, monkeypatch):
    from fastapi.testclient import TestClient

    from lcpp.backends.subprocess import SubprocessBackend
    from lcpp.daemon.app import create_app
    calls = []

    async def acquire(needs, make_room, reason, transport=None):
        calls.append(make_room)
        if not make_room:
            raise LcppError("needs_room", "Needs 9 GB", 409, data={"plan": {"enough": True, "unload": []}})
        return {"granted": True}
    monkeypatch.setattr(aihub, "acquire", acquire)
    with TestClient(create_app(fake_home, SubprocessBackend(fake_home.state / "logs"))) as c:
        s = c.get("/api/status").json()
        assert s["loaded"] is False and s["busy"] is False and s["jobs"] == []
        assert [x["label"] for x in s["stats"]] == ["Running", "Catalog", "On disk"]
        assert s["stats"][1]["value"] == 5 and s["stats"][2]["unit"] == "GB"
        r = c.post("/api/instances", json={"model_id": "minicpm-5-2B", "port": 17072})
        assert r.status_code == 409 and r.json()["code"] == "needs_room" and r.json()["data"]["plan"]["enough"] is True
        r = c.post("/api/instances", json={"model_id": "minicpm-5-2B", "port": 17072}, headers={"X-AIHub-Make-Room": "1"})
        assert r.status_code == 201, r.text
        assert calls == [False, True]
        c.post("/api/instances/stop-all")
