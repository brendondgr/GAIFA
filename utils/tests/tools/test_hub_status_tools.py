"""46.2: hub_gpu_status, hub_doctor and hub_free_gpu (and the LLM engines kept unless named)."""

from __future__ import annotations

import asyncio

import pytest

from utils.tools import hub_status_tools
from utils.tests.tools.conftest import _hub_with


@pytest.fixture
async def mh(services_dir, make_app, tools_cfg):
    async for h in _hub_with("fake-mem", services_dir, make_app, tools_cfg):
        yield h


async def loaded(h) -> None:
    await h.client.post("/api/services/fake-mem/load")
    for _ in range(100):
        if (await h.client.get("/api/services/fake-mem")).json()["load"] == "loaded":
            return
        await asyncio.sleep(0.1)
    raise AssertionError("fake-mem never loaded")


async def test_gpu_status_and_doctor(mh):
    g = await mh.call("hub_gpu_status", {})
    assert g["status"] == "done" and set(g["result"]) >= {"queue", "holder", "waiting", "recent"}
    d = await mh.call("hub_doctor", {})
    r = d["result"]
    assert d["status"] == "done" and set(r["counts"]) == {"ok", "note", "warn", "fail"}
    assert all(c["level"] != "ok" for c in r["checks"]) and isinstance(r["passed"], list)


async def test_free_gpu_unloads_what_is_loaded(mh):
    await loaded(mh)
    r = await mh.call("hub_free_gpu", {}, mode="auto")
    assert r["status"] == "done", r
    assert [f["id"] for f in r["result"]["freed"]] == ["fake-mem"] and r["result"]["failed"] == []
    assert (await mh.client.get("/api/services/fake-mem")).json()["load"] == "unloaded"
    again = await mh.call("hub_free_gpu", {"services": ["nope"]}, mode="auto")
    assert again["result"]["freed"] == [] and again["result"]["unknown"] == ["nope"]


async def test_llm_engines_are_kept_unless_named(mh, monkeypatch):
    monkeypatch.setattr(hub_status_tools, "LLM_ENGINES", ("fake-mem",))
    await loaded(mh)
    r = (await mh.call("hub_free_gpu", {}, mode="auto"))["result"]
    assert r["freed"] == [] and r["kept"][0]["id"] == "fake-mem"
    r = (await mh.call("hub_free_gpu", {"services": ["fake-mem"]}, mode="auto"))["result"]
    assert [f["id"] for f in r["freed"]] == ["fake-mem"]
