"""structured-memory 1.1: entities in a tree with aliases and anchors, facts that are replaced not overwritten,
the change log and undo, and keyword search, in agent.db."""

from __future__ import annotations

import pytest

from agent.memory.model import MemoryError
from agent.memory.store import MemoryStore
from agent.store import Store


@pytest.fixture
def m(tmp_path):
    return MemoryStore(Store(tmp_path / "agent.db"))


def test_entities_paths_and_a_rename_that_keeps_the_old_name(m):
    g = m.create_entity("projects", "AIHub", anchors=[{"kind": "git", "value": "github.com/brendondgr/GAIFA"}])
    sub = m.create_entity("topic", "agent", parent=g["id"])
    assert g["kind"] == "project" and g["path"] == "projects/AIHub" and sub["path"] == "projects/AIHub/agent"
    f = m.add_fact("AIHub's mods use ports 5100-5199", about=["AIHub"])
    r = m.update_entity(g["id"], name="GAIFA")
    assert r["name"] == "GAIFA" and r["aliases"] == ["AIHub"] and r["path"] == "projects/GAIFA"
    assert m.resolve("aihub")["id"] == g["id"] and m.resolve("GAIFA")["id"] == g["id"] and m.resolve("projects/GAIFA/agent")["id"] == sub["id"]
    assert m.fact_public(m.need_fact(f["id"]))["entities"][0]["path"] == "projects/GAIFA"     # the fact follows
    assert m.resolve("you")["id"] == "user" and m.public(m.need("user"))["path"] == "you"
    with pytest.raises(MemoryError) as e:
        m.create_entity("project", "aihub")                                          # an old name is still taken
    assert e.value.code == "exists"
    with pytest.raises(MemoryError):
        m.update_entity(g["id"], parent=sub["id"])                                   # no cycles


def test_alias_and_anchor_clashes(m):
    a = m.create_entity("person", "Ana")
    b = m.create_entity("person", "Bo", aliases=["Robert"])
    with pytest.raises(MemoryError) as e:
        m.update_entity(a["id"], aliases_add=["robert"])
    assert e.value.code == "alias_taken"
    m.update_entity(a["id"], anchors_add=[{"kind": "folder", "value": "/home/u/x"}])
    with pytest.raises(MemoryError) as e:
        m.update_entity(b["id"], anchors_add=[{"kind": "folder", "value": "/home/u/x"}])
    assert e.value.code == "anchor_taken"


def test_facts_replace_never_overwrite(m):
    f1 = m.add_fact("Prefers 16:9 images", kind="preference")
    assert f1["entities"][0]["id"] == "user" and f1["current"]
    again = m.add_fact("prefers 16:9 images.", kind="preference", evidence=[{"thread": "t1", "seq": 3}])
    assert again["id"] == f1["id"] and again["seen"] == 2 and again["evidence"] == [{"thread": "t1", "seq": 3}]
    f2 = m.add_fact("Prefers 4:3 images", kind="preference", replaces=f1["id"], valid_from="2026-10-26")
    old = m.fact_public(m.need_fact(f1["id"]))
    assert old["state"] == "retired" and old["replaced_by"] == f2["id"] and old["valid_until"] == "2026-10-26" and not old["current"]
    assert [f["id"] for f in m.facts_of("user")] == [f2["id"]]
    assert {f["id"] for f in m.facts_of("user", current=False)} == {f1["id"], f2["id"]}
    with pytest.raises(MemoryError):
        m.add_fact("x", replaces=f1["id"])                                           # only a current fact is replaced


def test_proposed_facts_and_their_new_entities_wait_for_approval(m):
    p = m.add_fact("Is writing a thesis on memory", about=[{"name": "Thesis", "kind": "project"}], source="inferred",
                   evidence=[{"thread": "t9", "seq": 4}])
    assert p["state"] == "proposed" and m.resolve("Thesis") is None                  # proposed: not found yet
    assert m.tree()["proposed"] == 2
    a = m.set_fact_state(p["id"], "active")
    assert a["current"] and m.resolve("Thesis")["kind"] == "project"
    r = m.add_fact("Uses LaTeX", source="inferred")
    assert m.set_fact_state(r["id"], "rejected")["state"] == "rejected"


