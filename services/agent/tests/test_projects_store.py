"""Plan projects 1.1: the project store (projects, sources) and chats filtered and grouped by project."""

from __future__ import annotations

import itertools

import pytest

from agent.projects.store import MAX_SOURCES, ProjectError, ProjectStore
from agent.store import Store


def _stores(tmp_path):
    s = Store(tmp_path / "agent.db")
    tick = itertools.count(1000)
    return s, ProjectStore(s, clock=lambda: float(next(tick)))


def test_create_get_update(tmp_path):
    _, ps = _stores(tmp_path)
    p = ps.create("  Thesis   draft ", "Chapter work", "Answer in French", ["grants", "grants", "notes"],
                  {"model": "m1", "mode": "auto", "disabled": ["comfy"], "skills": ["a:b"], "bogus": 1})
    assert p["id"].startswith("p_") and len(p["id"]) == 12
    assert p["name"] == "Thesis draft" and p["environments"] == ["grants", "notes"]
    assert p["defaults"] == {"model": "m1", "mode": "auto", "disabled": ["comfy"], "skills": ["a:b"]}
    assert p["pinned"] is False and p["chats"] == 0 and p["source_count"] == 0
    q = ps.update(p["id"], name="Thesis", pinned=True, environments=["notes"], defaults={"mode": "plan"})
    assert q["name"] == "Thesis" and q["pinned"] is True and q["environments"] == ["notes"] and q["defaults"] == {"mode": "plan"}
    assert q["updated"] > p["updated"]
    with pytest.raises(ProjectError):
        ps.create("   ")
    with pytest.raises(ProjectError):
        ps.update(p["id"], instructions="x" * 16_001)
    assert ps.by_name("THESIS")["id"] == p["id"]


def test_list_search_sort_pins(tmp_path):
    s, ps = _stores(tmp_path)
    a = ps.create("alpha", "about birds")
    b = ps.create("Beta", "fish")
    c = ps.create("gamma", "more birds")
    assert [p["name"] for p in ps.list()] == ["gamma", "Beta", "alpha"]            # recent activity: newest first
    assert [p["name"] for p in ps.list(sort="name")] == ["alpha", "Beta", "gamma"]
    assert [p["name"] for p in ps.list(sort="created")] == ["gamma", "Beta", "alpha"]
    t = s.create_thread("chat", None, "manual", {"project": a["id"]})
    s.update_thread(t["id"], title="later")                                         # a chat's activity counts
    s._c.execute("UPDATE threads SET updated = 5000 WHERE id = ?", (t["id"],))
    assert [p["name"] for p in ps.list()][0] == "alpha"
    assert ps.get(a["id"])["chats"] == 1
    before = ps.get(b["id"])["updated"]
    ps.update(b["id"], pinned=True)
    assert ps.get(b["id"])["updated"] == before                                     # a pin isn't activity (5.1)
    assert [p["name"] for p in ps.list(sort="name")] == ["Beta", "alpha", "gamma"]   # pins on top
    assert {p["name"] for p in ps.list(q="birds")} == {"alpha", "gamma"}
    assert [p["name"] for p in ps.list(q="BET")] == ["Beta"]
    assert c["id"] in {p["id"] for p in ps.list()}


def test_sources_add_reorder_remove(tmp_path):
    _, ps = _stores(tmp_path)
    p = ps.create("p")
    f = ps.add_source(p["id"], "file", output_id="o1", title="Paper.pdf", chars=1200)
    g = ps.add_source(p["id"], "page", url="https://example.com/news", title="News")
    assert f["id"].startswith("src_") and f["max_age_s"] is None and g["max_age_s"] == 3600
    assert [x["id"] for x in ps.sources(p["id"])] == [f["id"], g["id"]]
    with pytest.raises(ProjectError) as e:
        ps.add_source(p["id"], "file", output_id="o1")
    assert e.value.code == "exists"
    with pytest.raises(ProjectError):
        ps.add_source(p["id"], "page")                                               # no URL
    with pytest.raises(ProjectError):
        ps.add_source(p["id"], "video", output_id="x")
    assert [x["id"] for x in ps.reorder(p["id"], [g["id"]])] == [g["id"], f["id"]]
    ps.update_source(g["id"], status="error", error="timed out", max_age_s=900)
    assert ps.source(g["id"])["error"] == "timed out" and ps.source(g["id"])["max_age_s"] == 900
    with pytest.raises(ProjectError):
        ps.update_source(g["id"], status="weird")
    assert ps.remove_source(f["id"]) and not ps.remove_source(f["id"])
    assert [x["id"] for x in ps.sources(p["id"])] == [g["id"]]
    assert ps.delete(p["id"]) and ps.sources(p["id"]) == [] and ps.get(p["id"]) is None


def test_source_limit(tmp_path):
    _, ps = _stores(tmp_path)
    p = ps.create("big")
    for i in range(MAX_SOURCES):
        ps.add_source(p["id"], "file", output_id=f"o{i}")
    with pytest.raises(ProjectError) as e:
        ps.add_source(p["id"], "file", output_id="one-more")
    assert e.value.code == "too_many_sources" and e.value.status == 409
    other = ps.create("other")
    assert ps.add_source(other["id"], "file", output_id="o0")                       # per project


def test_threads_by_project(tmp_path):
    s, ps = _stores(tmp_path)
    a, b = ps.create("a"), ps.create("b")
    s.create_thread("one", None, "manual", {"project": a["id"]})
    s.create_thread("two", None, "manual", {"project": a["id"], "environment": "grants"})
    s.create_thread("three", None, "manual", {"project": b["id"]})
    s.create_thread("four", None, "manual", {})
    assert {t["title"] for t in s.threads(project=[a["id"]])} == {"one", "two"}
    assert [t["title"] for t in s.threads(project=["none"])] == ["four"]
    assert {t["title"] for t in s.threads(project=[b["id"], "none"])} == {"three", "four"}
    assert [t["title"] for t in s.threads(project=[a["id"]], environment=["grants"])] == ["two"]
    groups = {g["project"]: g["count"] for g in s.groups(by="project")}
    assert groups == {a["id"]: 2, b["id"]: 1, "none": 1}
    assert {g["environment"] for g in s.groups()} == {"default", "grants"}         # the default grouping is unchanged
