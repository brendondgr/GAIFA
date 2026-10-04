import re
from pathlib import Path

import httpx
import pytest

from utils.routes.web import HEAD_SCRIPTS, local_fonts, page_html
from utils.server import HubError

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "web"
EXPORT = ["Hub.dc.html", "OutputCard.dc.html", "JsonView.dc.html", "mock.js", "support.js"]


@pytest.fixture
async def web_client(make_app, root):
    (root / "web").symlink_to(WEB)
    app = make_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            yield c


def test_page_html_adds_scripts_before_support_and_local_fonts():
    src = (
        '<head><script src="./support.js"></script></head><body><x-dc><helmet>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous">\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans&amp;display=swap">'
        "</helmet></x-dc></body>"
    )
    out = page_html(src)
    assert out.index("react.production.min.js") < out.index("react-dom") < out.index("/config.js") < out.index("support.js")
    assert "fonts.g" not in out and '<link rel="stylesheet" href="/vendor/fonts.css">' in out


def test_page_without_support_js_is_an_error():
    with pytest.raises(HubError):
        page_html("<html></html>")


def test_export_files_are_present_and_support_js_untouched():
    for name in EXPORT:
        assert (WEB / name).is_file()
    assert (WEB / "support.js").read_bytes() == (REPO / "docs/reference/ui-export-2026-10-04/support.js").read_bytes()
    for name in ("react.production.min.js", "react-dom.production.min.js", "fonts.css"):
        assert (WEB / "vendor" / name).is_file()
    for font in re.findall(r"url\((fonts/[^)]+)\)", (WEB / "vendor/fonts.css").read_text()):
        assert (WEB / "vendor" / font).is_file()


def test_renamed_to_aihub():
    for name in ("Hub.dc.html", "mock.js"):
        text = (WEB / name).read_text()
        assert not re.search(r"\bHub\b", text) and "bin/hub" not in text


async def test_index_serves_the_export(web_client):
    r = await web_client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert HEAD_SCRIPTS in r.text and "fonts.googleapis" not in r.text
    assert "AIHub not responding" in r.text


async def test_no_external_urls_in_what_the_page_loads(web_client):
    html = (await web_client.get("/")).text
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not url.startswith(("http:", "https:", "//")), url
    for path in ("/vendor/react.production.min.js", "/vendor/react-dom.production.min.js", "/vendor/fonts.css",
                 "/vendor/fonts/ibm-plex-sans-latin-400-normal.woff2", "/mock.js", "/support.js", "/config.js"):
        assert (await web_client.get(path)).status_code == 200, path


async def test_components_get_local_fonts_but_no_scripts(web_client):
    r = await web_client.get("/OutputCard.dc.html")
    assert r.status_code == 200 and "/config.js" not in r.text
    assert r.text == local_fonts((WEB / "OutputCard.dc.html").read_text())
    assert (await web_client.get("/Nope.dc.html")).json()["code"] == "not_found"


async def test_index_without_web_is_404(client):
    r = await client.get("/")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_web_files_are_revalidated(web_client):
    for path in ("/api.js", "/mock.js", "/mod-ui.js", "/support.js", "/vendor/fonts.css"):
        r = await web_client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
        assert "etag" in r.headers
        again = await web_client.get(path, headers={"if-none-match": r.headers["etag"]})
        assert again.status_code == 304, path
