"""The HTTP API (FastAPI TestClient + SubprocessBackend + fake llama-server)."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from lcpp.backends.subprocess import SubprocessBackend
from lcpp.daemon.app import create_app


@pytest.fixture
def client(fake_home):
    web = fake_home.root / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>lcpp</title>")
    app = create_app(fake_home, SubprocessBackend(fake_home.state / "logs"))
    with TestClient(app) as c:
        yield c
        c.post("/api/instances/stop-all")
        wait_for(c, lambda ov: not ov["instances"])


def wait_for(c, pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ov = c.get("/api/overview").json()
        if pred(ov):
            return ov
        time.sleep(0.1)
    raise AssertionError(f"timed out; last overview: {json.dumps(ov)[:800]}")


def test_health_overview_and_static(client):
    assert client.get("/api/health").json()["ok"] is True
    ov = client.get("/api/overview").json()
    assert ov["instances"] == []
    assert ov["system"]["memory"]["total_bytes"] > 0
    assert ov["system"]["daemon"]["port"] == 7710
    assert ov["system"]["llama"]["binary_ok"] is True
    assert ov["relay"]["reachable"] is False and ov["relay"]["error"]
    assert "lcpp" in client.get("/").text
    assert "LCPP_API_BASE" in client.get("/config.js").text


def test_launch_lifecycle_over_http(client):
    pf = client.post("/api/instances/preflight", json={"kind": "single", "model_id": "minicpm-5-2B"}).json()
    assert pf["errors"] == [] and pf["port"] == 17071
    r = client.post("/api/instances", json={"kind": "single", "model_id": "minicpm-5-2B",
                                             "relay": {"enabled": True, "alias": "mini"}})
    assert r.status_code == 201, r.text
    body = r.json()
    inst = body["instance"]
    assert inst["state"] == "starting" and inst["relay"]["state"] == "pending"
    assert any("Relay is unreachable" in w for w in body["warnings"])
    wait_for(client, lambda ov: ov["instances"][0]["state"] == "ready")
    got = client.get("/api/instances/17071").json()
    assert got["name"] == inst["name"] and got["rss_bytes"]
    lines = client.get(f"/api/instances/{inst['name']}/logs?lines=50").json()["lines"]
    assert any("listening" in ln["text"] for ln in lines)
    # models view knows it is running
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert models["minicpm-5-2B"]["running"] == [inst["name"]]
    r = client.delete("/api/models/minicpm-5-2B")
    assert r.status_code == 409 and r.json()["code"] == "model_in_use"
    # port conflict with the running instance
    r = client.post("/api/instances", json={"model_id": "gemma4-19B", "port": 17071})
    assert r.status_code == 409 and r.json()["code"] == "port_in_use"
    r = client.delete(f"/api/instances/{inst['name']}")
    assert r.status_code == 202 and r.json()["state"] == "stopping"
    wait_for(client, lambda ov: not ov["instances"])
    assert client.get("/api/recent").json()[0]["model_id"] == "minicpm-5-2B"


def test_failed_then_dismiss(client):
    r = client.post("/api/instances", json={"model_id": "broken"})
    name = r.json()["instance"]["name"]
    ov = wait_for(client, lambda ov: ov["instances"] and ov["instances"][0]["state"] == "failed")
    assert "out of device memory" in ov["instances"][0]["last_error"]
    assert client.delete(f"/api/instances/{name}?dismiss=1").status_code == 204
    r = client.get(f"/api/instances/{name}")
    assert r.status_code == 404 and r.json()["code"] == "instance_not_found"


def test_chat_streams_with_metrics(client):
    client.post("/api/instances", json={"model_id": "gemma4-19B", "port": 17080})
    wait_for(client, lambda ov: ov["instances"][0]["state"] == "ready")
    with client.stream("POST", "/api/chat", json={
            "target": {"type": "instance", "name": "17080"},
            "request": {"model": "some-alias", "messages": [{"role": "user", "content": "hi"}]}}) as r:
        assert r.status_code == 200
        events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in events if "choices" in c)
    assert text == "Hello from the fake server."
    m = events[-1]["lcpp_metrics"]
    assert m["completion_tokens"] == 5 and m["prompt_tokens"] == 5 and m["ttft_ms"] >= 0
    r = client.post("/api/chat", json={"target": {"type": "instance", "name": "nope"}, "request": {}})
    assert r.status_code == 404
    r = client.post("/api/chat", json={"target": {"type": "relay", "model": "x"}, "request": {}})
    assert r.status_code == 502 and r.json()["code"] == "relay_unreachable"


def test_router_over_http(client):
    client.post("/api/instances", json={"kind": "router", "model_ids": ["gemma4-19B", "minicpm"], "port": 17081})
    wait_for(client, lambda ov: ov["instances"][0]["state"] == "ready")
    r = client.post("/api/instances/router-17081/models/minicpm-5-2B/load")
    assert r.status_code == 200
    assert [m["loaded"] for m in r.json()["models"]] == [False, True]
    assert client.post("/api/instances/router-17081/models/minicpm-5-2B/unload").json()["models"][1]["loaded"] is False


def test_models_crud_validate_discover_defaults(client):
    v = client.post("/api/models/validate", json={"id": "fresh", "path": "models/New/fresh-7B-Q8_0.gguf"}).json()
    assert v["ok"] and v["files"][0]["exists"]
    disc = client.get("/api/models/discovered").json()
    assert {d["path"].rsplit("lcpp/", 1)[-1] for d in disc} == {"New/fresh-7B-Q8_0.gguf", "extra/Loose-12B-Q4_K_M.gguf"}
    r = client.put("/api/models/fresh", json={"id": "fresh", "nicknames": ["fr"],
                                              "path": "models/New/fresh-7B-Q8_0.gguf",
                                              "overrides": {"ctx-size": 8192}})
    assert r.status_code == 200 and r.json()["effective"]["ctx-size"] == 8192
    r = client.put("/api/models/bad", json={"id": "bad", "path": "models/none.gguf"})
    assert r.status_code == 400 and "not found" in r.json()["detail"]
    d = client.put("/api/models/defaults", json={"ctx-size": 4096}).json()
    assert d == {"ctx-size": 4096}
    assert client.delete("/api/models/fresh").status_code == 204
    assert client.delete("/api/models/fresh").status_code == 404


def test_settings_roundtrip(client):
    s = client.get("/api/settings").json()
    s["ports"]["start"] = 17072
    r = client.put("/api/settings", json=s).json()
    assert r["restart_required"] is False and r["settings"]["ports"]["start"] == 17072
    assert client.get("/api/ports/suggest").json()["port"] == 17072
    s["daemon"]["port"] = 7701
    assert client.put("/api/settings", json=s).json()["restart_required"] is True
    s["ports"] = {"start": 9000, "end": 8000}
    r = client.put("/api/settings", json=s)
    assert r.status_code == 400 and r.json()["code"] == "invalid_param"


def test_log_follow_yields_new_lines(fake_home):
    """The SSE route is a thin loop over this; TestClient cannot consume an
    endless stream (it buffers the whole body), so the follower is tested directly."""
    import asyncio

    from conftest import make_supervisor

    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        await sup.launch({"model_id": "gemma4-19B", "port": 17082})
        follower = sup.follow("17082")
        got = []
        async with asyncio.timeout(10):
            async for line in follower:
                got.append(line["text"])
                if any("listening" in t for t in got):
                    break
        await follower.aclose()
        await sup.stop_all()
        while sup.instances:
            await asyncio.sleep(0.05)
        await sup.close()
        return got

    assert any("listening" in t for t in asyncio.run(scenario()))
