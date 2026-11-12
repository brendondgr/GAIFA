"""Plan lan-access 1.3: a device on the network gets in only signed in, by this machine's names, from its own
network; this machine (loopback) is unchanged (test_origin.py)."""

from __future__ import annotations

import httpx
import pytest

from utils.config import LanCfg
from utils.lan import addresses
from utils.origin import RequestGuard
from utils.proxy import _without_session
from utils.tests.lan.test_addresses import RAW

PASSWORD = "a long enough password"
HOST = "192.168.1.19:7000"
PHONE = "192.168.1.50"


@pytest.fixture
async def app(make_app):
    app = make_app(port=7000, extra_hosts=())
    lan = app.state.hub.lan
    lan._fixed = addresses.interfaces(RAW)
    lan.reconfigure(LanCfg(enabled=True))
    lan.listening = True
    lan.auth.set_password(PASSWORD)
    async with app.router.lifespan_context(app):
        yield app


def device(app, addr=PHONE, host=HOST):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(addr, 51000)),
                             base_url=f"http://{host}", follow_redirects=False)


async def signed_in(app, addr=PHONE):
    c = device(app, addr)
    r = await c.post("/api/lan/signin", json={"password": PASSWORD}, headers={"Origin": f"http://{HOST}", "User-Agent": "Firefox/130 Android"})
    assert r.status_code == 200, r.text
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    return c


async def test_a_device_signs_in_and_then_uses_gaifa(app):
    async with device(app) as c:
        r = await c.get("/api/sessions")
        assert r.status_code == 401 and r.json()["code"] == "sign_in"
        r = await c.get("/", headers={"Accept": "text/html"})
        assert r.status_code == 303 and r.headers["location"] == "/signin?next=%2F"
        r = await c.get("/chat/x?y=1")
        assert r.headers["location"] == "/signin?next=%2Fchat%2Fx%3Fy%3D1"
        page = await c.get("/signin")
        assert page.status_code == 200 and "Sign in" in page.text and "frame-ancestors 'none'" in page.headers["content-security-policy"]
        r = await c.post("/api/lan/signin", json={"password": "wrong"})
        assert r.status_code == 401 and r.json()["code"] == "wrong_password"
    c = await signed_in(app)
    try:
        assert (await c.get("/api/sessions")).status_code == 200
        assert (await c.get("/")).status_code != 303                         # the page itself (no web/ in the test root)
        me = (await c.get("/api/lan/status")).json()
        assert me["remote"] is True and me["me"]["label"] == "Firefox on Android" and "devices" not in me
        assert (await c.post("/api/lan/signout", headers={"Origin": f"http://{HOST}"})).status_code == 200
        c.cookies.clear()
        assert (await c.get("/api/sessions")).status_code == 401
    finally:
        await c.aclose()


async def test_this_machine_sees_the_devices_and_needs_no_password(app, make_app):
    c = await signed_in(app)
    await c.aclose()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)), base_url="http://127.0.0.1:7000") as here:
        st = (await here.get("/api/lan/status")).json()
        assert st["remote"] is False and st["on"] is True and st["devices"][0]["addr"] == PHONE
        assert st["urls"] and all(u.startswith(("http://", "https://")) for u in st["urls"])
        sid = st["devices"][0]["id"]
        assert (await here.delete(f"/api/lan/sessions/{sid}")).status_code == 200
        assert (await here.get("/api/lan/status")).json()["devices"] == []


async def test_who_is_refused(app):
    c = await signed_in(app)
    async with device(app, "81.2.69.160") as outsider, device(app, "172.17.0.2") as container:
        for d in (outsider, container):
            r = await d.get("/signin")
            assert r.status_code == 403 and r.json()["code"] == "not_local"
        r = await c.get("/api/sessions", headers={"Host": "attacker.example:7000"})          # DNS rebinding
        assert r.status_code == 421 and r.json()["code"] == "bad_host"
        assert (await c.get("/api/sessions", headers={"Host": "localhost:7000"})).status_code == 421   # loopback names are this machine's
        for origin in ("https://evil.example", "null", "http://192.168.1.19:5070", "https://192.168.1.19:7000"):
            r = await c.post("/api/services/x/stop", headers={"Origin": origin})
            assert r.status_code == 403 and r.json()["code"] == "cross_origin", origin
        assert (await c.post("/api/services/x/stop", headers={"Origin": f"http://{HOST}"})).status_code == 404     # through to the route
        assert (await c.post("/api/services/x/stop", headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 403 and r.json()["code"] == "this_machine_only"
        for method, path, body in (("PUT", "/api/lan/password", {"password": "x" * 20}), ("PUT", "/api/lan/settings", {"enabled": False}),
                                   ("DELETE", "/api/lan/sessions/all", None), ("PUT", "/api/settings", {"hub": {"port": 7001}}),
                                   ("PATCH", "/api/s/agent/v1/threads/t_1", {"mode": "bypass"}),
                                   ("PATCH", "/api/s/workspace/v1/folders/f1", {"level": "run"})):
            r = await c.request(method, path, json=body)
            assert r.status_code == 403 and r.json()["code"] == "this_machine_only", (method, path)
        assert (await c.put("/api/settings", json={"voice_mode": {"talk": "push"}})).status_code == 200
    await c.aclose()


async def test_closed_to_the_network_nothing_answers(app):
    lan = app.state.hub.lan
    lan.reconfigure(LanCfg(enabled=False))
    async with device(app) as c:
        r = await c.get("/signin")
        assert r.status_code == 403 and r.json()["code"] == "not_local"
    lan.reconfigure(LanCfg(enabled=True))
    lan.listening = False                                        # turned on but not listening yet (no restart): still closed
    async with device(app) as c:
        assert (await c.get("/signin")).status_code == 403


async def test_a_websocket_without_a_session_is_closed(app):
    sent = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(m):
        sent.append(m)

    async def inner(scope, receive, send):
        raise AssertionError("not let through")

    guard = RequestGuard(inner, app.state.hub)
    scope = {"type": "websocket", "path": "/api/s/voice/v1/realtime", "client": (PHONE, 5), "headers": [(b"host", HOST.encode())]}
    await guard(scope, receive, send)
    assert sent == [{"type": "websocket.close", "code": 4401}]


def test_the_sign_in_cookie_never_reaches_a_mod():
    assert _without_session("a=1; gaifa_session=SECRET; b=2") == "a=1; b=2"
    assert _without_session("gaifa_session=SECRET") == ""
