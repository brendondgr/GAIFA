"""Plan scheduled-tasks 1.2: tasks, runs in order, unread, notes with their limit, and the thread filter by task."""

from __future__ import annotations

import pytest

from agent.store import Store
from agent.tasks import store as ts
from agent.tasks.store import TaskError, TaskStore

DAILY = {"kind": "daily", "time": "07:00"}


@pytest.fixture
def st(tmp_path):
    s = Store(tmp_path / "a.db")
    clock = [1_000_000.0]
    k = TaskStore(s, clock=lambda: clock[0])
    k.clock_ref = clock
    yield s, k
    s.close()


def test_crud(st):
    s, k = st
    t = k.create("Digest", DAILY, instructions="Summarise the news", allow={"tools": ["web_*", "web_*"], "sites": ["Example.COM."]},
                 settings={"disabled": ["comfy"], "nope": 1}, skills=["a:b"], mode="auto")
    assert t["id"].startswith("k_") and t["enabled"] and t["use_profile"] and t["use_project_memory"] and not t["only_own"]
    assert t["allow"] == {"tools": ["web_*"], "sites": ["example.com"], "mcp": []}
    assert t["settings"] == {"disabled": ["comfy"]} and t["skills"] == ["a:b"] and t["when"] == "Every day at 07:00"
    assert t["next_due"] > 1_000_000 and t["last_run"] is None and t["unread"] == 0
    k.create("Off", DAILY, enabled=False, project_id="p_1")
    assert [x["name"] for x in k.list()] == ["Digest", "Off"]                     # on first
    assert [x["name"] for x in k.list(project="p_1")] == ["Off"]
    assert [x["name"] for x in k.list(project="none")] == ["Digest"]
    assert [x["name"] for x in k.list(q="news")] == ["Digest"]
    with pytest.raises(TaskError) as e:
        k.create("", DAILY)
    assert e.value.code == "bad_name"
    with pytest.raises(TaskError) as e:
        k.create("x", {"kind": "daily", "time": "25:00"})
    assert e.value.code == "invalid_schedule"
    with pytest.raises(TaskError) as e:
        k.create("x", DAILY, mode="manual")
    assert e.value.code == "bad_mode"
    with pytest.raises(TaskError):
        k.create("x", DAILY, instructions="y" * 16_001)
    with pytest.raises(TaskError):
        k.create("x", DAILY, keep_days=0)
    assert k.delete(t["id"]) and k.get(t["id"]) is None


def test_next_due_follows(st):
    s, k = st
    t = k.create("x", DAILY)
    off = k.update(t["id"], enabled=False)
    assert off["next_due"] is None and not off["enabled"]
    k.clock_ref[0] += 5 * 86400
    on = k.update(t["id"], enabled=True)
    assert on["next_due"] > k.clock_ref[0]                                     # from now: no catch-up
    hourly = k.update(t["id"], schedule={"kind": "hourly", "every": 1, "minute": 0})
    assert hourly["next_due"] - k.clock_ref[0] <= 3600 and hourly["when"] == "Every hour at :00"
    same = k.update(t["id"], name="y")
    assert same["next_due"] == hourly["next_due"] and same["name"] == "y"
    assert k.due(hourly["next_due"])[0]["id"] == t["id"] and k.due(hourly["next_due"] - 1) == []


def test_runs_and_unread(st):
    s, k = st
    t = k.create("x", DAILY)
    r1 = k.add_run(t["id"], 100.0, state="running", thread_id="t_1", started=100.0)
    r2 = k.add_run(t["id"], 200.0, state="queued")
    assert [r["id"] for r in k.runs(t["id"])] == [r2["id"], r1["id"]]
    assert [r["id"] for r in k.active()] == [r1["id"], r2["id"]]
    assert k.get(t["id"])["last_run"]["id"] == r1["id"]                         # queued runs aren't the last
    k.update_run(r1["id"], state="done", ended=150.0, seen=False, refused=2)
    assert k.unread() == {"count": 1, "tasks": {t["id"]: 1}} and k.get(t["id"])["unread"] == 1
    assert k.run_of_thread("t_1")["refused"] == 2
    k.update_run(r1["id"], seen=True)
    assert k.unread()["count"] == 0
    with pytest.raises(TaskError):
        k.update_run(r1["id"], state="nope")
    assert [r["id"] for r in k.runs(t["id"], before=200.0)] == [r1["id"]]


def test_notes(st):
    s, k = st
    t = k.create("x", DAILY)
    n = k.add_note(t["id"], "  the feed is at   /srv/feed.xml ", thread_id="t_1")
    assert n["text"] == "the feed is at /srv/feed.xml" and n["id"].startswith("n_")
    assert k.update_note(n["id"], "the feed moved to /srv/rss.xml")["text"].endswith("rss.xml")
    with pytest.raises(TaskError):
        k.add_note(t["id"], "x" * 501)
    with pytest.raises(TaskError):
        k.add_note(t["id"], "   ")
    for i in range(ts.NOTES_MAX - 1):
        k.add_note(t["id"], f"note {i}")
    with pytest.raises(TaskError) as e:
        k.add_note(t["id"], "one too many")
    assert e.value.code == "too_many_notes"
    assert k.remove_note(n["id"]) and len(k.notes(t["id"])) == ts.NOTES_MAX - 1


def test_thread_filter_and_release(st):
    s, k = st
    t = k.create("x", DAILY)
    a = s.create_thread("run", None, "auto", {"task": t["id"], "task_run": "r_1", "unattended": True})
    s.create_thread("plain", None, "manual", {})
    assert [x["id"] for x in s.threads(task=[t["id"]])] == [a["id"]]
    assert len(s.threads(task=["none"])) == 1 and s.count(task=[t["id"]]) == 1
    assert k.release_chats(t["id"]) == 1
    assert s.thread(a["id"])["settings"] == {}


def test_detach_project(st):
    s, k = st
    t = k.create("x", DAILY, project_id="p_1", only_own=True)
    assert k.detach_project("p_1") == [t["id"]]
    got = k.get(t["id"])
    assert got["project_id"] is None and not got["enabled"] and not got["only_own"] and got["next_due"] is None
