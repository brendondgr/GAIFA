"""`ANY /api/s/{id}/{path}`: a mod's own API through the hub (plan 2.5, architecture §5).

Bodies stream both ways, so uploads, audio and server-sent events pass through
without being buffered. The mod's responses, errors included, are returned
unchanged; the hub only answers itself (with the error envelope) when the mod
isn't running (503 `service_not_running`) or can't be reached (502 `upstream_error`).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from utils.services import Service, ServiceError

if TYPE_CHECKING:
    from utils.services import ServiceManager

router = APIRouter()

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
    "transfer-encoding", "upgrade", "proxy-connection",
}
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
