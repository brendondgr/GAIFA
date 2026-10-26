"""13.1: the tool catalog: manifest tools, a tools_source, metadata defaults, merged schemas,
search, the index, hub tools, a stopped mod's tools, and a tools_source that changes (plan 51.1)."""

from __future__ import annotations

import asyncio
import json

from utils.services import status
from utils.tools.schema import flatten


async def test_catalog_lists_manifest_source_and_hub_tools(th):
    tools = {t["name"]: t for t in (await th.client.get("/api/tools")).json()}
    for name in ("fake_tools_get_item", "fake_tools_make_image", "fake_tools_render", "fake_tools_paint",
                 "fake_tools_styles", "hub_list_services", "hub_search_outputs", "hub_stop_service", "hub_job_status"):
        assert name in tools, name
    get = tools["fake_tools_get_item"]
    assert get["risk"] == "read" and get["mod"] == "fake-tools" and get["source"] == "manifest" and not get["core"]
    assert get["parameters"]["required"] == ["item_id"]
    assert get["parameters"]["properties"]["verbose"]["type"] == "boolean"
    assert get["parameters"]["additionalProperties"] is False
    img = tools["fake_tools_make_image"]
    assert img["risk"] == "generate" and img["ask"] == ["aspect", "steps"]
    props = img["parameters"]["properties"]
    assert props["aspect"]["enum"] == ["1:1", "16:9", "9:16"] and props["steps"]["maximum"] == 50
    assert "title" not in props["prompt"] and props["prompt"]["description"] == "what to draw"
    assert props["reference"]["x-kind"] == "image" and props["reference"].get("nullable")
    assert img["examples"] == [{"prompt": "a red fox", "aspect": "16:9"}]
    assert tools["fake_tools_wipe"]["risk"] == "destructive"
    assert tools["fake_tools_upload_mesh"]["risk"] == "write"
    assert tools["fake_tools_upload_mesh"]["parameters"]["properties"]["mesh"]["x-kind"] == "mesh"
    assert tools["fake_tools_render"]["job"] is True and "Runs as a job" in tools["fake_tools_render"]["description"]
    paint = tools["fake_tools_paint"]
    assert paint["source"] == "tools_source" and paint["risk"] == "generate" and paint["ask"] == ["style"]
    assert paint["parameters"]["properties"]["image"]["x-kind"] == "image" and paint["job"] is True
    assert tools["fake_tools_styles"]["core"] is True and tools["fake_tools_styles"]["risk"] == "read"
    assert tools["fake_tools_styles"]["group"] == "fake-tools:looks" and "group" not in paint      # mcp-client 4.1
    assert tools["hub_stop_service"]["risk"] == "destructive" and tools["hub_list_services"]["core"]


async def test_index_is_small_and_names_and_search_work(th):
    full = (await th.client.get("/api/tools")).text
    index = (await th.client.get("/api/tools/index")).json()
    assert set(index[0]) <= {"name", "mod", "risk", "core", "summary", "available", "why"}
    assert len(json.dumps(index)) < len(full) / 2
    r = await th.client.get("/api/tools?names=fake_tools_render,hub_list_services")
    assert [t["name"] for t in r.json()] == ["fake_tools_render", "hub_list_services"]
    r = await th.client.get("/api/tools?names=fake_tools_rendr")
    assert r.status_code == 404 and r.json()["data"]["close"]["fake_tools_rendr"][0] == "fake_tools_render"
    hits = [t["name"] for t in (await th.client.get("/api/tools?q=make an image")).json()]
    assert hits[0] == "fake_tools_make_image"
    assert (await th.client.get("/api/tools?q=zzqx")).json() == []
    assert len((await th.client.get("/api/tools?q=tools")).json()) <= 8
    # stable between calls
    assert [t["name"] for t in index] == [t["name"] for t in (await th.client.get("/api/tools/index")).json()]


