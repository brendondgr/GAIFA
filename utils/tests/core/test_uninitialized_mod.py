"""A submodule that isn't checked out (plan mod-repos 2.3): its folder is empty, the hub skips it and
tests that read its files say how to get it."""

from __future__ import annotations

import shutil

import httpx

from utils.manifest import discover
from utils.tests.conftest import FAKE_MODS, needs_mods


def test_an_empty_mod_folder_is_skipped_not_broken(tmp_path):
    services = tmp_path / "services"
    shutil.copytree(FAKE_MODS / "fake-ok", services / "fake-ok")
    (services / "relay").mkdir()                       # `git clone` without --recurse-submodules leaves this
    mods = discover([services])
    assert [m.id for m in mods] == ["fake-ok"] and not mods[0].errors


async def test_the_hub_lists_only_checked_out_mods(make_app, root):
    shutil.copytree(FAKE_MODS / "fake-ok", root / "services" / "fake-ok")
    (root / "services" / "gen3d").mkdir()
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as client:
            ids = [s["id"] for s in (await client.get("/api/services")).json()]
            alerts = (await client.get("/api/overview")).json()["alerts"]
    assert "gen3d" not in ids and "fake-ok" in ids
    assert not [a for a in alerts if "gen3d" in str(a)]


def test_needs_mods_skips_with_the_command():
    mark = needs_mods("agent", "no-such-mod")
    assert mark.args[0] is True
    assert mark.kwargs["reason"] == "services/no-such-mod isn't checked out: git submodule update --init services/no-such-mod"
    assert needs_mods("agent").args[0] is False
