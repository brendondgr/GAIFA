"""A page the chat's own search found: web_fetch of a URL that a web_search in the same chat returned
runs without a card in every mode but Plan; only that exact URL (after trivial normalisation), only in
that chat, and not a URL the judge's URL rules flag. Against fake-perms installed as the `web` mod."""

from __future__ import annotations

import re

import httpx
import pytest

from utils.tests.conftest import free_port
from utils.tests.tools.conftest import ToolsHub, wait_ready
from utils.tools import searched
from utils.tools.approvals import MODES, decide

SEARCH, FETCH = "web_search", "web_fetch"
FOUND = ["https://Example.org:443/trek#gear", "https://example.org/b?x=1", "https://example.org/login?token=abc123",
         "http://[2001:db8::1]:8080/p"]


@pytest.fixture
async def web(services_dir, root, make_app, tools_cfg):
    services = services_dir("fake-perms")
    (services / "fake-perms").rename(services / "web")
    toml = services / "web" / "service.toml"
    text = toml.read_text().replace('id = "fake-perms"', 'id = "web"')
    toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", text))
    app = make_app(tools_cfg, port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            await wait_ready(c, "web")
            yield ToolsHub(app, c, services.parent)


async def search(web, thread="t1", urls=FOUND) -> dict:
    r = await web.call(SEARCH, {"query": "trek gear " + " ".join(urls)}, thread=thread, service="agent")
    assert r["status"] == "done", r                         # the shipped web_search grant: no card
    return r


def test_normal_changes_only_what_cant_change_the_page():
    n = searched.normal
    assert n(" HTTPS://Example.ORG:443/trek#gear ") == "https://example.org/trek"
    assert n("http://example.org") == n("http://example.org:80/") == "http://example.org/"
    assert n("https://example.org/Trek") != n("https://example.org/trek")       # paths keep their case
    assert n("https://example.org/a/") != n("https://example.org/a")
    assert n("https://example.org/a?b=1&c=2") != n("https://example.org/a?c=2&b=1")
    assert n("https://example.org:8443/a") == "https://example.org:8443/a"
    assert n("http://[2001:DB8::1]:8080/p") == "http://[2001:db8::1]:8080/p"
    for bad in ("ftp://example.org/", "file:///etc/passwd", "https://user:pw@example.org/", "https://", "not a url",
                "https://example.org:99999/", None, 3):
        assert n(bad) is None, bad
    assert searched.urls_of({"results": [{"url": "https://A.org/x#y"}, {"url": 5}, "junk", {}]}) == {"https://a.org/x"}
    assert searched.urls_of({"results": "nope"}) == searched.urls_of(None) == set()


@pytest.mark.parametrize("mode", MODES)
def test_decide_lets_a_searched_page_run_except_in_plan(mode):
    from utils import config

    c = config.Config()
    want = "deny" if mode == "plan" else "allow"
    verdict, why = decide("web_fetch", "network", c, mode, searched=True)
    assert verdict == want and (mode == "plan" or why == "a page your search found")
    assert decide("web_fetch", "network", c, mode)[0] != "allow"          # without it, as before
    c.agent.permissions.ask = ["web_fetch"]                  # the user's ask list still asks
    assert decide("web_fetch", "network", c, mode, searched=True)[0] == ("deny" if mode == "plan" else "ask")
    c.agent.permissions.ask, c.agent.permissions.deny = [], ["web_*"]
    assert decide("web_fetch", "network", c, mode, searched=True)[0] == "deny"
    c.agent.permissions.deny = []
    assert decide("web_fetch", "execute", c, mode, searched=True)[0] != "allow"   # only read and network tools


async def test_a_url_the_chats_search_returned_runs_without_a_card(web):
    s = await search(web)
    r = await web.call(FETCH, {"url": "https://example.org/trek"}, thread="t1", service="agent")
    assert r["status"] == "done" and not r.get("approval_id") and r["result"]["ran"] == "fetch"
    row = await web.hub.db.fetchone("SELECT origin FROM tool_calls WHERE id = ?", (r["call_id"],))
    assert f'"found_by": "{s["call_id"]}"' in row["origin"]
    assert (await web.call(FETCH, {"url": "https://EXAMPLE.org/trek#other"}, thread="t1"))["status"] == "done"
    assert (await web.call(FETCH, {"url": "https://example.org/b?x=1"}, thread="t1"))["status"] == "done"
    assert (await web.call(FETCH, {"url": "http://[2001:db8::1]:8080/p"}, thread="t1"))["status"] != "done"   # private: fetch_rule asks


@pytest.mark.parametrize("url, thread", [
    ("https://example.org/trek/more", "t1"),             # no prefix matches
    ("https://example.org/tre", "t1"),
    ("https://example.org/b", "t1"),                     # another query is another URL
    ("https://example.org/b?x=1&leak=secret", "t1"),
    ("http://example.org/trek", "t1"),                   # another scheme
    ("https://example.org.evil.com/trek", "t1"),
    ("https://example.org/login?token=abc123", "t1"),    # carries credentials: the judge's URL rules flag it
    ("https://example.org/trek", "t2"),                  # another chat
    ("https://example.org/trek", None),                  # no chat (MCP)
])
async def test_anything_else_still_asks(web, url, thread):
    await search(web)
    origin = {"thread": thread} if thread else {}
    r = await web.call(FETCH, {"url": url}, **origin)
    assert r["status"] == "needs_approval", (url, thread, r)


async def test_plan_mode_and_the_deny_list_still_refuse(web):
    await search(web)
    assert (await web.call(FETCH, {"url": "https://example.org/trek"}, mode="plan", thread="t1"))["status"] == "denied"
    web.hub.config.agent.permissions.deny = ["web_fetch"]
    try:
        assert (await web.call(FETCH, {"url": "https://example.org/trek"}, thread="t1"))["status"] == "denied"
    finally:
        web.hub.config.agent.permissions.deny = []


@pytest.mark.parametrize("mode", ["auto", "bypass", "accept_edits"])
async def test_every_other_mode_runs_it_without_the_judge(web, mode):
    await search(web)
    r = await web.call(FETCH, {"url": "https://example.org/trek"}, mode=mode, thread="t1")
    assert r["status"] == "done" and "judge" not in r


async def test_a_failed_search_or_one_from_long_ago_counts_for_nothing(web, monkeypatch):
    await search(web, urls=["https://old.example.org/"])
    for _ in range(3):
        await search(web, urls=["https://new.example.org/"])
    monkeypatch.setattr(searched, "RECENT", 2)
    assert (await web.call(FETCH, {"url": "https://old.example.org/"}, thread="t1"))["status"] == "needs_approval"
    assert (await web.call(FETCH, {"url": "https://new.example.org/"}, thread="t1"))["status"] == "done"
    await web.hub.db.execute("UPDATE tool_calls SET state = 'error' WHERE tool = 'web_search'")
    assert (await web.call(FETCH, {"url": "https://new.example.org/"}, thread="t1"))["status"] == "needs_approval"


async def test_it_reads_only_the_database_so_it_holds_across_a_restart(web):
    s = await search(web)
    web.hub.calls.live.clear()                              # nothing in memory: only tool_calls
    assert await searched.found_by(web.hub.db, "https://example.org/trek", "t1") == s["call_id"]
    assert await searched.found_by(web.hub.db, "https://example.org/trek", "t2") is None
    assert await searched.found_by(web.hub.db, "https://example.org/trek", None) is None