async def test_stopped_mod_keeps_its_tools_listed(th):
    for _ in range(50):   # the on-ready hook reads (and keeps) the tools in the background
        row = await th.hub.db.fetchone("SELECT value FROM kv WHERE key = 'tools:fake-tools'")
        if row:
            break
        await asyncio.sleep(0.05)
    assert row and "fake_tools_paint" in row["value"]
    await th.client.post("/api/services/fake-tools/stop?wait=1")
    tools = {t["name"]: t for t in (await th.client.get("/api/tools/index")).json()}
    assert tools["fake_tools_make_image"]["available"] is False
    assert "a call starts it first" in tools["fake_tools_make_image"]["why"]
    assert "fake_tools_paint" in tools  # the tools_source list was kept from the last run
    # a call starts it
    r = await th.call("fake_tools_get_item", {"item_id": "a"})
    assert r["status"] == "done" and r["result"]["id"] == "a"


def test_flatten_merges_params_and_body_and_reports_clashes():
    op = {"method": "POST", "path": "/v1/x/{id}", "params": [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "integer", "title": "Q"}}],
        "body": {"content_type": "application/json", "schema": {"type": "object", "properties": {
            "id": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]}}}
    s, route, problems = flatten(op)
    assert s["required"] == ["id", "text"] and route.params == {"id": "path", "q": "query"} and route.body == "json"
    assert "title" not in s["properties"]["q"] and problems and "same name" in problems[0]
    s2, r2, _ = flatten({"method": "POST", "path": "/v1/y", "params": [], "body": {"content_type": "application/json",
                                                                              "schema": {"type": "array", "items": {"type": "string"}}}})
    assert r2.body_key == "body" and s2["required"] == ["body"]
    s3, _, _ = flatten({"method": "POST", "path": "/v1/z", "params": [], "body": {"content_type": "application/json", "schema": {"type": "object"}}})
    assert "additionalProperties" not in s3


async def test_hidden_and_fixed_parameters(th):
    tools = {t["name"]: t for t in (await th.client.get("/api/tools?names=fake_tools_get_item_quiet,fake_tools_make_image_simple")).json()}
    assert "verbose" not in tools["fake_tools_get_item_quiet"]["parameters"]["properties"]
    assert set(tools["fake_tools_make_image_simple"]["parameters"]["properties"]) == {"prompt", "aspect"}
    r = await th.call("fake_tools_get_item_quiet", {"item_id": "z"})
    assert r["result"] == {"id": "z", "verbose": "true"}
    r = await th.call("fake_tools_get_item_quiet", {"item_id": "z", "verbose": False})
    assert r["status"] == "error" and r["error"]["code"] == "invalid_arguments"


async def test_a_tools_source_list_follows_the_mods_tools_rev(th):
    """51.1: a tool the mod adds while it runs appears once its status reports a new tools_rev, not before."""
    mgr = th.hub.services
    svc = mgr.get("fake-tools")

    async def poll() -> None:                   # one round of the status poller
        st, problems = await status.fetch(mgr, svc)
        assert st is not None and not problems, problems
        status.apply(mgr, svc, st)

    async def names() -> set[str]:
        return {t["name"] for t in (await th.client.get("/api/tools/index")).json()}

    await poll()
    assert svc.tools_rev == "1" and "fake_tools_doodle" not in await names()
    assert (await th.client.post("/api/s/fake-tools/v1/tools/doodle")).status_code == 200
    assert "fake_tools_doodle" not in await names()     # the same revision: the cached list stays
    await poll()
    assert svc.tools_rev == "2" and "fake_tools_doodle" in await names()
    row = await th.hub.db.fetchone("SELECT value FROM kv WHERE key = 'tools:fake-tools'")
    assert "fake_tools_doodle" in row["value"]          # kept for when the mod stops
    r = await th.call("fake_tools_doodle", {})
    assert r["status"] == "done", r
