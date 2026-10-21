"""Hidden outputs (plan 30.9): the sidecar's `"hidden": true` (the web mod's saved pages) keeps an output out of
the lists people see (`GET /api/outputs` and its totals, the Overview, the agent's output search, the outputs
chart, the activity feed) unless asked with `include_hidden`; by id, its file, text and search still work; an
older row with `hidden` in its meta is marked by the migration; `[outputs] hidden_keep_days` moves old ones to
the trash, off by default."""

from __future__ import annotations

import asyncio
import sqlite3
import time

from utils.config import Config
from utils.db import MIGRATIONS, migrate
from utils.events import ActivityLog
from utils.outputs import retention
from utils.outputs.announce import Announcer
from utils.tests.outputs.conftest import index
from utils.tools import hub_tools

PAGE = "# The 15 best things to do in Tallahassee\n\nSource: <https://x.example/>\n\n---\n\nThe Museum of Florida History.\n"


def _web(tree, rel: str, ts: float, **side) -> None:
    tree.put(rel, PAGE, sidecar={"title": "THE 15 BEST Things to Do in Tallahassee", "kind": "text", "created_ts": ts,
                                 "source": {"service": "web", "url": "https://x.example/"}, "hidden": True, **side})


async def test_listing_leaves_hidden_out_unless_asked(app, client, hub_tree):
    hub_tree.put("tts/2026-10-21/100000-hello.wav", 100, sidecar={"created_ts": 1000})
    hub_tree.put("uploads/2026-10-21/100001-notes.md", "my notes", sidecar={"created_ts": 2000})
    _web(hub_tree, "web/2026-10-21/102403-tripadvisor-com-things.md", 3000)
    _web(hub_tree, "web/2026-10-21/102500-example-com-other.md", 4000, title="Other")
    hub_tree.put("web/2026-10-21/102600-shown.md", "x", sidecar={"created_ts": 5000, "hidden": False})   # only `true` hides
    await index(app)
    r = (await client.get("/api/outputs")).json()
    assert [o["title"] for o in r["items"]] == ["shown", "notes", "hello"] and not any("hidden" in o for o in r["items"])
    t = r["totals"]
    assert (t["count"], t["by_kind"], t["by_service"], t["hidden"]) == (3, {"audio": 1, "text": 2}, {"tts": 1, "uploads": 1, "web": 1}, 2)
    assert t["size_bytes"] == 100 + len("my notes") + 1
    r = (await client.get("/api/outputs", params={"include_hidden": "true"})).json()
    assert [o["title"] for o in r["items"]] == ["shown", "Other", "THE 15 BEST Things to Do in Tallahassee", "notes", "hello"]
    assert [o.get("hidden") for o in r["items"]] == [None, True, True, None, None]
    assert (r["totals"]["count"], r["totals"]["by_service"]["web"], r["totals"]["hidden"]) == (5, 3, 2)
    # totals.hidden follows the other filters
    assert (await client.get("/api/outputs", params={"service": "tts"})).json()["totals"]["hidden"] == 0
    assert (await client.get("/api/outputs", params={"q": "tallahassee"})).json()["totals"] == \
        {"count": 0, "size_bytes": 0, "by_kind": {}, "by_service": {}, "hidden": 1}
    # paging with the flag keeps it
    p1 = (await client.get("/api/outputs", params={"include_hidden": "true", "limit": 2})).json()
    p2 = (await client.get("/api/outputs", params={"include_hidden": "true", "limit": 2, "cursor": p1["next_cursor"]})).json()
    assert [o["title"] for o in p2["items"]] == ["THE 15 BEST Things to Do in Tallahassee", "notes"]


async def test_by_id_its_file_text_and_search_still_work(app, client, hub_tree):
    _web(hub_tree, "web/2026-10-21/102403-tripadvisor-com-things.md", 3000)
    await index(app)
    oid = (await client.get("/api/outputs", params={"include_hidden": "true"})).json()["items"][0]["id"]
    o = (await client.get(f"/api/outputs/{oid}")).json()
    assert o["hidden"] is True and o["kind"] == "text" and "hidden" not in o["meta"]
    assert o["meta"]["source"]["service"] == "web"
    assert (await client.get(f"/api/outputs/{oid}/file")).text == PAGE
    assert "Museum of Florida History" in (await client.get(f"/api/outputs/{oid}/text")).json()["text"]
    hits = (await client.get(f"/api/outputs/{oid}/search", params={"q": "museum"})).json()
    assert hits["total"] == 1 and "Museum" in hits["hits"][0]["text"]


