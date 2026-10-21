"""`ANY /api/s/{id}/{path}`: a mod's own API through the hub (plan 2.5, architecture §5).

Bodies stream both ways, so uploads, audio and server-sent events pass through
without being buffered. The mod's responses, errors included, are returned
unchanged, plus `X-Content-Type-Options: nosniff` and, on documents (HTML, SVG, XML or
untyped), `Content-Security-Policy: sandbox`, so a file a mod serves can't run script as
the hub. The hub only answers itself (with the error envelope) when the mod isn't running (503 `service_not_running`) or can't be reached (502 `upstream_error`).

WebSockets pass through too (plan 29.2, the stt mod's live stream): text and binary
messages both ways until either side closes. A page from another origin is refused
at the handshake (HTTP 403, `utils/origin.py`). Otherwise the hub accepts and closes
with a code the browser can read: 4404 no such mod, 4503 not running, 4502 it didn't accept. The connection counts as a request in flight, so the mod isn't idle-unloaded.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from utils import origin
from utils.services import Service, ServiceError

if TYPE_CHECKING:
    from utils.services import ServiceManager

router = APIRouter()

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
    "transfer-encoding", "upgrade", "proxy-connection",
}
DOCUMENT_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml", "text/xsl"}
TIMEOUT = httpx.Timeout(connect=3.0, write=300.0, read=None, pool=10.0)

# Awaited before a request is sent: (service, method, path, request headers). The memory
# triggers (plan 5.5) make room here, or raise 409 needs_room.
BeforeHook = Callable[[Service, str, str, Any], Awaitable[None]]


def make_client() -> httpx.AsyncClient:
    # trust_env=False: an HTTP(S)_PROXY in the environment must never catch loopback traffic.
    return httpx.AsyncClient(
        trust_env=False, timeout=TIMEOUT, follow_redirects=False,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30),
    )


def _forward_headers(request: Request, prefix: str) -> list[tuple[bytes, bytes]]:
    drop = HOP_BY_HOP | {"host"}
    # Headers named in `Connection:` are hop-by-hop too.
    for token in request.headers.get("connection", "").split(","):
        drop.add(token.strip().lower())
    out = [(k, v) for k, v in request.headers.raw if k.decode("latin-1").lower() not in drop]
    host = request.headers.get("host", "")
    out += [
        (b"x-forwarded-prefix", prefix.encode()),
        (b"x-forwarded-host", host.encode("latin-1")),
        (b"x-forwarded-proto", request.url.scheme.encode()),
    ]
    return out


def _response_headers(resp: httpx.Response, svc: Service, prefix: str) -> list[tuple[bytes, bytes]]:
    drop = set(HOP_BY_HOP)
    for token in resp.headers.get("connection", "").split(","):
        drop.add(token.strip().lower())
    out = []
    for k, v in resp.headers.raw:
        lk = k.decode("latin-1").lower()
        if lk in drop:
            continue
        if lk == "location":
            v = _rewrite_location(v.decode("latin-1"), svc, prefix).encode("latin-1")
        out.append((lk.encode("latin-1"), v))
    return out + _guard_headers(resp)


def _guard_headers(resp: httpx.Response) -> list[tuple[bytes, bytes]]:
    """A mod's response is served from the hub's origin: no type sniffing, and a document (HTML, SVG, XML, or
    no type at all) opens sandboxed, so a file a mod serves can't run script as the hub."""
    out = []
    if "x-content-type-options" not in resp.headers:
        out.append((b"x-content-type-options", b"nosniff"))
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if not ctype or ctype in DOCUMENT_TYPES or ctype.endswith("+xml"):
        out.append((b"content-security-policy", b"sandbox"))     # adds to any policy the mod sent
    return out


def _rewrite_location(v: str, svc: Service, prefix: str) -> str:
    """Keep redirects inside the proxy: `/x` and `http://127.0.0.1:<port>/x` become `<prefix>/x`."""
    for base in (svc.url, f"http://localhost:{svc.port}"):
        if v.startswith(base):
            return prefix + (v[len(base):] or "/")
    if v.startswith("/") and not v.startswith("//"):
        return prefix + v
    return v


def _upstream_path(request: Request, service_id: str) -> str:
    """The path after `/api/s/<id>`, still percent-encoded as the client sent it."""
    raw = request.scope.get("raw_path") or request.url.path.encode()
    path = raw.decode("latin-1")
    prefix = f"/api/s/{service_id}"
    rest = path[len(prefix):] if path.startswith(prefix) else "/" + request.path_params.get("path", "")
    return rest or "/"


