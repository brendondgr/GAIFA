"""Downloads into the HF cache and their registration in GAIFA (plan 18.3)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from vllm_mod.downloads import role_of
from vllm_mod.server import create_app

from .conftest import run


def test_download_progress_and_registration(settings, make_engine, make_downloads, hub, fetch):
    async def go():
        e = make_engine()
        dl = make_downloads(e)
        p = e.profiles()["small"]
        assert dl.local_commit(p) is None
        job = await dl.start(p)
        seen = set()
        while job.state == "running":
            seen.add(job.progress)
            await asyncio.sleep(0.05)
        assert job.state == "done" and job.commit == "c0ffee" and job.progress == 1.0
        assert any(x is not None and 0 < x < 1 for x in seen) or len(seen) > 1
        assert dl.local_commit(p) == "c0ffee"
        assert job.registered == "registered"
        entry = hub.models[0]
        assert entry["path"] == "hf-cache/hub/models--org--small"
        assert entry["kind"] == "llm" and entry["format"] == "hf-dir" and entry["services"] == ["vllm"]
        assert entry["source"] == {"type": "huggingface", "repo": "org/small", "revision": "c0ffee"}
        assert {f["role"] for f in entry["files"]} == {"weights", "config", "tokenizer"}
        assert all(f["path"].startswith("hf-cache/hub/models--org--small/snapshots/c0ffee/") for f in entry["files"])
        # once local, ensure() doesn't fetch again; a second registration is harmless
        await dl.ensure(p)
        assert fetch.calls == ["org/small"]
        assert await dl.register(p, settings.hf_home / "hub" / "models--org--small" / "snapshots" / "c0ffee") == "exists"
    settings.hf_home = settings.state_dir.parent / "models" / "hf-cache"     # inside a data/models
    run(go())


def test_a_load_downloads_first_and_a_failed_download_fails_the_load(settings, make_engine, make_downloads, hub, fetch):
    eng = make_engine()
    app = create_app(settings, engine=eng, downloads=make_downloads(eng))
    with TestClient(app) as c:
        fetch.fail = "401 Client Error: gated repo"
        r = c.post("/v1/load", json={"profile": "small"})
        assert r.status_code == 500 and "gated repo" in r.json()["detail"]
        assert hub.calls == []                      # no memory was asked for
        assert c.get("/v1/engine").json()["state"] == "unloaded"
        fetch.fail = None
        r = c.post("/v1/load", json={"profile": "small"})
        assert r.status_code == 200 and r.json()["state"] == "ready"
        rows = {p["id"]: p for p in c.get("/v1/profiles").json()["profiles"]}
        assert rows["small"]["downloaded"] == "c0ffee" and rows["small"]["local_bytes"] == fetch.size
        assert rows["big"]["downloaded"] is None
        r = c.post("/v1/downloads", json={"profile": "big"})
        assert r.status_code == 202 and r.json()["repo"] == "org/big"
        assert c.post("/v1/downloads", json={"profile": "nope"}).status_code == 404
        c.post("/v1/unload")


def test_roles():
    assert role_of("model-00001-of-00004.safetensors") == "weights"
    assert role_of("tokenizer_config.json") == "tokenizer"
    assert role_of("config.json") == "config"
    assert role_of("chat_template.jinja") == "config"
    assert role_of("modeling_qwen.py") == "other"
