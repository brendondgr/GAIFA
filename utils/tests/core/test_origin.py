"""The Host and Origin rules (`utils/origin.py`): DNS rebinding and cross-site requests are refused,
the hub's own page, curl and the mods' clients aren't. (Streams through the guard: test_server's SSE
test and test_proxy, on a real uvicorn hub.)"""

from __future__ import annotations

import httpx
import pytest

from utils import origin

HOSTS = origin.LOOPBACK_HOSTS
OWN = "http://127.0.0.1:7000"


@pytest.mark.parametrize("value, ok", [
    ("127.0.0.1:7000", True), ("127.0.0.1", True), ("localhost:7000", True), ("LOCALHOST:1", True), ("[::1]:7000", True),
    ("attacker.example:7000", False), ("127.0.0.1.nip.io:7000", False), ("127.attacker.com", False),
    ("evil.localhost:7000", False), ("localhost.", False), ("127.0.0.2:7000", False), ("127.0.0.1@evil.example", False),
    ("127.0.0.1:7000/x", False), ("127.0.0.1:abc", False), ("", False), (None, False),
])
def test_host_names_this_machine(value, ok):
    assert origin.host_ok(value, HOSTS) is ok


@pytest.mark.parametrize("value, ok", [
    (OWN, True), ("http://localhost:7000", True), ("http://[::1]:7000", True), ("HTTP://LOCALHOST:7000", True),
    ("http://127.0.0.1", False), ("http://127.0.0.1:5070", False), ("https://127.0.0.1:7000", False),
    ("http://127.attacker.com:7000", False), ("https://127.0.0.1.nip.io", False), ("http://evil.localhost:7000", False),
    ("null", False), ("", False), ("http://127.0.0.1:7000/path", False), ("http://user@127.0.0.1:7000", False),
])
def test_same_origin_is_the_hubs_own_page(value, ok):
    assert origin.same_origin(value, HOSTS, 7000) is ok
    assert origin.same_origin("http://127.0.0.1", HOSTS, 80)       # the default port counts


@pytest.fixture
async def hub(make_app):
    app = make_app(port=7000, extra_hosts=())          # production's allowlist: loopback names only
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=OWN) as c:
            yield c


async def test_a_foreign_host_is_refused_dns_rebinding(hub):
    for method in ("GET", "POST"):
        r = await hub.request(method, "/api/sessions", headers={"Host": "attacker.example:7000", "Origin": "http://attacker.example:7000"})
        assert r.status_code == 421 and r.headers["x-gaifa-error"] == "bad_host"
        assert r.json()["code"] == "bad_host" and "127.0.0.1:7000" in r.json()["data"]["fix"]
    assert (await hub.get("/api/sessions", headers={"Host": "127.0.0.1.nip.io:7000"})).status_code == 421
    assert (await hub.get("/", headers={"Host": "attacker.example"})).status_code == 421       # the UI too
    for host in ("127.0.0.1:7000", "localhost:7000", "[::1]:7000", "localhost"):
        assert (await hub.get("/api/sessions", headers={"Host": host})).status_code == 200, host


async def test_cross_site_unsafe_requests_are_refused(hub):
    """A page elsewhere can POST without a preflight (`mode: 'no-cors'`): refused when it says where it's from."""
    stop = "/api/services/x/stop"
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Origin": "http://127.0.0.1:5070"},
                    {"Origin": "http://127.attacker.com:7000"}, {"Sec-Fetch-Site": "cross-site"},
                    {"Origin": OWN, "Sec-Fetch-Site": "cross-site"}):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            r = await hub.request(method, stop, headers=headers)
            assert r.status_code == 403 and r.json()["code"] == "cross_origin", (method, headers)
    r = await hub.post("/api/outputs/upload?name=planted.txt", content=b"hi", headers={"Origin": "https://evil.example",
                                                                                        "Content-Type": "text/plain"})
    assert r.status_code == 403 and r.json()["data"]["fix"] == "open GAIFA at http://127.0.0.1:7000"
    # the hub's own page (by any loopback name), and clients that aren't pages: through to the route (no mod x: 404)
    for headers in ({}, {"Origin": OWN, "Sec-Fetch-Site": "same-origin"}, {"Origin": "http://localhost:7000"},
                    {"Origin": "http://[::1]:7000"}, {"Sec-Fetch-Site": "none"}):
        assert (await hub.post(stop, headers=headers)).status_code == 404, headers
    # reads aren't changed: a foreign page can send them but can't read the answer (no CORS headers)
    r = await hub.get("/api/sessions", headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers



async def test_a_repeated_host_or_origin_is_foreign():
    """Two Host headers (the real one first) or two Origins: neither is believed."""
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["path"])

    class Hub:
        allowed_hosts, port = HOSTS, 7000

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    guard = origin.RequestGuard(app, Hub())
    for headers in ([(b"host", b"127.0.0.1:7000"), (b"host", b"attacker.example")],
                    [(b"host", b"127.0.0.1:7000"), (b"origin", OWN.encode()), (b"origin", b"https://evil.example")]):
        sent.clear()
        await guard({"type": "http", "method": "POST", "path": "/api/services/x/stop", "headers": headers}, None, send)
        assert sent[0]["status"] in (421, 403)
    await guard({"type": "http", "method": "POST", "path": "/ok", "headers": [(b"host", b"127.0.0.1:7000")]}, None, send)
    assert seen == ["/ok"]
