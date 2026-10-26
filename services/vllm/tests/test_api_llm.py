"""GAIFA's [llm] contract on vLLM (plan llm-servers 3.2): profiles as catalog entries, load and unload through
the engine (the fake vLLM), and the engine's state."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from vllm_mod.server import create_app


def wait_state(c, want, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        e = c.get("/v1/llm/engine").json()
        if e["state"] == want:
            return e
        time.sleep(0.1)
    raise AssertionError(f"engine never reached {want}: {e}")


def test_catalog_load_engine_unload(make_engine, make_downloads, settings):
    eng = make_engine()
    with TestClient(create_app(settings, engine=eng, downloads=make_downloads(eng))) as c:
        cat = c.get("/v1/llm/catalog").json()["models"]
        assert sorted(m["id"] for m in cat) == ["big", "small"]
        small = next(m for m in cat if m["id"] == "small")
        assert small == {"id": "small", "name": "Small", "format": "hf", "model": "org/small", "size_gb": None, "memory_gb": 2.0,
                         "context": 4096, "downloaded": False, "loaded": False, "relay_model": "Small"}
        assert c.get("/v1/llm/engine").json()["loaded"] == []
        r = c.post("/v1/llm/load", json={"id": "small"})
        assert r.status_code == 202
        e = wait_state(c, "ready")
        assert e["loaded"] == ["small"]
        after = next(m for m in c.get("/v1/llm/catalog").json()["models"] if m["id"] == "small")
        assert after["loaded"] is True and after["downloaded"] is True                       # a load downloads first
        assert c.post("/v1/llm/unload", json={"id": "big"}).json() == {"loaded": ["small"]}     # not loaded: nothing stops
        assert c.post("/v1/llm/unload", json={}).json() == {"loaded": []}
        assert c.get("/v1/llm/engine").json()["state"] == "unloaded"


def test_load_an_unknown_profile(make_engine, make_downloads, settings):
    eng = make_engine()
    with TestClient(create_app(settings, engine=eng, downloads=make_downloads(eng))) as c:
        r = c.post("/v1/llm/load", json={"id": "nope"})
        assert r.status_code == 404 and "no profile" in r.text
