"""2.10: the mod self-test (`aihub check`)."""

from __future__ import annotations

import httpx
import pytest

from utils.services.check import page_check, widget_problems
from utils.tests.services.conftest import ready


def statuses(report: dict) -> dict[str, str]:
    return {c["name"]: c["status"] for c in report["checks"]}


async def check(served, sid: str, start: bool = False) -> dict:
    async with httpx.AsyncClient(base_url=served.url, timeout=60) as c:
        r = await c.get(f"/api/services/{sid}/check" + ("?start=1" if start else ""))
    assert r.status_code == 200, r.text
    return r.json()


async def test_fake_ok_passes(rig, serve):
    rig.add("fake-ok")
    served = await serve()
    await ready(served, "fake-ok")
    r = await check(served, "fake-ok")
    assert r["ok"] is True
    assert statuses(r) == {"manifest": "ok", "command": "ok", "state": "ok", "port": "ok", "health": "ok", "openapi": "ok", "status": "ok"}
    assert all(c["ok"] for c in r["checks"])


async def test_bad_manifest_stops_at_the_manifest(rig, serve):
    d = rig.add("fake-ok", as_id="bad")
    (d / "service.toml").write_text('id = "bad"\n[run]\nport = 5150\nhelth = "/x"\n')
    served = await serve()
    r = await check(served, "bad")
    assert r["ok"] is False
    assert [c["name"] for c in r["checks"]] == ["manifest", "manifest"]
    assert {c["detail"] for c in r["checks"]} == {"service.toml: [run].helth: unknown key (check the spelling against architecture §4.3)", 'service.toml: [run].command is required (or set kind = "external")'}


async def test_failing_health(rig, serve):
    rig.add("fake-ok", edit={"health": '"/nope"', "start_timeout_s": "1"})
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        await c.post("/api/services/fake-ok/start?wait=1")
    r = await check(served, "fake-ok")
    st = statuses(r)
    assert r["ok"] is False and st["state"] == "fail"
    assert "not healthy after 1s (/nope HTTP 404)" in next(c["detail"] for c in r["checks"] if c["name"] == "state")


async def test_wrong_status_shape(rig, serve):
    rig.add("fake-ok")
    rig.config('[services.fake-ok]\nenv = { FAKE_BAD_STATUS = "1" }')
    served = await serve()
    await ready(served, "fake-ok")
    r = await check(served, "fake-ok")
    status = next(c for c in r["checks"] if c["name"] == "status")
    assert r["ok"] is False and status["status"] == "fail"
    assert "loaded must be true, false or null" in status["detail"] and "jobs must be a list" in status["detail"]


async def test_stopped_mod_skips_live_checks_and_can_start(rig, serve):
    rig.add("fake-ok")
    rig.config("[services.fake-ok]\nautostart = false")
    served = await serve()
    r = await check(served, "fake-ok")
    st = statuses(r)
    assert r["ok"] is True and st["state"] == "skip" and st["health"] == "skip" and st["openapi"] == "skip" and st["port"] == "ok"
    r = await check(served, "fake-ok", start=True)
    assert statuses(r)["health"] == "ok" and served.services.get("fake-ok").state == "ready"


async def test_missing_executable_and_referenced_operations(rig, serve):
    d = rig.add("fake-ok", edit={"command": '[".venv/bin/python", "server.py"]', "install": '"install.sh"'})
    served = await serve()
    r = await check(served, "fake-ok")
    cmd = next(c for c in r["checks"] if c["name"] == "command")
    assert cmd["status"] == "fail" and cmd["detail"].endswith(".venv/bin/python not found (run `aihub install fake-ok`?)")


async def test_operations_must_exist(rig, serve):
    d = rig.add("fake-ok")
    with open(d / "service.toml", "a") as f:
        f.write('\n[memory]\nload = "POST /v1/load"\nunload = "POST /v1/unload"\n\n[tools]\nshout = { op = "POST /v1/shout" }\necho = { op = "POST /v1/echo" }\n')
    served = await serve()
    await ready(served, "fake-ok")
    r = await check(served, "fake-ok")
    ops = next(c for c in r["checks"] if c["name"] == "operations")
    assert ops["status"] == "fail"
    assert ops["detail"] == "not in the OpenAPI: [memory].load: POST /v1/load; [memory].unload: POST /v1/unload; [tools].shout: POST /v1/shout"


async def test_port_taken_by_someone_else(rig, serve):
    import socket

    rig.add("fake-ok")
    rig.config("[services.fake-ok]\nautostart = false")
    served = await serve()
    with socket.socket() as s:
        s.bind(("127.0.0.1", rig.ports["fake-ok"]))
        s.listen()
        r = await check(served, "fake-ok")
    port = next(c for c in r["checks"] if c["name"] == "port")
    assert port["status"] == "fail" and "is in use by" in port["detail"]


def test_widget_shapes():
    good = {"unit": "calls", "t": [1, 2, 3], "series": [{"name": "Calls", "values": [1, None, 2]}]}
    assert widget_problems(good, "bar") == []
    assert widget_problems({"categories": ["a"], "series": [{"name": "x", "values": [1]}]}, "donut") == []
    assert widget_problems({"rows": [{"a": 1}]}, "table") == []
    assert widget_problems([1], "bar") == ["WidgetData must be a JSON object"]
    assert widget_problems({"series": []}, "line") == ["series must be a non-empty list of {name, values}"]
    assert widget_problems({"series": [{"name": "x", "values": [1]}]}, "line") == ["a line widget needs t (unix seconds) or categories"]
    assert widget_problems({"t": [1, 2], "series": [{"name": "x", "values": [1]}, {"values": [1, 2]}, {"name": "y", "values": ["a", 2]}]}, "area") == [
        "series[0] (x): 1 values for 2 points", "series[1] needs a name", "series[2] (y): values must be numbers or null"]
    assert widget_problems({"rows": "x"}, "table") == ["a table widget needs rows: [{column: value}, …]"]
    assert widget_problems({"series": [{"name": "n", "values": [5]}]}, "number") == []


def test_page_checks(tmp_path):
    p = tmp_path / "page.js"
    assert page_check(p) == ("fail", "page.js is declared in [ui] page but doesn't exist")
    p.write_text("export default { tabs: [{id: 'a'}], mount(el, ctx) {} }")
    assert page_check(p) == ("ok", "page.js exports tabs and mount")
    p.write_text("export default { mount(el, ctx) { fetch('/x'); } }")
    assert page_check(p)[0] == "warn" and "calls fetch()" in page_check(p)[1]
    p.write_text("const x = 1;")
    assert page_check(p)[0] == "fail"
    d = tmp_path / "Page.dc.html"
    d.write_text("<html><x-dc>hi</x-dc></html>")
    assert page_check(d) == ("ok", "Page.dc.html component")
