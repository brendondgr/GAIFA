"""Fetch → markdown → an output with its sidecar; text, JSON and PDF pages; types it refuses (plan 26.1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import html

ARTICLE = ("<h1>Release b6000</h1><p>This release adds a new <a href='https://example.org/kernel'>Vulkan kernel</a> and "
           "makes prompt processing faster on many machines that people use every day.</p><h2>Fixes</h2>"
           "<p>Several crashes with long contexts are fixed, and the server reports its slots more precisely now.</p>"
           "<table><tr><th>Model</th><th>t/s</th></tr><tr><td>7B</td><td>42</td></tr></table>")


def _files(tmp_path: Path) -> list[Path]:
    return sorted(p for p in (tmp_path / "outputs").rglob("*") if p.is_file())


def test_html_becomes_markdown_output(site, make_client, tmp_path):
    site.routes["/robots.txt"] = (404, {}, b"")
    site.routes["/releases/b6000"] = html("llama.cpp b6000 · Releases", ARTICLE)
    url = f"http://site.test:{site.port}/releases/b6000"
    r = make_client().post("/v1/fetch", json={"url": url})
    assert r.status_code == 200, r.text
    body = r.json()
    path = Path(body["path"])
    assert re.fullmatch(r"\d{6}-site-test-release-b6000\.md", path.name), path.name
    assert path.parent.parent == tmp_path / "outputs" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name)
    text = path.read_text()
    assert text.startswith("# Release b6000\n") and f"Source: <{url}>" in text
    assert "[Vulkan kernel](https://example.org/kernel)" in text and "## Fixes" in text and "| 7B | 42 |" in text
    assert "var x" not in text and "© footer" not in text
    assert body["content"] == text and body["truncated"] is False and body["chars"] == len(text)
    assert body["kind"] == "text" and body["final_url"] == url and body["title"] == "Release b6000"
    side = json.loads(path.with_name(path.name + ".json").read_text())
    assert side["url"] == url and side["title"] == body["title"] and side["kind"] == "text"
    assert side["fetched_ts"] > 0 and side["fetched"] and side["source"] == {"service": "web", "url": url}
    assert not [p for p in _files(tmp_path) if p.suffix == ".part"]
    assert all(s["ua"].startswith("AIHub-web/") for s in site.seen)


def test_max_chars_and_names_never_clash(site, make_client):
    site.routes["/a"] = html("Same title", ARTICLE)
    c = make_client()
    url = f"http://site.test:{site.port}/a"
    one = c.post("/v1/fetch", json={"url": url, "max_chars": 100}).json()
    two = c.post("/v1/fetch", json={"url": url, "max_chars": 0}).json()
    assert len(one["content"]) == 100 and one["truncated"] is True and one["chars"] > 100
    assert two["content"] == "" and one["path"] != two["path"]


def test_text_and_json(site, make_client):
    site.routes["/notes.txt"] = (200, {"Content-Type": "text/plain; charset=latin-1"}, "café notes".encode("latin-1"))
    site.routes["/data.json"] = (200, {"Content-Type": "application/json"}, b'{"a": [1, 2]}')
    c = make_client()
    t = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/notes.txt"}).json()
    assert "café notes" in t["content"] and t["title"] == "notes.txt" and t["path"].endswith(".md")
    j = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/data.json"}).json()
    assert '```json\n{\n  "a": [' in j["content"]


def test_pdf_becomes_document(site, make_client):
    pdf = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
    site.routes["/papers/attention-is-all.pdf"] = (200, {"Content-Type": "application/pdf"}, pdf)
    site.routes["/pdf/1706.03762"] = (200, {"Content-Type": "application/octet-stream"}, pdf)  # sniffed by its magic
    c = make_client()
    r = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/papers/attention-is-all.pdf"}).json()
    path = Path(r["path"])
    assert path.suffix == ".pdf" and path.read_bytes() == pdf and r["kind"] == "document" and r["content"] == ""
    assert r["title"] == "attention is all" and "hub_read_document" in r["note"]
    assert json.loads(path.with_name(path.name + ".json").read_text())["kind"] == "document"
    sniffed = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/pdf/1706.03762"}).json()
    assert sniffed["kind"] == "document" and sniffed["title"] == "1706.03762"


def test_unsupported_type_and_http_errors(site, make_client, tmp_path):
    site.routes["/cat.png"] = (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n")
    site.routes["/gone"] = (410, {"Content-Type": "text/plain"}, b"gone")
    c = make_client()
    r = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/cat.png"})
    assert r.status_code == 415 and r.json()["code"] == "unsupported_type" and r.json()["fix"]
    r = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/gone"})
    assert r.status_code == 502 and r.json()["code"] == "http_error" and "410" in r.json()["detail"]
    r = c.post("/v1/fetch", json={"url": f"http://nowhere.test:{site.port}/"})
    assert r.status_code == 502 and r.json()["code"] == "dns_failed"
    assert _files(tmp_path) == []


def test_redirect_followed_to_allowed_page(site, make_client):
    site.routes["/old"] = (301, {"Location": "/new"}, b"")
    site.routes["/new"] = (302, {"Location": f"http://other.test:{site.port}/final"}, b"")
    site.routes["/final"] = html("Final", ARTICLE)
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/old"}).json()
    assert r["final_url"] == f"http://other.test:{site.port}/final" and r["title"] == "Release b6000"
    side = json.loads(Path(r["path"] + ".json").read_text())
    assert side["url"] == f"http://site.test:{site.port}/old" and side["final_url"] == r["final_url"]
