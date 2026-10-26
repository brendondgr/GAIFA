"""The hub's view of local LLM engines (plan llm-servers 3.4): /api/llm/engines over [llm] mods, load and
unload passed through, a stopped engine, an unknown model, and an engine that needs room."""

from __future__ import annotations

import httpx

from utils.tests.services.conftest import ready


async def test_engines_load_and_unload(rig, serve):
    rig.add("fake-engine")
    rig.add("fake-ok")                                   # not an engine: not listed
    served = await serve()
    await ready(served, "fake-engine")
    async with httpx.AsyncClient(base_url=served.url, timeout=30) as c:
        [e] = (await c.get("/api/llm/engines")).json()
        assert (e["id"], e["running"], e["engine"]) == ("fake-engine", True, {"state": "idle", "loaded": []})
        assert [(m["id"], m["loaded"], m["relay_model"]) for m in e["models"]] == [("tiny-gguf", False, "tiny"), ("small-hf", False, "small-vllm")]
        r = await c.post("/api/llm/fake-engine/load", json={"id": "tiny-gguf"})
        assert r.status_code == 202 and r.json() == {"id": "tiny-gguf", "state": "loading"}
        [e] = (await c.get("/api/llm/engines")).json()
        assert e["engine"]["loaded"] == ["tiny-gguf"] and e["models"][0]["loaded"] is True
        r = await c.post("/api/llm/fake-engine/load", json={"id": "nope"})
        assert r.status_code == 404 and "no model nope" in r.json()["detail"]                 # the mod's own answer
        assert (await c.post("/api/llm/fake-engine/unload", json={})).json() == {"loaded": []}
        r = await c.post("/api/llm/fake-ok/load", json={"id": "x"})
        assert r.status_code == 404 and r.json()["code"] == "engine_not_found"


async def test_a_stopped_engine(rig, serve):
    rig.add("fake-engine")
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url, timeout=30) as c:
        await c.post("/api/services/fake-engine/stop?wait=1")
        [e] = (await c.get("/api/llm/engines")).json()
        assert e["running"] is False and e["models"] == [] and e["engine"] is None
        r = await c.post("/api/llm/fake-engine/load", json={"id": "tiny-gguf"})
        assert r.status_code == 409 and r.json()["code"] == "engine_stopped"
