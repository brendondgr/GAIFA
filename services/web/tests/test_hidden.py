"""Saved pages are hidden outputs (plan 30.9): the sidecar says `"hidden": true` for pages, PDFs and dry runs,
and `hide_saved` marks pages saved before that, once."""

from __future__ import annotations

import json
from pathlib import Path

import pages
from conftest import html

DRY = {"X-GAIFA-Origin": '{"tool_call": "c1", "dry_run": true}'}


def _side(r: dict) -> dict:
    return json.loads(Path(r["path"] + ".json").read_text())


def test_every_saved_page_is_hidden(site, make_client):
    site.routes["/robots.txt"] = (404, {}, b"")
    site.routes["/a"] = html("A page", "<h1>A page</h1><p>" + "Words about a thing that matters to someone. " * 8 + "</p>")
    site.routes["/p.pdf"] = (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4\n%%EOF\n")
    c = make_client()
    page = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/a"}).json()
    pdf = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}/p.pdf"}).json()
    dry = c.post("/v1/fetch", json={"url": "https://harbour-council.example/transport/ferry-fares"}, headers=DRY).json()
    assert _side(page)["hidden"] is True and _side(page)["kind"] == "text"
    assert _side(pdf)["hidden"] is True and _side(pdf)["kind"] == "document"
    assert _side(dry)["hidden"] is True and _side(dry)["dry_run"] is True


def test_hide_saved_marks_old_pages_once(tmp_path):
    day = tmp_path / "2026-10-21"
    day.mkdir(parents=True)
    old = day / "102403-tripadvisor-com-things.md.json"
    old.write_text(json.dumps({"title": "Things", "source": {"service": "web", "url": "https://x.example/"}}))
    shown = day / "110000-kept.md.json"            # the user un-hid this one: left alone
    shown.write_text(json.dumps({"title": "Kept", "hidden": False, "source": {"service": "web"}}))
    other = day / "120000-notes.md.json"           # not a page this mod saved
    other.write_text(json.dumps({"title": "Notes"}))
    (day / "130000-broken.md.json").write_text("{not json")
    (tmp_path / "misc").mkdir()
    (tmp_path / "misc" / "x.json").write_text(json.dumps({"source": {"service": "web"}}))   # not a date folder
    assert pages.hide_saved(tmp_path) == 1
    assert json.loads(old.read_text()) == {"title": "Things", "source": {"service": "web", "url": "https://x.example/"}, "hidden": True}
    assert json.loads(shown.read_text())["hidden"] is False and "hidden" not in json.loads(other.read_text())
    assert "hidden" not in json.loads((tmp_path / "misc" / "x.json").read_text())
    assert not [p for p in day.iterdir() if p.name.startswith(".")]
    assert pages.hide_saved(tmp_path) == 0            # once
    assert pages.hide_saved(tmp_path / "missing") == 0
