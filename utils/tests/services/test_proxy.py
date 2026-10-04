"""2.5: the proxy at /api/s/<id>/*, against a real uvicorn server and fake mods."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import signal
import time
import wave

import httpx
import pytest

from utils.tests.services.conftest import ready, until


@pytest.fixture
async def hub(rig, serve):
    rig.add("fake-ok")
    served = await serve()
    await ready(served, "fake-ok")
    return served


async def test_json_query_and_headers(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.post("/api/s/fake-ok/v1/echo?a=1&b=two%20words&a=3", json={"x": [1, 2]}, headers={"X-Custom": "yes", "Connection": "keep-alive, X-Drop-Me", "X-Drop-Me": "1"})
    assert r.status_code == 200 and "x-aihub-error" not in r.headers
    body = r.json()
    assert body["json"] == {"x": [1, 2]}
    assert body["query"] == {"a": ["1", "3"], "b": ["two words"]}
    h = {k.lower(): v for k, v in body["headers"].items()}
    assert h["x-custom"] == "yes" and h["x-forwarded-prefix"] == "/api/s/fake-ok"
    assert h["x-forwarded-host"] == f"127.0.0.1:{hub.port}" and h["x-forwarded-proto"] == "http"
    assert "x-drop-me" not in h  # named in Connection: → hop-by-hop
    assert h["host"] == f"127.0.0.1:{hub.services.get('fake-ok').port}"


async def test_binary_audio_passes_through(hub, rig):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        via_hub = await c.post("/api/s/fake-ok/v1/speech", json={"text": "hi"})
        direct = await c.post(f"http://127.0.0.1:{rig.ports['fake-ok']}/v1/speech", json={"text": "hi"})
    assert via_hub.status_code == 200 and via_hub.headers["content-type"] == "audio/wav"
    assert via_hub.content == direct.content
    with wave.open(io.BytesIO(via_hub.content)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 4000


async def test_50mb_multipart_upload_streams(hub):
    payload = os.urandom(1 << 20) * 50
    async with httpx.AsyncClient(base_url=hub.url, timeout=60) as c:
        r = await c.post("/api/s/fake-ok/v1/upload", files={"file": ("big.bin", payload, "application/octet-stream")})
    assert r.status_code == 200
    got = r.json()
    assert got["content_type"].startswith("multipart/form-data; boundary=")
    assert got["size"] > 50 * (1 << 20)
    # The multipart body arrived whole: it contains the payload byte for byte.
    assert got["size"] - len(payload) < 1024


async def test_upload_body_is_byte_exact(hub):
    payload = os.urandom(3 * (1 << 20) + 17)
    async with httpx.AsyncClient(base_url=hub.url, timeout=30) as c:
        r = await c.post("/api/s/fake-ok/v1/upload", content=payload, headers={"content-type": "application/octet-stream"})
    assert r.json() == {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "content_type": "application/octet-stream"}


async def test_sse_is_not_buffered(hub):
    t0 = time.perf_counter()
    stamps: list[float] = []
    async with httpx.AsyncClient(base_url=hub.url, timeout=10) as c:
        async with c.stream("GET", "/api/s/fake-ok/v1/events?n=4&gap=0.4") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    stamps.append(time.perf_counter() - t0)
    assert len(stamps) == 4
    assert stamps[0] < 0.2, stamps  # first event right away, not after the stream ends
    assert stamps[-1] > 1.1  # the rest arrive as they are sent
    assert all(b - a > 0.25 for a, b in zip(stamps, stamps[1:])), stamps


async def test_client_disconnect_closes_upstream(hub):
    svc = hub.services.get("fake-ok")
    async with httpx.AsyncClient(base_url=hub.url, timeout=10) as c:
        async with c.stream("GET", "/api/s/fake-ok/v1/events?n=200&gap=0.05") as r:
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    assert svc.in_flight == 1
                    break  # leave after the first event
    await until(lambda: svc.in_flight == 0, timeout=5)

    async def aborted():
        async with httpx.AsyncClient() as c:
            return (await c.get(f"{svc.url}/v1/status")).json()["sse_aborted"] >= 1

    await until(aborted, timeout=5)  # the mod saw its client go away


async def test_mod_errors_pass_through_unchanged(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok/v1/nope")
    assert r.status_code == 404 and r.json() == {"detail": "no route /v1/nope"}
    assert "x-aihub-error" not in r.headers


async def test_redirects_stay_inside_the_proxy(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok/v1/redirect")
        assert r.status_code == 307 and r.headers["location"] == "/api/s/fake-ok/v1/status"
        r = await c.get("/api/s/fake-ok/v1/redirect", follow_redirects=True)
    assert r.status_code == 200 and "stats" in r.json()


async def test_root_path_and_head(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok")
        assert r.status_code == 404 and r.json() == {"detail": "no route /"}
        r = await c.head("/api/s/fake-ok/health")
    assert r.status_code in (200, 501)  # the stdlib server has no do_HEAD: 501, passed through


async def test_unknown_and_stopped_mods(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/nope/x")
        assert (r.status_code, r.json()["code"], r.headers["x-aihub-error"]) == (404, "service_not_found", "service_not_found")
        await hub.services.stop("fake-ok", wait=True)
        r = await c.get("/api/s/fake-ok/health")
    assert r.status_code == 503 and r.json()["code"] == "service_not_running"
    assert r.json()["detail"] == "Fake OK is not running (state: stopped)" and r.headers["x-aihub-error"] == "service_not_running"


async def test_unreachable_mod_is_502(hub):
    svc = hub.services.get("fake-ok")
    os.kill(svc.pid, signal.SIGKILL)  # gone, but the monitor hasn't noticed yet
    await asyncio.sleep(0.01)
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok/health")
    if r.status_code == 503:  # the monitor was faster; still the hub's own error
        assert r.json()["code"] == "service_not_running"
    else:
        assert r.status_code == 502 and r.json()["code"] == "upstream_error" and "didn't answer" in r.json()["detail"]
    assert svc.in_flight == 0


async def test_tracking(hub):
    svc = hub.services.get("fake-ok")
    assert svc.last_request_ts is None
    async with httpx.AsyncClient(base_url=hub.url) as c:
        await c.get("/api/s/fake-ok/v1/status")
    assert svc.in_flight == 0 and time.time() - svc.last_request_ts < 5


async def test_before_proxy_hook_runs(hub):
    seen: list[tuple[str, str, str]] = []

    async def hook(svc, method, path):
        seen.append((svc.id, method, path))

    hub.services.before_proxy.append(hook)
    async with httpx.AsyncClient(base_url=hub.url) as c:
        await c.post("/api/s/fake-ok/v1/speech?x=1", json={"text": "a"})
    assert seen == [("fake-ok", "POST", "/v1/speech")]


async def test_encoded_path_is_kept(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok/v1/a%2Fb%20c")
    assert r.json() == {"detail": "no route /v1/a%2Fb%20c"}


async def test_no_gzip_on_proxied_streams(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/s/fake-ok/v1/events", headers={"accept-encoding": "gzip"})
    assert "content-encoding" not in r.headers
