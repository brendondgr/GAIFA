"""capability-enablement 1.2: one answer for "can this mod be used" (`utils/services/availability.py`), in
`GET /api/services` as `installed` and `availability`, with every status from a fake mod."""

from __future__ import annotations

import pytest

from utils.services.availability import availability
from utils.services.views import summary

from .conftest import until

NOT_SET_UP = {"command": '[".venv/bin/python", "server.py"]'}


async def test_each_status(rig, monkeypatch):
    rig.add("fake-ok", as_id="running")
    rig.add("fake-ok", as_id="idle")
    rig.add("fake-ok", as_id="fresh", edit=NOT_SET_UP)
    rig.add("fake-ok", as_id="offmod")
    rig.add("fake-crash", as_id="crashy")
    rig.add("fake-ok", as_id="cuda-only")
    bad = rig.add("fake-ok", as_id="bad")
    (bad / "service.toml").write_text((bad / "service.toml").read_text().replace("health = ", "healthz = "))
    rig.config("[services.offmod]\nenabled = false\n\n[services.cuda-only]\naccel = \"cuda\"\n")
    from utils import hardware
    from .test_variants import machine
    monkeypatch.setattr(hardware, "detect", lambda refresh=False: machine("strix-halo"))
    mgr = await rig.manager()
    await mgr.start("running", wait=True)
    try:
        await mgr.start("crashy", wait=True)
    except Exception:  # noqa: BLE001
        pass
    await until(lambda: mgr.get("crashy").state == "failed")

    def st(sid):
        return availability(mgr, mgr.get(sid))

    assert st("running")["status"] == "on" and st("running")["why"] == ""
    a = st("idle")
    assert a["status"] == "starts_on_use" and a["fix"] == {"kind": "start", "id": "idle", "command": "gaifa start idle", "tool": "hub_start_service"}
    a = st("fresh")
    assert a == {"status": "not_set_up", "why": "Fake OK isn't set up on this machine",
                 "fix": {"kind": "setup", "id": "fresh", "command": "gaifa setup fresh", "tool": ""}}
    a = st("offmod")
    assert a["status"] == "off" and a["why"] == "Fake OK is turned off" and a["fix"]["kind"] == "enable"
    a = st("crashy")
    assert a["status"] == "failed" and a["why"].startswith("Fake Crash didn't start") and a["fix"]["command"] == "gaifa logs crashy"
    a = st("cuda-only")
    assert a["status"] == "cant_run" and "can't run on this machine" in a["why"] and a["fix"]["kind"] == "setup"
    a = st("bad")
    assert a["status"] == "broken" and "service.toml" in a["why"] and a["fix"]["command"] == "gaifa check bad"


async def test_not_set_up_wins_over_off(rig):
    rig.add("fake-ok", as_id="both", edit=NOT_SET_UP)
    rig.config("[services.both]\nenabled = false\n")
    mgr = await rig.manager()
    assert availability(mgr, mgr.get("both"))["status"] == "not_set_up"


async def test_summary_carries_it_and_last_error_says_not_set_up(rig):
    rig.add("fake-ok", as_id="fresh", edit=NOT_SET_UP)
    rig.add("fake-ok", as_id="ok")
    mgr = await rig.manager()
    s = summary(mgr, mgr.get("fresh"))
    assert s["installed"] is False and s["availability"]["status"] == "not_set_up"
    assert s["last_error"] == "not set up: run `gaifa setup fresh`"       # found at discovery, not only at autostart
    s = summary(mgr, mgr.get("ok"))
    assert s["installed"] is True and s["availability"]["status"] == "starts_on_use" and s["last_error"] is None


async def test_found_by_a_rescan_too(rig):
    mgr = await rig.manager()
    rig.add("fake-ok", as_id="later", edit=NOT_SET_UP)
    await mgr.rescan()
    assert mgr.get("later").last_error == "not set up: run `gaifa setup later`"


def test_the_api_model_reads_it():
    from utils.api_models import Availability
    a = Availability.model_validate({"status": "off", "why": "Web is turned off",
                                     "fix": {"kind": "enable", "id": "web", "command": "x", "tool": ""}})
    assert a.fix.kind == "enable"
    with pytest.raises(Exception):
        Availability.model_validate({"status": "gone", "why": "", "fix": {"kind": "none", "id": "x", "command": "", "tool": ""}})
