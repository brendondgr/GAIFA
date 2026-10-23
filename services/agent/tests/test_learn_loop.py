"""22.5: the improvement loop with the scripted model: a tool note adopted, keeping the base, a failed
gate, an invalid proposal retried then dropped, a prompt change becoming a proposal, the library."""

from __future__ import annotations

import json

from agent.harness import Harness
from agent.learn.library import Library
from agent.learn.loop import Learner, render

NOTE = {"keep_base": False, "files": {"tools/gen3d_make_3d.md": "Send stages as a list, e.g. [\"shape\", \"preview\"].\n"},
        "notes": "chat 1: stages sent as a string, invalid_arguments twice"}
EXP = {"cue": "a tool refuses an argument's shape twice", "lesson": "add a tool note with the exact shape",
       "evidence": "replay errors 2 → 0", "confidence": "medium: one chat"}


def seed_chat(env, n=1):
    st = env.agent.store
    for i in range(n):
        tid = st.create_thread(title=f"real {i}")["id"]
        st.append(tid, "user", {"text": "make a 3D fox"})
        st.append(tid, "tool_call", {"id": "c", "name": "gen3d_make_3d", "arguments": {"prompt": "fox", "stages": "shape"}})
        st.append(tid, "tool_result", {"id": "c", "name": "gen3d_make_3d", "status": "error", "error": {"code": "invalid_arguments", "detail": "stages: expected array"}})


def script(env, inv=NOTE, pref=None, compose=NOTE, exp=EXP):
    env.model.queue({"match": "You are reviewing", "text": "Chat 1: stages sent as a string; the call failed twice."},
                    {"match": "YOUR DIMENSION: INV", "text": json.dumps(inv)},
                    {"match": "YOUR DIMENSION: PREF", "text": json.dumps(pref or {"keep_base": True, "notes": "nothing about tastes"})},
                    {"match": "You are composing", "text": "Here you go:\n" + json.dumps(compose)},
                    {"match": "one improvement round", "text": json.dumps(exp) if exp else "NO_ENTRY"})


async def stub_probe(records, version):
    return {"pre_chosen": None, "errors": 0 if version else 2, "denied_repeats": 0, "ran": True, "replays": len(records)}


def learner(env, ok=True):
    async def gate(domain, cur, cand, full):
        return {"ok": ok, "full": full, "current": 0.8, "candidate": 0.9 if ok else 0.5, "why": "" if ok else "worse"}
    return Learner(env.agent, "http://agent", model="main", gate=gate, probe=stub_probe)


async def test_a_tool_note_is_adopted_and_learned(env):
    seed_chat(env)
    script(env)
    rec = await learner(env).run(["gen3d"])
    [d] = rec["domains"]
    h = Harness(env.agent.cfg.data)
    assert rec["state"] == "done" and d["decision"] == "adopted" and h.current() == d["final"]
    assert h.tree()["tools/gen3d_make_3d.md"].startswith("Send stages as a list")
    assert h.meta(d["final"])["adopted_by"] == "auto" and h.meta(d["final"])["gate"]["ok"]
    [entry] = Library(env.agent.cfg.data, "gen3d").listing()
    assert entry["cue"] == EXP["cue"] and entry["version"] == d["final"] and entry["withdrawn"] is None
    h.activate(0)                                                   # rolled back: the next round no longer reads it
    assert Library(env.agent.cfg.data, "gen3d").text() == "(none yet)"
    h.activate(d["final"])
    stages = [x["stage"] for x in rec["ledger"]]
    assert stages[:3] == ["gen3d:reflect", "gen3d:propose-INV", "gen3d:propose-PREF"] and "gen3d:compose" in stages
    assert (env.agent.cfg.data / "learn" / "runs" / f"{rec['id']}.json").is_file()
    again = await learner(env).run(["gen3d"])                       # nothing new since: no work
    assert again["domains"] == []


async def test_both_keep_the_base(env):
    seed_chat(env)
    script(env, inv={"keep_base": True, "notes": "fine"}, compose=None, exp=None)
    rec = await learner(env).run(["gen3d"])
    assert rec["domains"][0]["candidates"] == [] and Harness(env.agent.cfg.data).current() == 0


async def test_a_failed_gate_keeps_the_current_version(env):
    seed_chat(env)
    script(env)
    rec = await learner(env, ok=False).run(["gen3d"])
    d = rec["domains"][0]
    h = Harness(env.agent.cfg.data)
    assert d["decision"] == "gate failed" and h.current() == 0 and h.meta(d["final"])["adopted_by"] == "rejected"


