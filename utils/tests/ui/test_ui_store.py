"""settings-that-stick 4.1: GET/PATCH /api/ui/store/{scope}: what a page remembers, per mod or `hub`, in
data/state/ui/<scope>.json; keys merge, limits hold, an unknown mod is refused, a change is published."""

from __future__ import annotations

import asyncio
import json

import httpx

from utils.tests.settings.test_settings import _hub
from utils.ui_store import UiStore


async def test_get_set_delete(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        assert (await c.get("/api/ui/store/fake-ok")).json() == {"values": {}}
        r = await c.patch("/api/ui/store/fake-ok", json={"set": {"voice": "af_heart", "speak": {"speed": 1.2}}})
        assert r.status_code == 200 and r.json()["values"] == {"voice": "af_heart", "speak": {"speed": 1.2}}
        f = served.hub.paths.state / "ui" / "fake-ok.json"
        assert json.loads(f.read_text()) == {"speak": {"speed": 1.2}, "voice": "af_heart"}
        r = await c.patch("/api/ui/store/fake-ok", json={"delete": ["voice"]})
        assert r.json()["values"] == {"speak": {"speed": 1.2}}
        assert (await c.patch("/api/ui/store/hub", json={"set": {"chat.layout": {"root": 1}}})).status_code == 200
        assert (await c.get("/api/ui/store/hub")).json()["values"] == {"chat.layout": {"root": 1}}


async def test_two_pages_keep_each_others_keys(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        await asyncio.gather(c.patch("/api/ui/store/hub", json={"set": {"a": 1}}), c.patch("/api/ui/store/hub", json={"set": {"b": 2}}))
        assert (await c.get("/api/ui/store/hub")).json()["values"] == {"a": 1, "b": 2}


async def test_refusals(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.get("/api/ui/store/nope")
        assert r.status_code == 404 and r.json()["code"] == "not_found"
        r = await c.patch("/api/ui/store/hub", json={"set": {"big": "x" * 17000}})
        assert r.status_code == 413 and r.json()["code"] == "payload_too_large"
        r = await c.patch("/api/ui/store/hub", json={"set": {"": 1}})
        assert r.status_code == 422
        r = await c.patch("/api/ui/store/hub", json={"put": {}})
        assert r.status_code == 422
        assert (await c.get("/api/ui/store/hub")).json()["values"] == {}


async def test_a_change_is_published(rig, serve):
    served = await _hub(rig, serve)
    sub = served.hub.bus.subscribe()
    async with httpx.AsyncClient(base_url=served.url) as c:
        await c.patch("/api/ui/store/hub", json={"set": {"a": 1}})
        await c.patch("/api/ui/store/hub", json={"set": {"a": 1}})     # unchanged: nothing
    evs = []
    while not sub.queue.empty():
        ev = sub.queue.get_nowait()
        if ev.get("type") == "ui_store":
            evs.append(ev)
    sub.close()
    assert evs == [{"type": "ui_store", "scope": "hub", "keys": ["a"]}]


def test_the_file_limit(tmp_path):
    st = UiStore(tmp_path)
    for i in range(16):         # 16 × 16 000 bytes fit in 256 KB; a 17th doesn’t
        st.change("hub", {f"k{i}": "x" * 16000})
    try:
        st.change("hub", {"k99": "x" * 16000})
    except ValueError as e:
        assert "256 KB" in str(e)
    else:
        raise AssertionError("the file limit")
    assert len(st.get("hub")) == 16
