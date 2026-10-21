"""`GET /v1/favicon?host=`: a site's icon under the fetch rules, cached, served as an image with nosniff (Chat's Sources)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

import favicons
import server
from conftest import make_guard

ICO = b"\x00\x00\x01\x00\x01\x00\x10\x10" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def icons(site, tmp_path):
    """A web mod whose sites are the test server (`http://<host>:<port>`), its icon cache in tmp_path/icons."""
    app = server.create_app(f"http://127.0.0.1:{site.port}", tmp_path / "outputs", make_guard(site.port),
                            icons_dir=tmp_path / "icons", icon_origin=lambda h: f"http://{h}:{site.port}")
    with TestClient(app) as c:
        c.dir = tmp_path / "icons"
        yield c


def hits(site, path: str) -> int:
    return sum(1 for s in site.seen if s["path"] == path)


def test_serves_favicon_ico_and_caches_it(site, icons):
    site.routes["/favicon.ico"] = (200, {"Content-Type": "image/vnd.microsoft.icon"}, ICO)
    r = icons.get("/v1/favicon", params={"host": "Site.Test."})
    assert r.status_code == 200 and r.content == ICO
    assert r.headers["content-type"] == "image/x-icon" and r.headers["x-content-type-options"] == "nosniff"
    assert "max-age=" in r.headers["cache-control"] and "sandbox" in r.headers["content-security-policy"]
    assert (icons.dir / "site.test.ico").read_bytes() == ICO
    again = icons.get("/v1/favicon", params={"host": "site.test"})
    assert again.status_code == 200 and again.content == ICO and hits(site, "/favicon.ico") == 1


def test_type_comes_from_the_bytes(site, icons):
    site.routes["/favicon.ico"] = (200, {"Content-Type": "application/octet-stream"}, PNG)
    r = icons.get("/v1/favicon", params={"host": "site.test"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_falls_back_to_the_pages_link_icon_skipping_svg(site, icons):
    site.routes["/robots.txt"] = (404, {}, b"")
    site.routes["/"] = (200, {"Content-Type": "text/html"}, b'<html><head><link rel="icon" type="image/svg+xml" href="/i.svg">'
                        b'<link rel="shortcut icon" sizes="32x32" href="/static/i.png"></head><body>hi</body></html>')
    site.routes["/i.svg"] = (200, {"Content-Type": "image/svg+xml"}, SVG)
    site.routes["/static/i.png"] = (200, {"Content-Type": "image/png"}, PNG)
    r = icons.get("/v1/favicon", params={"host": "site.test"})
    assert r.status_code == 200 and r.content == PNG and hits(site, "/i.svg") == 0


def test_robots_disallowing_the_home_page_means_no_fallback(site, icons):
    site.routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /\n")
    site.routes["/"] = (200, {"Content-Type": "text/html"}, b'<link rel="icon" href="/static/i.png">')
    site.routes["/static/i.png"] = (200, {"Content-Type": "image/png"}, PNG)
    assert icons.get("/v1/favicon", params={"host": "site.test"}).status_code == 404 and hits(site, "/") == 0


@pytest.mark.parametrize("route", [
    (200, {"Content-Type": "image/svg+xml"}, SVG),                                  # SVG is never served
    (200, {"Content-Type": "image/png"}, SVG),                                      # … whatever it claims
    (200, {"Content-Type": "text/html"}, PNG),                                      # not an image type
    (200, {"Content-Type": "image/png"}, b"GIF-ish but not really"),               # bytes of no known image
    (200, {"Content-Type": "image/png"}, PNG + b"\x00" * (101 * 1024)),             # over 100 KB
    (404, {"Content-Type": "text/plain"}, b"no"),
])
def test_refuses_what_isnt_a_small_raster_icon(site, icons, route):
    site.routes["/favicon.ico"] = route
    site.routes["/robots.txt"] = (404, {}, b"")
    site.routes["/"] = (200, {"Content-Type": "text/html"}, b"<html><head></head></html>")
    r = icons.get("/v1/favicon", params={"host": "site.test"})
    assert r.status_code == 404 and r.json()["code"] == "no_favicon" and "max-age" in r.headers["cache-control"]
    assert (icons.dir / "site.test.miss").exists()
    n = len(site.seen)
    assert icons.get("/v1/favicon", params={"host": "site.test"}).status_code == 404 and len(site.seen) == n   # the miss is cached


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "printer.local", "nas.lan", "a b.com", "-x.com", "x", "[::1]", "x.123"])
def test_refuses_names_that_arent_public_hosts(icons, host):
    r = icons.get("/v1/favicon", params={"host": host})
    assert r.status_code == 422 and r.json()["code"] == "bad_host"


def test_never_connects_to_private_addresses(site, icons):
    for host in ("private.test", "lan.test", "metadata.test", "rebind.test"):
        assert icons.get("/v1/favicon", params={"host": host}).status_code == 404
    assert site.seen == []


def test_a_redirect_to_a_private_address_is_refused(site, icons):
    site.routes["/favicon.ico"] = (302, {"Location": f"http://lan.test:{site.port}/x.ico"}, b"")
    site.routes["/robots.txt"] = (404, {}, b"")
    site.routes["/"] = (200, {"Content-Type": "text/html"}, b"<html></html>")
    assert icons.get("/v1/favicon", params={"host": "site.test"}).status_code == 404
    assert not [s for s in site.seen if s["host"] == "lan.test"]


def test_cache_expires_and_stays_bounded(tmp_path, monkeypatch):
    f = favicons.Favicons(tmp_path, lambda: None, None)  # type: ignore[arg-type]
    old = time.time() - favicons.HIT_TTL_S - 10
    f._store("old.example", (PNG, "png"))
    os.utime(tmp_path / "old.example.png", (old, old))
    assert f._cached("old.example") is False                      # expired: looked up again
    monkeypatch.setattr(favicons, "MAX_FILES", 3)
    for i in range(5):
        f._store(f"h{i}.example", (PNG, "png"))
        os.utime(tmp_path / f"h{i}.example.png", (time.time() - 100 + i, time.time() - 100 + i))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 3 and "h4.example.png" in names and "old.example.png" not in names
    f._store("h4.example", None)                                    # a miss replaces the hit
    assert f._cached("h4.example") is None and not (tmp_path / "h4.example.png").exists()


def test_icon_links_prefers_raster_near_32px():
    html = ('<link rel="apple-touch-icon" href="/apple.png"><link rel="icon" href="/big.png" sizes="192x192">'
            '<link rel="icon" href="data:image/png;base64,AAAA"><link rel="icon" href="/a.svg"><link rel="icon" href="/s.png" sizes="32x32">'
            '<link rel="icon" href="javascript:alert(1)">')
    assert favicons.icon_links(html, "https://ex.org/p/") == ["https://ex.org/s.png", "https://ex.org/apple.png", "https://ex.org/big.png"]
