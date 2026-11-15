"""capability-enablement 1.6: the web mod's status says `search` is off (tools_off) while no SearXNG answers or it refuses
JSON, and on again once it does; fetch is never marked off. searxng_failed no longer asks for a retry with another query."""

from __future__ import annotations

import socket

from conftest import searx


def dead_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_search_on_while_searxng_answers(site, make_client):
    site.routes["/healthz"] = (200, {"Content-Type": "text/plain"}, b"OK")
    st = make_client().get("/v1/status").json()
    assert st["tools_off"] == {}


def test_search_off_without_searxng(make_client):
    port = dead_port()
    st = make_client(f"http://127.0.0.1:{port}").get("/v1/status").json()
    off = st["tools_off"]
    assert set(off) == {"search"} and off["search"]["why"] == f"no SearXNG answers at http://127.0.0.1:{port}"
    assert "gaifa setup searxng" in off["search"]["fix"] and "web_fetch still reads pages" in off["search"]["fix"]


def test_search_off_while_json_is_refused_then_on(site, make_client):
    site.routes["/healthz"] = (200, {"Content-Type": "text/plain"}, b"OK")
    site.routes["/search"] = (403, {"Content-Type": "text/plain"}, b"Forbidden")
    c = make_client()
    assert c.post("/v1/search", json={"query": "x"}).json()["code"] == "searxng_no_json"
    off = c.get("/v1/status").json()["tools_off"]
    assert "refuses JSON" in off["search"]["why"] and "search.formats" in off["search"]["fix"]
    site.routes["/search"] = searx([{"url": "https://e.org/", "title": "e", "content": ""}])
    assert c.post("/v1/search", json={"query": "x"}).status_code == 200
    assert c.get("/v1/status").json()["tools_off"] == {}


def test_a_failed_search_says_try_once_more(site, make_client):
    site.routes["/healthz"] = (200, {"Content-Type": "text/plain"}, b"OK")
    site.routes["/search"] = (200, {"Content-Type": "application/json"}, b"[1, 2]")
    r = make_client().post("/v1/search", json={"query": "x"}).json()
    assert r["code"] == "searxng_failed" and "try once more" in r["fix"] and "different query" not in r["fix"]