async def forward(mgr: ServiceManager, request: Request, service_id: str) -> StreamingResponse:
    svc = mgr.get(service_id)
    if not svc.up:
        state = svc.state if not svc.errors else "failed (manifest errors)"
        raise ServiceError(503, "service_not_running", f"{svc.mod.name} is not running (state: {state})", {"state": svc.state})
    prefix = f"/api/s/{service_id}"
    path = _upstream_path(request, service_id)
    query = request.scope.get("query_string", b"")
    url = svc.url + path + ("?" + query.decode("latin-1") if query else "")
    method = request.method

    for hook in mgr.before_proxy:
        await hook(svc, method, path, request.headers)

    has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
    req = mgr.proxy_client.build_request(
        method, url, headers=_forward_headers(request, prefix), content=request.stream() if has_body else None,
    )
    svc.in_flight += 1
    svc.last_request_ts = time.time()
    try:
        resp = await mgr.proxy_client.send(req, stream=True)
    except httpx.HTTPError as e:
        svc.in_flight -= 1
        why = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        raise ServiceError(502, "upstream_error", f"{svc.mod.name} didn't answer on {svc.url} ({why})") from None
    except BaseException:
        svc.in_flight -= 1
        raise

    done = False

    async def finish() -> None:
        nonlocal done
        if not done:
            done = True
            svc.in_flight -= 1
            svc.last_request_ts = time.time()
            await resp.aclose()

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            # Runs when the stream ends and when the client disconnects (the task is cancelled).
            await finish()

    out = StreamingResponse(body(), status_code=resp.status_code, background=BackgroundTask(finish))
    # The mod's headers exactly (repeated ones like Set-Cookie kept), instead of Starlette's defaults.
    out.raw_headers = _response_headers(resp, svc, prefix)
    return out


@router.api_route("/api/s/{service_id}", methods=METHODS, include_in_schema=False)
@router.api_route("/api/s/{service_id}/{path:path}", methods=METHODS, include_in_schema=False)
async def proxy(request: Request, service_id: str, path: str = "") -> StreamingResponse:
    return await forward(request.app.state.hub.services, request, service_id)


def _own_origin(ws: WebSocket) -> bool:
    """No Origin (not a browser page), or the hub's own page (`utils/origin.py`; the middleware checks it too)."""
    hub = ws.app.state.hub
    return origin.refusal({k.lower(): v for k, v in ws.headers.items()}, hub.allowed_hosts, hub.port) is None


@router.websocket("/api/s/{service_id}/{path:path}")
async def proxy_ws(ws: WebSocket, service_id: str, path: str = "") -> None:
    import websockets

    if not _own_origin(ws):
        await ws.close(code=1008)                # before accept: the handshake gets HTTP 403
        return
    mgr = ws.app.state.hub.services
    try:
        svc = mgr.get(service_id)
    except ServiceError:
        await ws.accept()
        await ws.close(code=4404, reason=f"no mod {service_id}")
        return
    if not svc.up:
        await ws.accept()
        await ws.close(code=4503, reason=f"{svc.mod.name} is not running")
        return
    query = ws.scope.get("query_string", b"").decode("latin-1")
    url = "ws" + svc.url[len("http"):] + "/" + path + (f"?{query}" if query else "")
    try:
        upstream = await websockets.connect(url, max_size=None, open_timeout=5, proxy=None,
                                            additional_headers={"X-Forwarded-Prefix": f"/api/s/{service_id}"})
    except (OSError, websockets.WebSocketException, TimeoutError) as e:
        await ws.accept()
        await ws.close(code=4502, reason=f"{svc.mod.name} didn't accept the connection ({type(e).__name__})"[:120])
        return
    await ws.accept()
    svc.in_flight += 1
    svc.last_request_ts = time.time()

    async def up() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            await upstream.send(msg["bytes"] if msg.get("bytes") is not None else msg.get("text") or "")

    async def down() -> None:
        async for msg in upstream:
            await ws.send_bytes(msg) if isinstance(msg, bytes) else await ws.send_text(msg)

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        code, reason = upstream.close_code or 1000, upstream.close_reason or ""
        await upstream.close()
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=code if code != 1005 else 1000, reason=reason)
        svc.in_flight -= 1
        svc.last_request_ts = time.time()
