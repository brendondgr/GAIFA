"""2.9: serving mod pages: /ui/services/<id>/..., /Mod_<id>.dc.html, page_url."""

from __future__ import annotations

import shutil

import httpx
import pytest

from utils.tests.conftest import REPO
from utils.tests.services.conftest import ready


@pytest.fixture
async def hub(rig, serve):
    d = rig.add("fake-ok")
    (d / "ui").mkdir()
    (d / "ui" / "page.js").write_text("export default { tabs: [{ id: 'one', label: 'One' }], mount(el) { el.textContent = 'hi'; } };\n")
    (d / "ui" / "logo.svg").write_text("<svg/>")
    (d / "ui" / ".secret").write_text("no")
    (d / "secret.txt").write_text("outside ui/")
    with open(d / "service.toml", "a") as f:
        f.write('\n[ui]\npage = "ui/page.js"\n')
    p = rig.add("fake-ok", as_id="dcpage")
    (p / "ui").mkdir()
    (p / "ui" / "Page.dc.html").write_text('<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X"></head><body><x-dc>hi</x-dc></body></html>')
    with open(p / "service.toml", "a") as f:
        f.write('\n[ui]\npage = "ui/Page.dc.html"\n')
    shutil.copytree(REPO / "services" / "_template" / "ui", rig.services / "_template" / "ui")
    served = await serve()
    await ready(served, "fake-ok", "dcpage")
    return served


async def test_page_module_is_served_uncached(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/ui/services/fake-ok/page.js?v=123")
        assert r.status_code == 200 and "export default" in r.text
        assert r.headers["content-type"].startswith("text/javascript") and r.headers["cache-control"] == "no-cache"
        assert (await c.get("/ui/services/fake-ok/logo.svg")).status_code == 200
        r = await c.get("/ui/services/_template/page.js")  # the mock Example mod's page
        assert r.status_code == 200 and "Say hello" in r.text


@pytest.mark.parametrize("path", [
    "/ui/services/fake-ok/.secret", "/ui/services/fake-ok/..%2Fsecret.txt", "/ui/services/fake-ok/%2e%2e/secret.txt",
    "/ui/services/fake-ok/nope.js", "/ui/services/Bad_Id/page.js", "/ui/services/nope/page.js", "/ui/services/fake-ok/",
])
async def test_nothing_outside_ui_is_served(hub, path):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get(path)
    assert r.status_code == 404 and r.json()["code"] == "not_found", path


async def test_dc_page_under_mod_name(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/Mod_dcpage.dc.html")
        assert r.status_code == 200 and "<x-dc>hi</x-dc>" in r.text
        assert "fonts.googleapis.com" not in r.text and "/vendor/fonts.css" in r.text
        assert (await c.get("/Mod_fake-ok.dc.html")).status_code == 404  # it has page.js, not Page.dc.html


async def test_page_url_in_summaries(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        items = {s["id"]: s for s in (await c.get("/api/services")).json()}
    assert items["fake-ok"]["has_page"] and items["fake-ok"]["page_url"] == "/ui/services/fake-ok/page.js"
    assert items["dcpage"]["page_url"] == "/Mod_dcpage.dc.html"


async def test_missing_page_file_means_no_page(rig, serve):
    d = rig.add("fake-ok")
    with open(d / "service.toml", "a") as f:
        f.write('\n[ui]\npage = "ui/page.js"\n')
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        s = (await c.get("/api/services/fake-ok")).json()
    assert s["has_page"] is False and s["page_url"] is None


def test_shell_has_no_hard_coded_hello_tab():
    html = (REPO / "web" / "Hub.dc.html").read_text()
    assert "sayHello" not in html and "CUSTOM_TABS" not in html and "sv.t.hello" not in html
    assert '<dc-import name="ModPage"' in html and "modListeners" in html and "case 'resync'" in html