async def test_overview_agent_search_and_chart_leave_hidden_out(app, client, hub_tree):
    now = time.time()
    hub_tree.put("uploads/2026-10-21/100001-notes.md", "my notes", sidecar={"created_ts": now - 60})
    _web(hub_tree, "web/2026-10-21/102403-tripadvisor-com-things.md", now - 30)
    await index(app)
    ov = (await client.get("/api/overview")).json()
    assert [o["title"] for o in ov["recent_outputs"]] == ["notes"]
    found = await hub_tools.search_outputs(app.state.hub, {"q": "things"})
    assert found == {"outputs": [], "total": 0}
    assert (await hub_tools.search_outputs(app.state.hub, {}))["total"] == 1
    stats = (await client.get("/api/outputs/stats", params={"range": "7d", "by": "service"})).json()
    assert [(b["key"], b["count"]) for b in stats["buckets"]] == [("uploads", 1)]


async def test_no_activity_item_for_a_hidden_output(outs, tree, db, bus):
    act = ActivityLog(db, bus)
    outs.announcer = Announcer(act, quiet_s=0.02, window_s=0.2)
    sub = bus.subscribe()
    _web(tree, "web/2026-10-21/102403-tripadvisor-com-things.md", 3000)
    tree.put("uploads/2026-10-21/100001-notes.md", "my notes", sidecar={"created_ts": 2000})
    await outs.sync()
    await asyncio.sleep(0.1)
    assert [x["text"] for x in act.recent()] == ['uploads created "notes"']
    evs = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    assert sorted(e["output"].get("hidden", False) for e in evs if e["type"] == "output") == [False, True]   # pages hear it


def test_the_migration_marks_rows_indexed_with_hidden_in_their_meta(tmp_path):
    conn = sqlite3.connect(tmp_path / "hub.db")
    migrate(conn, MIGRATIONS[:11])
    for oid, meta in (("a", '{"hidden": true, "url": "u"}'), ("b", '{"hidden": false}'), ("c", "{}"), ("d", "not json")):
        conn.execute("INSERT INTO outputs (id, service, kind, title, path, created_ts, meta, sig) VALUES (?, 'web', 'text', ?, ?, 1, ?, 's')",
                     (oid, oid, f"web/{oid}.md", meta))
    conn.commit()
    assert migrate(conn) == len(MIGRATIONS)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, hidden, sig FROM outputs")}
    assert rows == {"a": (1, ""), "b": (0, "s"), "c": (0, "s"), "d": (0, "s")}     # "a" is described again at the next rescan


async def test_retention_is_off_by_default_and_moves_old_hidden_outputs_to_the_trash(outs, tree):
    assert Config().outputs.hidden_keep_days == 0
    now = time.time()
    _web(tree, "web/2026-09-01/102403-old.md", now - 40 * 86400)
    _web(tree, "web/2026-10-21/102403-new.md", now - 86400)
    tree.put("tts/2026-09-01/100000-old-but-mine.wav", 10, sidecar={"created_ts": now - 400 * 86400})
    await outs.sync()
    assert await retention.expire_hidden(outs, 0) == 0
    assert (tree.dir / "web/2026-09-01/102403-old.md").exists()
    assert await retention.expire_hidden(outs, 30) == 1
    assert not (tree.dir / "web/2026-09-01/102403-old.md").exists()
    assert not (tree.dir / "web/2026-09-01/102403-old.md.json").exists()
    assert list((tree.dir / ".trash").rglob("102403-old.md"))                      # recoverable for the trash's 30 days
    assert (tree.dir / "web/2026-10-21/102403-new.md").exists() and (tree.dir / "tts/2026-09-01/100000-old-but-mine.wav").exists()
    left = await outs.list(include_hidden=True)
    assert sorted(o["title"] for o in left["items"]) == ["THE 15 BEST Things to Do in Tallahassee", "old but mine"]
    assert "Moved 1 saved web page older than 30 days" in outs.activity.recent()[0]["text"]
