"""22.5: the learner's library: entries with cue, lesson, evidence and confidence, and an index."""

from agent.learn.library import Library


def test_entries_and_index(tmp_path):
    lib = Library(tmp_path, "comfy")
    assert lib.text() == "(none yet)"
    assert lib.add("r1", {"cue": "only a cue"}) is None                       # no lesson, no evidence: not kept
    lib.add("r1", {"cue": "an edit pack refuses references", "lesson": "add a tool note", "evidence": "replay errors 3 → 0", "confidence": "low"},
            diff="+note", adopted="adopted")
    assert lib.listing() == [{"run": "r1", "cue": "an edit pack refuses references", "lesson": "add a tool note",
                              "evidence": "replay errors 3 → 0", "confidence": "low", "version": None, "withdrawn": None}]
    assert "an edit pack refuses references" in (lib.dir / "INDEX.md").read_text() and "add a tool note" in lib.text()
    assert (lib.dir / "entries" / "r1" / "adopted.diff").read_text() == "+note"


def lesson(cue):
    return {"cue": cue, "lesson": "add a tool note", "evidence": "chat 1", "confidence": "high"}


def test_a_lesson_is_withdrawn_when_its_version_is_rejected_or_rolled_back(tmp_path):
    from agent.harness import Harness

    h = Harness(tmp_path)
    v1 = h.create({"tools/gen3d_make_3d.md": "note one\n"}, parent=0, activate=True)
    v2 = h.create({"tools/gen3d_make_3d.md": "note two\n"}, parent=v1, activate=True)
    lib = Library(tmp_path, "gen3d")
    lib.add("r1", lesson("first"), adopted="adopted", version=v1)
    lib.add("r2", lesson("second"), adopted="adopted", version=v2)
    lib.add("r3", lesson("a failed gate"), adopted="gate failed", version=h.create({"tools/gen3d_make_3d.md": "x\n"}, parent=v2, adopted_by="rejected"))
    pending = h.create({"systemprompt.md": "a new prompt\n"}, parent=v2, adopted_by="proposed")
    lib.add("r4", lesson("waiting for you"), adopted="proposed", version=pending)
    assert [e["withdrawn"] for e in lib.listing()] == [None, None, None, None]

    h.activate(v1)                                                  # a rollback: v2's lesson no longer holds
    assert [e["withdrawn"] for e in lib.listing()][:2] == [None, f"version {v2} was rolled back"]
    assert "second" not in lib.text() and "first" in lib.text() and "a failed gate" in lib.text()
    assert "(withdrawn: version 2 was rolled back)" in (lib.dir / "INDEX.md").read_text()
    h.activate(v2)                                                  # forward again: it holds again
    assert "second" in lib.text()

    h.set_meta(v1, adopted_by="rejected")                           # rejected by hand after it went live
    assert lib.listing()[0]["withdrawn"] == f"version {v1} was rejected" and "first" not in lib.text()
    assert lib.listing()[3]["withdrawn"] is None                    # a proposal still waiting is not withdrawn


def test_an_older_entry_finds_its_version_in_the_run_record(tmp_path):
    import json

    from agent.harness import Harness

    h = Harness(tmp_path)
    v = h.create({"tools/gen3d_make_3d.md": "a wrong note\n"}, parent=0, activate=True)
    lib = Library(tmp_path, "gen3d")
    lib.add("r1", lesson("old"), adopted="adopted")                 # written before entries carried a version
    (tmp_path / "learn" / "runs").mkdir(parents=True)
    (tmp_path / "learn" / "runs" / "r1.json").write_text(json.dumps({"domains": [{"domain": "comfy", "final": 99},
                                                                                {"domain": "gen3d", "final": v}]}))
    assert lib.listing()[0]["version"] == v and lib.listing()[0]["withdrawn"] is None
    h.activate(0)
    assert lib.listing()[0]["withdrawn"] == f"version {v} was rolled back" and lib.text() == "(none yet)"
