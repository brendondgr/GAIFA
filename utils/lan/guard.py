"""Who may come in from the network (plan lan-access 1.3), beside `utils/origin.py`'s rules for this machine.

A request is from the network when its connection's address (never a header) isn't loopback. Then, in order:

1. GAIFA isn't open to the network, or the address isn't on this machine's own network (or `allow`): 403 `not_local`.
2. The `Host` isn't one of this machine's names or network addresses: 421 `bad_host` (DNS rebinding stays closed).
3. An unsafe method or a WebSocket with an `Origin` from anywhere but GAIFA's own address, or `Sec-Fetch-Site:
   cross-site`: 403 `cross_origin`.
4. The sign-in page and its two routes are open; everything else needs a signed-in device's cookie: 401 `sign_in`
   for the API (a WebSocket is closed), a redirect to `/signin` for a page.
5. What stays on this machine (`limits.py`): 403 `this_machine_only`.

The device's session is put in `scope["state"]["lan"]`.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import quote

from utils.lan import limits
from utils.lan.auth import COOKIE

OPEN = {("GET", "/signin"), ("POST", "/api/lan/signin"), ("GET", "/lan/ca.crt"), ("GET", "/lan/trust"), ("GET", "/favicon.ico")}
MAX_BODY = 1 << 20


def cookie(headers: dict[str, str]) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
    except Exception:                          # noqa: BLE001 - a malformed cookie header is no session
        return None
    m = c.get(COOKIE)
    return m.value if m else None


def origin_ok(origin: str, hosts: set[str], ports: set[int], https_port: int | None) -> bool:
    from utils.origin import _ORIGIN, split_host

    m = _ORIGIN.match(origin.strip())
    if not m or m.group(1).lower() not in ("http", "https"):
        return False
    parts = split_host(m.group(2))
    if parts is None or parts[0] not in hosts:
        return False
    scheme = m.group(1).lower()
    port = parts[1] or (443 if scheme == "https" else 80)
    return port in ports and (scheme == "http") == (port != https_port)


async def _body(receive: Any) -> tuple[bytes, list[dict[str, Any]], bool]:
    """Read a request's body for the limits; (body, the messages to replay, too long)."""
    msgs, body = [], b""
    while True:
        m = await receive()
        msgs.append(m)
        if m["type"] != "http.request":
            break
        body += m.get("body", b"")
        if len(body) > MAX_BODY:
            return body, msgs, True
        if not m.get("more_body"):
            break
    return body, msgs, False


def _replay(msgs: list[dict[str, Any]], receive: Any):
    queue = list(msgs)

    async def again() -> dict[str, Any]:
        return queue.pop(0) if queue else await receive()
    return again


async def gate(lan: Any, scope: dict[str, Any], receive: Any, send: Any, headers: dict[str, str], client: str,
               refuse: Any, app: Any) -> None:
    """A request from the network: refused, or passed to `app` (module doc)."""
    ws = scope["type"] == "websocket"
    method, path = ("GET" if ws else scope.get("method", "GET")), scope.get("path", "")
    where = "Open GAIFA on the GAIFA machine, or turn on Settings → General → Network there."
    if lan is None or not lan.on or not lan.is_local(client):
        return await refuse(scope, receive, send, 403, "not_local", "GAIFA isn't open to this device.", where)
    from utils.origin import host_ok

    hosts = lan.hosts()
    if not host_ok(headers.get("host"), hosts):
        return await refuse(scope, receive, send, 421, "bad_host", "GAIFA only answers requests addressed to this machine.",
                            f"open {lan.urls()[0] if lan.urls() else 'GAIFA by its address'}")
    if lan.cfg.https == "only" and lan.https_listening and scope.get("scheme") == "http" and not ws:
        from utils.origin import split_host

        name = split_host(headers.get("host", ""))[0]
        name = f"[{name}]" if ":" in name else name
        target = f"https://{name}:{lan.https_port}{path}" + (("?" + scope["query_string"].decode("latin-1")) if scope.get("query_string") else "")
        await send({"type": "http.response.start", "status": 308, "headers": [(b"location", target.encode()), (b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})
        return None
    origin = headers.get("origin")
    if (ws or method in limits.UNSAFE) and ((origin is not None and not origin_ok(origin, hosts, lan.ports(), lan.https_port))
                                            or headers.get("sec-fetch-site", "").strip().lower() == "cross-site"):
        return await refuse(scope, receive, send, 403, "cross_origin", "a page from another site can't change anything in GAIFA", where)
    if (method, path) in OPEN:
        return await app(scope, receive, send)
    if path == "/mcp" or path.startswith("/mcp/"):
        return await refuse(scope, receive, send, 403, "this_machine_only", limits.refused(method, path), limits.WHERE)
    session = lan.auth.session(cookie(headers), client)
    if session is None:
        if ws or path.startswith("/api/"):
            return await refuse(scope, receive, send, 401, "sign_in", "Sign in to GAIFA on this device first.", "open /signin")
        target = path + (("?" + scope["query_string"].decode("latin-1")) if scope.get("query_string") else "")
        await send({"type": "http.response.start", "status": 303, "headers": [(b"location", f"/signin?next={quote(target, safe='')}".encode()),
                                                                               (b"cache-control", b"no-store"), (b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})
        return None
    if not ws and limits.needs_body(method, path):
        raw, msgs, too_long = await _body(receive)
        receive = _replay(msgs, receive)
        try:
            body = None if too_long or not raw else json.loads(raw)
        except ValueError:
            body = None
        if too_long and "json" in headers.get("content-type", ""):      # too long to check: not let through
            return await refuse(scope, receive, send, 413, "too_large", "That request is too large.", where)
    else:
        body = None
    if why := limits.refused(method, path, body):
        return await refuse(scope, receive, send, 403, "this_machine_only", why, limits.WHERE)
    scope.setdefault("state", {})["lan"] = session
    return await app(scope, receive, send)
