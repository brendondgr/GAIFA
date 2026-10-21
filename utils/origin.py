"""Who may talk to the hub: the Host and Origin rules (architecture §5).

The hub has no login; what keeps other websites out is that only this machine can reach
127.0.0.1. Two browser tricks get around that, and `RequestGuard` (pure ASGI, so streams,
server-sent events and WebSockets pass through untouched) refuses both:

- **DNS rebinding.** A page on `attacker.example` re-points its name at 127.0.0.1 and is
  then same-origin with the hub. Its requests carry `Host: attacker.example`, so a request
  whose Host isn't a loopback name (`127.0.0.1`, `localhost`, `[::1]`, any port) gets
  421 `bad_host` (a WebSocket handshake: 403). A repeated Host or Origin counts as foreign.
- **Cross-site requests.** Any page can send a "simple" POST (no preflight) to the hub. An
  unsafe method (POST, PUT, PATCH, DELETE) or a WebSocket handshake that carries an `Origin`
  must come from the hub's own origin (`http://<loopback name>:<hub port>`), and one marked
  `Sec-Fetch-Site: cross-site` is refused too: 403 `cross_origin`. Requests without an Origin
  (curl, the mods' clients, MCP clients) aren't browser pages and stay allowed.

`/mcp` answers its own refusals as JSON-RPC errors with the same check (`utils/tools/mcp.py`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_HOST = re.compile(r"^(?:\[([0-9A-Fa-f:.]+)\]|([A-Za-z0-9.-]+))(?::(\d{1,5}))?$")
_ORIGIN = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.+)$")


def split_host(value: str) -> tuple[str, int | None] | None:
    """`127.0.0.1:7000` → ("127.0.0.1", 7000); `[::1]` → ("::1", None); anything else (userinfo, paths, junk) → None."""
    m = _HOST.match(value.strip())
    if not m:
        return None
    return (m.group(1) or m.group(2)).lower(), int(m.group(3)) if m.group(3) else None


def host_ok(value: str | None, hosts: Iterable[str]) -> bool:
    """The Host header names this machine (any port)."""
    parts = split_host(value) if value else None
    return parts is not None and parts[0] in hosts


def same_origin(origin: str, hosts: Iterable[str], port: int) -> bool:
    """`origin` is the hub's own: http, a loopback name, the hub's port. `null` and the rest aren't."""
    m = _ORIGIN.match(origin.strip())
    if not m or m.group(1).lower() != "http":
        return False
    parts = split_host(m.group(2))
    return parts is not None and parts[0] in hosts and (parts[1] or 80) == port


def refusal(headers: Mapping[str, str], hosts: Iterable[str], port: int) -> str | None:
    """Why an unsafe request or a WebSocket handshake comes from another site, or None when it doesn't.
    `headers` keys are lowercase."""
    origin = headers.get("origin")
    if origin is not None and not same_origin(origin, hosts, port):
        return f"a page from {origin[:100]!r} can't change anything in AIHub"
    if headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        return "a page from another site can't change anything in AIHub"
    return None


def _headers(scope: Mapping[str, Any]) -> dict[str, str]:
    """Lowercase names; a repeated Host or Origin is joined ("a, b"), which no check accepts."""
    out: dict[str, str] = {}
    for k, v in scope.get("headers") or []:
        name, value = k.decode("latin-1").lower(), v.decode("latin-1")
        if name in out and name in ("host", "origin"):
            out[name] += ", " + value
        else:
            out.setdefault(name, value)
    return out


class RequestGuard:
    """Pure ASGI middleware: refuses foreign Host headers and cross-site unsafe requests (module doc).
    `hub` gives `allowed_hosts` and `port`, read on each request."""

    def __init__(self, app: Any, hub: Any) -> None:
        self.app, self.hub = app, hub

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        hosts, port = self.hub.allowed_hosts, self.hub.port
        if not host_ok(headers.get("host"), hosts):
            await self._refuse(scope, receive, send, 421, "bad_host",
                               f"AIHub only answers requests addressed to this machine, not {headers.get('host', '')[:100]!r}",
                               f"open AIHub at http://127.0.0.1:{port}")
            return
        ws = scope["type"] == "websocket"
        # /mcp answers its own refusals (as JSON-RPC errors), with the same check.
        if (ws or (scope.get("method") in UNSAFE and scope.get("path") != "/mcp")) and (why := refusal(headers, hosts, port)):
            await self._refuse(scope, receive, send, 403, "cross_origin", why, f"open AIHub at http://127.0.0.1:{port}")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: dict[str, Any], receive: Any, send: Any, status: int, code: str, detail: str, fix: str) -> None:
        if scope["type"] == "websocket":
            await receive()                      # websocket.connect
            await send({"type": "websocket.close", "code": 1008})     # before accept: the handshake gets HTTP 403
            return
        body = json.dumps({"detail": detail, "code": code, "data": {"fix": fix}}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"x-aihub-error", code.encode())]})
        await send({"type": "http.response.body", "body": body})
