"""capability-enablement 1.3: starting a mod that was never set up answers 409 not_set_up before anything is launched;
rescan's autostart and `gaifa start all` skip it; a failed start is recorded for availability."""

from __future__ import annotations

import pytest

from utils import cli
from utils.services.availability import availability
from utils.services.model import ServiceError

from .conftest import until

NOT_SET_UP = {"command": '[".venv/bin/python", "server.py"]'}


async def test_start_refuses_with_the_fix_and_launches_nothing(rig, monkeypatch):
    rig.add("fake-ok", as_id="fresh", edit=NOT_SET_UP)
    mgr = await rig.manager()
    launched = []
    monkeypatch.setattr(mgr.backend, "start", lambda spec: launched.append(spec))
    with pytest.raises(ServiceError) as e:
        await mgr.start("fresh")
    assert (e.value.status, e.value.code) == (409, "not_set_up")
    assert e.value.detail == "Fake OK isn't set up on this machine" and e.value.data["fix"] == "gaifa setup fresh"
    assert launched == [] and mgr.get("fresh").state == "stopped"


async def test_the_route_answers_409_with_the_envelope(rig, serve):
    import httpx

    rig.add("fake-ok", as_id="fresh", edit=NOT_SET_UP)
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.post("/api/services/fresh/start")
        listed = {s["id"]: s for s in (await c.get("/api/services")).json()}
    assert r.status_code == 409 and r.json()["code"] == "not_set_up" and r.json()["data"]["fix"] == "gaifa setup fresh"
    assert listed["fresh"]["availability"]["status"] == "not_set_up" and listed["fresh"]["installed"] is False


async def test_rescan_autostart_skips_it(rig):
    mgr = await rig.manager()
    rig.add("fake-ok", as_id="later", edit=NOT_SET_UP)
    rig.add("fake-ok", as_id="ok")
    await mgr.rescan(autostart=True)
    await until(lambda: mgr.get("ok").state == "ready")
    assert mgr.get("later").state == "stopped" and mgr.get("later").start_failed_at is None


async def test_a_failed_start_is_recorded_and_cleared(rig):
    rig.add("fake-ok", as_id="crashy", edit={"command": '["python3", "-c", "raise SystemExit(1)"]'})   # exits before it answers
    mgr = await rig.manager()
    try:
        await mgr.start("crashy", wait=True)
    except ServiceError:
        pass
    await until(lambda: mgr.get("crashy").state == "failed")
    assert mgr.get("crashy").start_failed_at is not None
    assert availability(mgr, mgr.get("crashy"))["status"] == "failed"
    await mgr.stop("crashy", wait=True)
    assert mgr.get("crashy").start_failed_at is None


def test_start_all_skips_and_says_so(monkeypatch, capsys):
    rows = [{"id": "web", "kind": "process", "manifest_errors": [], "enabled": True, "installed": False, "state": "stopped"},
            {"id": "calendar", "kind": "process", "manifest_errors": [], "enabled": True, "installed": True, "state": "stopped"}]
    calls = []
    monkeypatch.setattr(cli, "unit_installed", lambda: False)
    monkeypatch.setattr(cli, "_no_unit", lambda: False)
    monkeypatch.setattr(cli, "services_or_none", lambda: rows)
    monkeypatch.setattr(cli, "call", lambda m, p, **k: calls.append(p) or {"state": "ready"})
    assert cli._lifecycle("start", "all") == 0
    out = capsys.readouterr().out
    assert "web: not set up, skipped (gaifa setup web)" in out and "calendar: ready" in out
    assert calls == ["/api/services/calendar/start?wait=1"]
