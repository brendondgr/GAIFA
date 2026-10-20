"""Search against a fake SearXNG (plan 26.1), and the status that says whether SearXNG answers."""

from __future__ import annotations

import socket

from conftest import searx

RESULTS = [
    {"url": "https://github.com/ggml-org/llama.cpp/releases", "title": "Releases · llama.cpp", "content": "b6000 adds …",
     "engine": "bing", "publishedDate": "2026-10-18T00:00:00"},
    {"url": "https://github.com/ggml-org/llama.cpp/releases", "title": "duplicate", "content": "", "engine": "google"},
    {"url": "https://news.example.org/llama", "title": "llama.cpp news", "content": "x" * 900, "engines": ["google", "bing"]},
    {"url": "https://third.example.org/", "title": "", "content": "third"},
]


def test_search_maps_results(site, make_client):
    site.routes["/search"] = searx(RESULTS, answers=["an answer"], suggestions=["llama.cpp changelog"],
                                   unresponsive_engines=[["brave", "too many requests"]])
    r = make_client().post("/v1/search", json={"query": "llama.cpp release", "time_range": "week",
                                                "categories": ["it", "news"], "language": "en", "limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["url"] for x in body["results"]] == ["https://github.com/ggml-org/llama.cpp/releases",
                                                    "https://news.example.org/llama", "https://third.example.org/"]
    first, second, third = body["results"]
    assert first == {"title": "Releases · llama.cpp", "url": RESULTS[0]["url"], "snippet": "b6000 adds …",
                     "engine": "bing", "published": "2026-10-18T00:00:00"}
    assert second["engine"] == "google,bing" and len(second["snippet"]) == 500 and second["published"] is None
    assert third["title"] == "https://third.example.org/"
    assert body["answers"] == ["an answer"] and body["suggestions"] == ["llama.cpp changelog"]
    assert body["unresponsive"] == ["brave"]
    q = [s for s in site.seen if s["path"] == "/search"][0]["query"]
    assert q == {"q": ["llama.cpp release"], "format": ["json"], "pageno": ["1"], "categories": ["it,news"],
                 "time_range": ["week"], "language": ["en"]}


def test_search_limit_and_validation(site, make_client):
    site.routes["/search"] = searx([{"url": f"https://e.org/{i}", "title": str(i), "content": ""} for i in range(30)])
    c = make_client()
    assert len(c.post("/v1/search", json={"query": "x"}).json()["results"]) == 8
    assert len(c.post("/v1/search", json={"query": "x", "limit": 20}).json()["results"]) == 20
    assert c.post("/v1/search", json={"query": "x", "limit": 21}).status_code == 422
    assert c.post("/v1/search", json={"query": ""}).status_code == 422
    assert c.post("/v1/search", json={"query": "x", "time_range": "decade"}).status_code == 422


def test_search_json_disabled(site, make_client):
    site.routes["/search"] = (403, {"Content-Type": "text/html"}, b"Forbidden")
    r = make_client().post("/v1/search", json={"query": "x"})
    assert r.status_code == 502
    assert r.json()["code"] == "searxng_no_json" and "search.formats" in r.json()["fix"]


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_searxng_down(make_client):
    c = make_client(f"http://127.0.0.1:{_closed_port()}")
    r = c.post("/v1/search", json={"query": "x"})
    assert r.status_code == 503 and r.json()["code"] == "searxng_down" and r.json()["fix"]
    st = c.get("/v1/status").json()
    assert st["stats"][0]["label"] == "SearXNG" and st["stats"][0]["value"] == "down"
    assert st["searxng"]["up"] is False
    assert c.get("/health").status_code == 200  # the server is up even when SearXNG isn't


def test_status_up_and_counts(site, make_client):
    site.routes["/healthz"] = (200, {"Content-Type": "text/plain"}, b"OK")
    site.routes["/search"] = searx(RESULTS[:1])
    c = make_client()
    c.post("/v1/search", json={"query": "x"})
    st = c.get("/v1/status").json()
    assert {s["label"]: s["value"] for s in st["stats"]} == {"SearXNG": "up", "Searches": 1, "Pages fetched": 0, "Refused": 0}
    assert st["loaded"] is None and st["busy"] is False and st["jobs"] == []
