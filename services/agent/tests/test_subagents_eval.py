"""Plan agent-workflows 5.1: the sub-agents eval's graders and summary (the eval itself runs live: evals/subagents.py)."""

from __future__ import annotations

from evals import subagents as ev


def test_graders(tmp_path):
    assert ev.has_all("load", "total")("It has load() and Total().", tmp_path)
    assert not ev.has_all("load", "discount")("only load", tmp_path)
    (tmp_path / "greet.py").write_text("def welcome(name):\n    return 'hi ' + name\n")
    (tmp_path / "app.py").write_text("from greet import welcome\n\nprint(welcome('ann'))\n")
    assert ev.renamed("", tmp_path)
    (tmp_path / "app.py").write_text("from greet import greet\n\nprint(greet('ann'))\n")
    assert not ev.renamed("", tmp_path)
    assert {c.kind for c in ev.CASES} == {"split", "single"} and all("{folder}" in c.prompt for c in ev.CASES)


def test_summary():
    rows = [{"kind": "split", "sub_agents": True, "passed": True, "tokens": 100, "seconds": 10, "spawned": 3},
            {"kind": "split", "sub_agents": False, "passed": False, "tokens": 50, "seconds": 8, "spawned": 0},
            {"kind": "single", "sub_agents": True, "passed": True, "tokens": 20, "seconds": 2, "spawned": 1}]
    s = ev.summarise(rows)
    assert s["split/on"] == {"passed": "1/1", "tokens": 100, "seconds": 10.0, "spawned": 3}
    assert s["single/on"]["spawned"] == 1 and "single/off" not in s
