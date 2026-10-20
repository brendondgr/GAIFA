"""22.5: the learner's library: entries with cue, lesson, evidence and confidence, and an index."""

from agent.learn.library import Library


def test_entries_and_index(tmp_path):
    lib = Library(tmp_path, "comfy")
    assert lib.text() == "(none yet)"
    assert lib.add("r1", {"cue": "only a cue"}) is None                       # no lesson, no evidence: not kept
    lib.add("r1", {"cue": "an edit pack refuses references", "lesson": "add a tool note", "evidence": "replay errors 3 → 0", "confidence": "low"},
            diff="+note", adopted="adopted")
    assert lib.listing() == [{"run": "r1", "cue": "an edit pack refuses references", "lesson": "add a tool note",
                              "evidence": "replay errors 3 → 0", "confidence": "low"}]
    assert "an edit pack refuses references" in (lib.dir / "INDEX.md").read_text() and "add a tool note" in lib.text()
    assert (lib.dir / "entries" / "r1" / "adopted.diff").read_text() == "+note"
