"""21.1: complete tool records: refused calls, filled and edited fields, durations, the tool series,
and dry-run rows pruned after 30 days."""

from __future__ import annotations

import json
import time

from utils.tools import records
from utils.tools.edits import edited


def test_edited_ignores_checkboxes_and_empties_the_user_never_touched():
    schema = {"properties": {"hd": {"type": "boolean"}, "steps": {"type": "integer", "default": 8}, "note": {"type": "string"},
                             "image": {"type": "string"}}}
    model = {"steps": 8, "image": "output:abc"}
    card = {"hd": False, "steps": 8, "note": "", "image": {"$file": "output:abc"}}
    assert edited(schema, model, card) == []
    assert edited(schema, model, {**card, "steps": 20, "hd": True}) == ["hd", "steps"]


async def test_refused_filled_edited_and_duration_are_recorded(th):
    db = th.hub.db
    await th.call("fake_tools_nope", {})
    await th.call("fake_tools_make_image", {"aspect": "16:10"})
    refused = await db.fetchall("SELECT tool, code FROM tool_refusals ORDER BY created_ts")
    assert [(r["tool"], r["code"]) for r in refused] == [("fake_tools_nope", "unknown_tool"), ("fake_tools_make_image", "invalid_arguments")]
    r = await th.call("fake_tools_shape", {"image": "output:000000000000"})
    a = await db.fetchone("SELECT filled FROM approvals WHERE id = ?", (r["approval_id"],))
    assert json.loads(a["filled"]) == {"engine": "default"}
    d = await th.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "arguments": {
        "image": "output:000000000000", "engine": "body"}})
    assert d.status_code == 200, d.text
    ap = (await th.client.get(f"/api/approvals/{r['approval_id']}")).json()
    assert ap["edited"] == ["engine"] and ap["filled"] == {"engine": "default"}
    row = await db.fetchone("SELECT filled, duration_ms, state FROM tool_calls WHERE approval_id = ?", (r["approval_id"],))
    assert row["duration_ms"] is not None and row["filled"] is None   # the user chose the engine (the fake picture makes it fail; it still ends)


async def test_usage_and_the_dry_run_prune(th):
    db = th.hub.db
    await th.call("fake_tools_get_item", {"item_id": "x"})
    await th.call("fake_tools_get_item", {"item_id": "y"}, dry_run=True)
    use = {u["tool"]: u for u in await records.usage(db, time.time() - 60)}
    assert use["fake_tools_get_item"]["calls"] == 1                     # the dry run doesn't count
    await db.execute("UPDATE tool_calls SET created_ts = created_ts - 31 * 86400")
    assert await records.prune_dry_runs(db) == 1
    assert len(await db.fetchall("SELECT id FROM tool_calls")) == 1


def test_tool_events_become_series(th):
    rec = th.hub.metrics
    rec.tool_event({"status": "done", "tool": "fake_tools_get_item", "origin": {}})
    rec.tool_event({"status": "error", "tool": "fake_tools_get_item", "origin": {}})
    rec.tool_event({"status": "done", "tool": "fake_tools_get_item", "origin": {"dry_run": True}})
    rec.tool_event({"status": "running", "tool": "fake_tools_get_item", "origin": {}})
    names = {i.name: v for i, v in rec.samples(int(time.time())) if i.name.startswith("tools.")}
    assert names == {"tools.calls.fake-tools": 2.0, "tools.errors.fake-tools": 1.0}
