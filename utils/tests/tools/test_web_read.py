"""Plan 30.8: `POST /api/web/read` reads a page for the user through the web mod (a fake one here), screens all of
its text in pieces, keeps the report with the output, and the agent's later reads (hub_read_document, the text
route with screened=true) reuse it."""

from __future__ import annotations

import httpx
import pytest

from utils.tests.conftest import free_port
from utils.tests.tools.conftest import ToolsHub, wait_ready
from utils.tests.tools.test_screen import fake_screen

WEB_TOML = """id = "web"
name = "Web"
[run]
command = ["python3", "../_fakepage.py"]
port = {port}
health = "/health"
status = "/v1/status"
env = {{ FAKE_PORT = "{{port}}", FAKE_OUTPUTS = "{{outputs}}" }}
start_timeout_s = 15
stop_timeout_s = 5
restart = "no"
[outputs]
kinds = ["text"]
"""


@pytest.fixture
async def web(services_dir, make_app, tools_cfg):
    services = services_dir()                                  # the fake mods' helpers, _fakepage.py among them
    (services / "web").mkdir()
    (services / "web" / "service.toml").write_text(WEB_TOML.format(port=free_port()))
    app = make_app(tools_cfg, port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            await wait_ready(c, "web")
            yield ToolsHub(app, c, services.parent)


def counting(monkeypatch) -> list[int]:
    """Count calls to screen() (after fake_screen has patched it)."""
    import utils.tools.screen as sc

    calls, inner = [], sc.screen

    async def counted(text, *a, **k):
        calls.append(len(text))
        return await inner(text, *a, **k)
    monkeypatch.setattr(sc, "screen", counted)
    return calls


async def test_a_page_is_read_saved_and_screened_whole(web, monkeypatch):
    fake_screen(monkeypatch)                                   # a relay that flags passages saying "banana"
    calls = counting(monkeypatch)
    r = await web.client.post("/api/web/read", json={"url": "https://example.org/long", "text": True})
    assert r.status_code == 200, r.text
    page = r.json()
    o = page["output"]
    assert o["service"] == "web" and o["kind"] == "text" and page["title"] == "Long page" and page["kind"] == "text"
    assert page["chars"] > 30000 and page["markdown"].index("banana") > 20000      # past any first max_chars
    s = page["screening"]
    assert s["removed"] == 1 and s["checked"] == "patterns+model" and s["covered"] == page["chars"]
    assert s["findings"][0]["why"] == "aimed at an AI" and "AI assistants" in s["findings"][0]["excerpt"]
    assert "banana" not in page["screened"] and "[removed by screening: aimed at an AI]" in page["screened"]
    assert page["screened"].count("\n") == page["markdown"].count("\n")           # lines stay put
    assert calls == [page["chars"]]                            # the whole page in one screening
    assert (web.hub.paths.outputs / ".text" / f"{o['id']}.screening.json").is_file()

    # the agent's reads reuse the report: no screening again
    at = page["markdown"].index("banana") - 300
    got = (await web.call("hub_read_document", {"ref": f"output:{o['id']}", "offset": at, "limit": 2000}))["result"]
    assert "banana" not in got and "[removed by screening: aimed at an AI]" in got and "Screening removed 1 passage" in got
    w = (await web.client.get(f"/api/outputs/{o['id']}/text", params={"offset": at, "limit": 2000, "screened": "true"})).json()
    assert "banana" not in w["text"] and any("Screening removed 1" in n for n in w["notes"])
    assert calls == [page["chars"]]
    raw = (await web.client.get(f"/api/outputs/{o['id']}/text", params={"offset": at, "limit": 2000})).json()
    assert "banana" in raw["text"]                             # the user's own view: the page as it is

    web.hub.config.agent.screen.window_chars = 6000            # another screening setup: the report isn't reused
    await web.call("hub_read_document", {"ref": f"output:{o['id']}", "offset": at, "limit": 2000})
    assert len(calls) == 2

    r = await web.client.post("/api/web/read", json={"url": "https://example.org/short"})
    assert r.status_code == 200 and r.json()["screening"]["removed"] == 0 and "markdown" not in r.json()


async def test_screening_off_and_refusals(web, monkeypatch):
    fake_screen(monkeypatch)
    r = await web.client.post("/api/web/read", json={"url": "http://127.0.0.1/admin"})
    assert r.status_code == 403 and r.json()["code"] == "blocked_address" and r.json()["data"]["fix"]
    r = await web.client.post("/api/web/read", json={"url": "https://example.org/missing"})
    assert r.status_code == 502 and r.json()["code"] == "http_error"
    web.hub.config.agent.screen.pages = False
    r = await web.client.post("/api/web/read", json={"url": "https://example.org/long"})
    assert r.status_code == 200 and "screening" not in r.json()


async def test_without_the_web_mod(client):
    r = await client.post("/api/web/read", json={"url": "https://example.org/long"})
    assert r.status_code == 404 and r.json()["code"] == "service_not_found"