async def test_an_invalid_proposal_is_retried_then_dropped(env):
    seed_chat(env)
    bad = {"keep_base": False, "files": {"secret.py": "print(1)"}, "notes": "x"}
    env.model.queue({"match": "You are reviewing", "text": "r"}, {"match": "YOUR DIMENSION: INV", "text": json.dumps(bad)},
                    {"match": "YOUR LAST REPLY WAS REFUSED", "text": json.dumps(bad)},
                    {"match": "YOUR DIMENSION: PREF", "text": json.dumps({"keep_base": True})})
    rec = await learner(env).run(["gen3d"])
    assert rec["domains"][0]["candidates"] == []
    assert any(x.get("refused") for x in rec["ledger"])


async def test_a_prompt_change_becomes_a_proposal(env):
    seed_chat(env)
    rule = {"keep_base": False, "files": {"guardrails.md": "- Ask before making 3D from text.\n"}, "notes": "chat 1"}
    script(env, inv=rule, compose=rule)
    rec = await learner(env).run(["gen3d"])
    d = rec["domains"][0]
    h = Harness(env.agent.cfg.data)
    assert d["decision"] == "proposed" and h.current() == 0 and h.meta(d["final"])["adopted_by"] == "proposed"
    r = await env.client.post(f"/v1/harness/versions/{d['final']}/activate")
    assert r.json()["current"] == d["final"] and h.meta(d["final"])["adopted_by"] == "user"


def test_render_shows_edits_denials_and_answers():
    ev = [{"type": "user", "payload": {"text": "hi"}},
          {"type": "approval", "payload": {"id": "a", "tool": "t", "arguments": {"preset": "base"}}},
          {"type": "decision", "payload": {"id": "a", "approve": True, "arguments": {"preset": "fast"}}},
          {"type": "approval", "payload": {"id": "b", "tool": "t2", "arguments": {}}},
          {"type": "decision", "payload": {"id": "b", "approve": False, "reason": "no"}},
          {"type": "answer", "payload": {"answers": {"Which?": "This"}}}]
    text = render(ev)
    assert "USER CHANGED THE CARD of t:" in text and "preset: 'base' → 'fast'" in text and "USER DENIED t2: no" in text and "Which? → This" in text


def test_eval_and_opted_out_chats_never_teach_it(env):
    """Overnight 2026-10-21: the learner picked chats by their tool calls only, so eval dry runs and chats
    switched to "don't learn" fed it too (the miner already skipped them)."""
    st = env.agent.store
    ids = {}
    for name, settings in (("real", {}), ("eval", {"dry_run": True}), ("optout", {"no_learn": True})):
        tid = st.create_thread(title=name, settings=settings)["id"]
        st.append(tid, "tool_call", {"id": "c", "name": "gen3d_make_3d", "arguments": {"prompt": "fox"}})
        ids[name] = tid
    assert learner(env).chats("gen3d", 0) == [ids["real"]]


async def test_a_run_stopped_from_outside_is_interrupted_not_running(env):
    """Overnight 2026-10-21: a run cut off when the agent stopped (its coroutine closed, no exception the run
    catches) was saved as "running" and the Learning page showed it running for good."""
    seed_chat(env)
    lr = learner(env)
    coro = lr.run(["gen3d"])
    script(env)
    coro.send(None)                     # starts, then waits on the model
    coro.close()                        # GeneratorExit: what a shutdown does to an unfinished run
    assert [r["state"] for r in lr.runs()] == ["interrupted"]
    old = dict(lr.runs()[0], id="old", state="running", stage="running")   # a record an older agent left behind
    (lr.dir / "runs" / "old.json").write_text(json.dumps(old))
    assert {r["id"]: r["state"] for r in lr.runs()}["old"] == "interrupted"


def test_the_gate_runs_no_live_task():
    from agent.learn.loop import CORE, gate_tasks
    from evals.harness import is_live

    for full in (False, True):
        assert not [t.id for t in gate_tasks("comfy", full) if is_live(t)]
    ids = {t.id for t in gate_tasks("comfy")}
    assert set(CORE) <= ids and "img_full" in ids and "ws_csv_chart" not in ids and "transcribe_summary" not in ids


async def test_the_gate_runs_gpu_tasks_one_at_a_time(env, monkeypatch):
    """Tasks that reach this machine's GPU (stt, embed, the decide screener) never overlap; the rest run 8 at a time."""
    import asyncio

    import evals.harness as eh

    now = {"gpu": 0, "llm": 0}
    most = {"gpu": 0, "llm": 0}

    class FakeHarness:
        def __init__(self, *a, **k):
            pass

        async def run(self, t):
            kind = "gpu" if eh.reaches_gpu(t) else "llm"
            now[kind] += 1
            most[kind] = max(most[kind], now[kind])
            await asyncio.sleep(0.005)
            now[kind] -= 1
            return None

        async def close(self):
            pass

    monkeypatch.setattr(eh, "Harness", FakeHarness)
    monkeypatch.setattr(eh, "grade", lambda t, run: {"ok": True})
    g = await Learner(env.agent, "http://agent", model="main", gate_runs=1).gate("comfy", 0, 1, full=True)
    assert g["ok"] and most["gpu"] == 1 and 1 < most["llm"] <= 8
