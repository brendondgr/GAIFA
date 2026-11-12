"""Plan lan-access 3.2–3.3: HTTPS for devices on the network: its origin, `https = "only"`, the trust page."""

from __future__ import annotations

import httpx
import pytest

from utils.config import LanCfg
from utils.lan import addresses, cert
from utils.tests.lan.test_addresses import RAW
from utils.tests.lan.test_guard import HOST, PASSWORD, PHONE


@pytest.fixture
async def app(make_app):
    app = make_app(port=7000, extra_hosts=())
    lan = app.state.hub.lan
    lan._fixed = addresses.interfaces(RAW)
    lan.reconfigure(LanCfg(enabled=True, https="only"))
    lan.listening = lan.https_listening = True
    lan.auth.set_password(PASSWORD)
    async with app.router.lifespan_context(app):
        yield app


def device(app, scheme="http", port=7000):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(PHONE, 51000)),
                             base_url=f"{scheme}://192.168.1.19:{port}", follow_redirects=False)


async def test_only_https_plain_http_redirects_there(app):
    async with device(app) as c:
        r = await c.get("/chat/x?y=1")
        assert r.status_code == 308 and r.headers["location"] == "https://192.168.1.19:7443/chat/x?y=1"
    async with device(app, "https", 7443) as c:
        assert (await c.get("/signin")).status_code == 200
        r = await c.post("/api/lan/signin", json={"password": PASSWORD}, headers={"Origin": "https://192.168.1.19:7443"})
        assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()
        assert (await c.post("/api/services/x/stop", headers={"Origin": "https://192.168.1.19:7443"})).status_code == 404   # its own origin
        assert (await c.post("/api/services/x/stop", headers={"Origin": "http://192.168.1.19:7443"})).status_code == 403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5)), base_url="http://127.0.0.1:7000") as here:
        assert (await here.get("/api/sessions")).status_code == 200            # this machine is never redirected


@pytest.mark.skipif(not cert.available(), reason="needs the openssl command")
async def test_the_trust_page_and_the_certificate(app):
    async with device(app, "https", 7443) as c:
        assert (await c.get("/lan/ca.crt")).status_code == 404                  # none yet
        cert.ensure(app.state.hub.paths.state, ["bdgr"], ["192.168.1.19"], "bdgr")
        r = await c.get("/lan/ca.crt")
        assert r.status_code == 200 and r.content.startswith(b"-----BEGIN CERTIFICATE-----") and b"PRIVATE" not in r.content
        page = await c.get("/lan/trust")
        assert page.status_code == 200 and cert.fingerprint(app.state.hub.paths.state) in page.text
    st = app.state.hub.lan.status()
    assert st["https_listening"] is True and st["ca_fingerprint"] and st["urls"][0] == "https://192.168.1.19:7443"