def test_merge_and_undo(m):
    a = m.create_entity("project", "Ariadne")
    b = m.create_entity("project", "Ariadne site")
    f = m.add_fact("Ariadne site is built with Astro", about=[b["id"]])
    merged = m.merge(b["id"], a["id"])
    assert "Ariadne site" in merged["aliases"] and m.resolve("Ariadne site")["id"] == a["id"]
    assert [x["id"] for x in m.facts_of(a["id"])] == [f["id"]]
    log = m.log(limit=1)[0]
    assert log["op"] == "merge"
    m.undo(log["id"])
    assert m.resolve("Ariadne site")["id"] == b["id"] and [x["id"] for x in m.facts_of(b["id"])] == [f["id"]]
    assert m.facts_of(a["id"]) == []
    with pytest.raises(MemoryError):
        m.undo(log["id"])


def test_undo_a_rename_and_an_edit(m):
    g = m.create_entity("project", "AIHub")
    m.update_entity(g["id"], name="GAIFA")
    m.undo(m.log(limit=1)[0]["id"])
    e = m.public(m.need(g["id"]))
    assert e["name"] == "AIHub" and e["aliases"] == [] and m.resolve("GAIFA") is None
    f = m.add_fact("Runs on port 7000", about=["AIHub"])
    m.update_fact(f["id"], text="Runs on 127.0.0.1:7000")
    m.undo(m.log(limit=1)[0]["id"])
    assert m.need_fact(f["id"])["text"] == "Runs on port 7000"


def test_forget_and_retire(m):
    f = m.add_fact("Lives in Tallahassee")
    m.set_fact_state(f["id"], "retired")
    assert not m.fact_public(m.need_fact(f["id"]))["current"]
    m.forget(f["id"])
    assert m.fact_row(f["id"]) is None and m.log(limit=1)[0]["op"] == "forget"
    assert "Tallahassee" not in str(m.log())


def test_keyword_search_finds_current_facts_and_entities_by_any_name(m):
    g = m.create_entity("project", "AIHub")
    f = m.add_fact("The hub listens on loopback only", about=[g["id"]])
    old = m.add_fact("The hub used port 8000", about=[g["id"]])
    m.add_fact("The hub uses port 7000", about=[g["id"]], replaces=old["id"])
    m.update_entity(g["id"], name="GAIFA")
    refs = dict(m.keyword("loopback"))
    assert f"fact:{f['id']}" in refs
    assert f"fact:{old['id']}" not in dict(m.keyword("8000"))                       # replaced: not current
    assert f"entity:{g['id']}" in dict(m.keyword("aihub")) and f"fact:{f['id']}" in dict(m.keyword("gaifa"))


def test_the_tree(m):
    g = m.create_entity("project", "GAIFA")
    m.create_entity("topic", "memory", parent=g["id"])
    m.add_fact("Is building GAIFA", about=["GAIFA"])
    t = m.tree()
    kinds = {k["kind"]: k for k in t["kinds"]}
    assert kinds["project"]["entities"][0]["name"] == "GAIFA" and kinds["project"]["entities"][0]["facts"] == 1
    assert kinds["project"]["entities"][0]["children"][0]["name"] == "memory" and "topic" not in kinds


def test_about_with_a_name_and_its_path_is_one_entry(m):
    f = m.add_fact("The site deploys to Netlify", about=["Ariadne", "projects/Ariadne"])
    assert [e["path"] for e in f["entities"]] == ["projects/Ariadne"] and len(m.entities()) == 2      # the user and Ariadne
    t = m.create_entity("topic", "Cooking")
    g = m.add_fact("Likes Thai food", about=["projects/Cooking"])                 # another kind by that name: used
    assert [e["id"] for e in g["entities"]] == [t["id"]]
    h = m.add_fact("Uses the agent loop", about=["projects/Ariadne/agent", "you"])
    assert sorted(e["path"] for e in h["entities"]) == ["projects/Ariadne/agent", "you"]
