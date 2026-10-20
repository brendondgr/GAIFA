"""The fetch rules (plan 26.1): every refused address class, also after DNS and on redirects;
the 10 MB and 20 s caps; robots.txt."""

from __future__ import annotations

import pytest

import safety
from conftest import html, slow

REFUSED_URLS = [
    ("ftp://site.test/file", "bad_scheme"),
    ("file:///etc/passwd", "bad_scheme"),
    ("javascript:alert(1)", "bad_scheme"),
    ("http:///nohost", "bad_url"),
    ("http://localhost/", "blocked_address"),
    ("http://printer.local/", "blocked_address"),
    ("http://nas.home.arpa/", "blocked_address"),
    ("http://127.0.0.1/", "blocked_address"),
    ("http://127.1.2.3:8080/", "blocked_address"),
    ("http://10.1.2.3/", "blocked_address"),
    ("http://172.16.0.1/", "blocked_address"),
    ("http://192.168.0.1/", "blocked_address"),
    ("http://100.64.0.1/", "blocked_address"),        # carrier-grade NAT
    ("http://169.254.169.254/latest/meta-data", "blocked_address"),
    ("http://0.0.0.0/", "blocked_address"),
    ("http://[::1]/", "blocked_address"),
    ("http://[fe80::1]/", "blocked_address"),
    ("http://[fd00::1]/", "blocked_address"),
    ("http://[::ffff:127.0.0.1]/", "blocked_address"),
    ("http://224.0.0.1/", "blocked_address"),
]


@pytest.mark.parametrize("url,code", REFUSED_URLS)
def test_refused_by_address(make_client, url, code):
    r = make_client().post("/v1/fetch", json={"url": url})
    assert r.status_code in (403, 422), r.text
    assert r.json()["code"] == code and r.json()["fix"]


@pytest.mark.parametrize("name", ["private.test", "lan.test", "metadata.test", "loop6.test", "mapped.test", "rebind.test"])
def test_refused_after_dns(site, make_client, name):
    """Public-looking names whose addresses are local; `rebind.test` has one public and one loopback address."""
    site.routes["/"] = html("Should not be read", "<p>secret</p>")
    r = make_client().post("/v1/fetch", json={"url": f"http://{name}:{site.port}/"})
    assert r.status_code == 403 and r.json()["code"] == "blocked_address", r.text
    assert "resolves to" in r.json()["detail"]
    assert not [s for s in site.seen if s["path"] == "/"]


@pytest.mark.parametrize("target", ["http://127.0.0.1/admin", "http://127.0.0.1:{port2}/", "http://private.test:{port}/",
                                    "http://[::1]:{port}/", "http://localhost:{port}/", "file:///etc/passwd"])
def test_redirect_to_local_refused(site, make_client, target):
    site.routes["/go"] = (302, {"Location": target.format(port=site.port, port2=site.port + 1)}, b"")
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/go"})
    assert r.status_code in (403, 422) and r.json()["code"] in ("blocked_address", "bad_scheme"), r.text


def test_too_many_redirects(site, make_client):
    site.routes["/loop"] = (302, {"Location": "/loop"}, b"")
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/loop"})
    assert r.status_code == 502 and r.json()["code"] == "too_many_redirects"


def test_size_cap_by_header_and_by_stream(site, make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(safety, "MAX_BYTES", 1000)
    site.routes["/big"] = html("Big", "<p>" + "x" * 2000 + "</p>")

    def chunked(h):
        h.send_response(200)
        h.send_header("Content-Type", "text/html")
        h.send_header("Transfer-Encoding", "chunked")
        h.end_headers()
        for _ in range(5):
            h.wfile.write(b"190\r\n" + b"y" * 400 + b"\r\n")
        h.wfile.write(b"0\r\n\r\n")
    site.routes["/stream"] = chunked
    c = make_client()
    for path in ("/big", "/stream"):
        r = c.post("/v1/fetch", json={"url": f"http://site.test:{site.port}{path}"})
        assert r.status_code == 413 and r.json()["code"] == "too_large", r.text
    assert not list((tmp_path / "outputs").rglob("*.md"))


def test_real_cap_is_10_mb_and_20_s():
    assert safety.MAX_BYTES == 10 * 1024 * 1024 and safety.TIMEOUT_S == 20.0


def test_time_cap(site, make_client, monkeypatch):
    monkeypatch.setattr(safety, "TIMEOUT_S", 0.5)
    site.routes["/slow"] = slow(2.0)
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/slow"})
    assert r.status_code == 504 and r.json()["code"] == "timeout"


def test_robots_disallow_and_allow(site, make_client):
    site.routes["/robots.txt"] = (200, {"Content-Type": "text/plain"},
                                  b"User-agent: *\nDisallow: /private/\n\nUser-agent: AIHub-web\nDisallow: /no-aihub/\n")
    site.routes["/private/page"] = html("Private", "<p>x</p>")
    site.routes["/public/page"] = html("Public", "<p>" + "words " * 40 + "</p>")
    site.routes["/no-aihub/page"] = html("Not for us", "<p>x</p>")
    c = make_client()
    base = f"http://site.test:{site.port}"
    assert c.post("/v1/fetch", json={"url": base + "/public/page"}).status_code == 200
    for path in ("/no-aihub/page",):
        r = c.post("/v1/fetch", json={"url": base + path})
        assert r.status_code == 403 and r.json()["code"] == "robots_disallowed", r.text
    assert not [s for s in site.seen if s["path"] == "/no-aihub/page"]
    assert len([s for s in site.seen if s["path"] == "/robots.txt"]) == 1  # cached per site


def test_robots_star_group_applies_without_own_group(site, make_client):
    site.routes["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /private/\n")
    site.routes["/private/page"] = html("Private", "<p>x</p>")
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/private/page"})
    assert r.status_code == 403 and r.json()["code"] == "robots_disallowed"


def test_robots_on_redirect_target(site, make_client):
    site.routes["site.test/robots.txt"] = (404, {}, b"")
    site.routes["other.test/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /\n")
    site.routes["/hop"] = (302, {"Location": f"http://other.test:{site.port}/page"}, b"")
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/hop"})
    assert r.status_code == 403 and r.json()["code"] == "robots_disallowed"


def test_robots_server_error_means_disallow(site, make_client):
    site.routes["/robots.txt"] = (503, {}, b"down")
    site.routes["/page"] = html("Page", "<p>x</p>")
    r = make_client().post("/v1/fetch", json={"url": f"http://site.test:{site.port}/page"})
    assert r.status_code == 403 and r.json()["code"] == "robots_disallowed"


def test_address_classes():
    assert safety.address_refused("93.184.216.34") is None and safety.address_refused("2606:4700::1111") is None
    for ip, word in [("127.0.0.1", "loopback"), ("::1", "loopback"), ("10.0.0.1", "private"), ("169.254.1.1", "link-local"),
                     ("fe80::1", "link-local"), ("::ffff:10.0.0.1", "private"), ("0.0.0.0", "unspecified")]:
        assert safety.address_refused(ip) == word, ip
    assert safety.address_refused("100.64.0.1")
