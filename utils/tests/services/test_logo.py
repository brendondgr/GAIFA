"""33.1: a mod's logo: `[ui] logo`, else `ui/logo.svg`; `logo_url` in summaries; one per installed mod."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from utils.manifest import discover
from utils.tests.conftest import REPO
from utils.tests.services.conftest import ready
from utils.tests.services.test_manifest import write

BASE = 'id = "{id}"\n[run]\ncommand = ["a"]\nport = 5100\n'


@pytest.fixture
async def hub(rig, serve):
    d = rig.add("fake-ok")  # ui/logo.svg, found without [ui] logo
    (d / "ui").mkdir()
    (d / "ui" / "logo.svg").write_text("<svg/>")
    p = rig.add("fake-ok", as_id="named")  # [ui] logo names a PNG
    (p / "ui" / "img").mkdir(parents=True)
    (p / "ui" / "img" / "mark.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with open(p / "service.toml", "a") as f:
        f.write('\n[ui]\nlogo = "ui/img/mark.png"\n')
    rig.add("fake-ok", as_id="plain")  # no logo at all
    g = rig.add("fake-ok", as_id="gone")  # names a file that isn't there
    with open(g / "service.toml", "a") as f:
        f.write('\n[ui]\nlogo = "ui/nope.svg"\n')
    served = await serve()
    await ready(served, "fake-ok", "named", "plain", "gone")
    return served


async def test_logo_url_in_summaries_and_served(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        items = {s["id"]: s for s in (await c.get("/api/services")).json()}
        assert items["fake-ok"]["logo_url"] == "/ui/services/fake-ok/logo.svg"
        assert items["named"]["logo_url"] == "/ui/services/named/img/mark.png"
        assert items["plain"]["logo_url"] is None and items["gone"]["logo_url"] is None
        for sid in ("fake-ok", "named"):
            assert (await c.get(items[sid]["logo_url"])).status_code == 200
        assert (await c.get("/api/services/named")).json()["logo_url"] == "/ui/services/named/img/mark.png"


@pytest.mark.parametrize("logo, expect", [
    ("../logo.svg", "inside the mod's ui/ folder"),
    ("logo.svg", "inside the mod's ui/ folder"),
    ("/tmp/logo.svg", "inside the mod's ui/ folder"),
    ("ui", "inside the mod's ui/ folder"),
    ("ui/logo.gif", ".svg, .png or .webp"),
])
def test_bad_logo_is_a_manifest_error(tmp_path, logo, expect):
    write(tmp_path, "bad", BASE.format(id="bad") + f'[ui]\nlogo = "{logo}"\n')
    [mod] = discover([tmp_path])
    assert not mod.ok and expect in "\n".join(mod.errors), mod.errors


def test_every_mod_has_its_own_logo():
    mods = sorted(d for d in (REPO / "services").iterdir() if (d / "service.toml").is_file() and d.name != "_template")
    assert mods
    missing = [d.name for d in mods if not (d / "ui" / "logo.svg").is_file()]
    assert not missing, f"no ui/logo.svg: {missing}"
    digests = {}
    for d in mods:
        text = (d / "ui" / "logo.svg").read_bytes()
        assert text.lstrip().startswith(b"<svg") and b"<script" not in text, d.name
        digests.setdefault(hashlib.sha256(text).hexdigest(), []).append(d.name)
    assert all(len(v) == 1 for v in digests.values()), [v for v in digests.values() if len(v) > 1]
    assert not (REPO / "services" / "_template" / "ui" / "logo.svg").exists()  # new mods get the UI's monogram
