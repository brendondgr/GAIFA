"""29.2: WebSockets through /api/s/<id>/*, against a real uvicorn hub and a WebSocket echo mod."""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from utils.tests.services.conftest import free_port, ready, until


def echo_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.websocket("/v1/echo")
    async def echo(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({"query": dict(ws.query_params), "prefix": ws.headers.get("x-forwarded-prefix")})
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("text") == "bye":
                    await ws.close(code=4001, reason="asked to")
                    return
                if msg.get("bytes") is not None:
                    await ws.send_bytes(msg["bytes"][::-1])
                else:
                    await ws.send_text(msg["text"].upper())
        except WebSocketDisconnect:
            return

    return app


@pytest.fixture
async def ws_hub(rig, serve):
    port = free_port()
    (rig.services / "ws-echo").mkdir()
    (rig.services / "ws-echo" / "service.toml").write_text(
        f'id = "ws-echo"\nname = "WS echo"\n[run]\nkind = "external"\nport = {port}\nhealth = "/health"\n')
    server = uvicorn.Server(uvicorn.Config(echo_app(), host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    await until(lambda: server.started, timeout=10)
    served = await serve()
    await ready(served, "ws-echo")
    yield served
    server.should_exit = True
    with contextlib.suppress(Exception):
        await asyncio.wait_for(task, 10)


async def handshake(hub, host: str) -> int:
    """The status a WebSocket handshake sent with this Host header gets (the client libraries set their own Host)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", hub.port)
    writer.write((f"GET /api/s/ws-echo/v1/echo HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await writer.drain()
    status = int((await asyncio.wait_for(reader.readline(), 10)).split()[1])
    writer.close()
    return status


def ws_url(hub, path: str) -> str:
    return hub.url.replace("http", "ws", 1) + path


async def test_text_and_binary_pass_both_ways_with_the_query(ws_hub):
    async with websockets.connect(ws_url(ws_hub, "/api/s/ws-echo/v1/echo?lang=en&n=2")) as ws:
        first = await ws.recv()
        assert '"lang":"en"' in first and '"/api/s/ws-echo"' in first
        await ws.send("hello")
        assert await ws.recv() == "HELLO"
        await ws.send(b"\x01\x02\x03")
        assert await ws.recv() == b"\x03\x02\x01"
        svc = ws_hub.services.get("ws-echo")
        assert svc.in_flight == 1
    await until(lambda: svc.in_flight == 0)


async def test_the_mods_close_code_reaches_the_client(ws_hub):
    async with websockets.connect(ws_url(ws_hub, "/api/s/ws-echo/v1/echo")) as ws:
        await ws.recv()
        await ws.send("bye")
        with pytest.raises(websockets.ConnectionClosed):
            await ws.recv()
    assert ws.close_code == 4001 and ws.close_reason == "asked to"


async def test_a_foreign_page_and_a_stopped_mod_are_refused(ws_hub):
    # names that only look like this machine, another port on it, https, a sandboxed page
    for bad in ("https://evil.example", "http://127.attacker.com", f"http://127.0.0.1.nip.io:{ws_hub.port}",
                "http://evil.localhost", "http://127.0.0.1:5070", f"https://127.0.0.1:{ws_hub.port}", "null"):
        with pytest.raises(websockets.InvalidStatus, match="403"):
            await websockets.connect(ws_url(ws_hub, "/api/s/ws-echo/v1/echo"), origin=bad)
    assert await handshake(ws_hub, "attacker.example") == 403            # DNS rebinding: a foreign Host
    assert await handshake(ws_hub, f"127.0.0.1:{ws_hub.port}") == 101
    async with websockets.connect(ws_url(ws_hub, "/api/s/ws-echo/v1/echo"), origin=ws_hub.url) as ws:
        assert "query" in await ws.recv()
    async with websockets.connect(ws_url(ws_hub, "/api/s/nope/v1/echo")) as ws:
        with pytest.raises(websockets.ConnectionClosed):
            await ws.recv()
    assert ws.close_code == 4404
