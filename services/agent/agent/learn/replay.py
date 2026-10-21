"""Replays (plan 22.3): a real chat becomes a dry-run task, run again under a candidate harness.

The replay sends your messages verbatim, answers its questions with your recorded answers, and
answers its cards with the arguments you ran, so it goes on as the real chat did. The checks come
from the record, not from a grader:

- **pre-chosen**: of the fields you changed on the chat's cards, the share the candidate now picks
  itself (the arguments on its card before anyone edits them);
- **no denied repeat**: a call you denied isn't made again with the same arguments;
- **errors**: no more tool errors and refusals than the real chat had.

Replays run in this agent as dry runs pinned to the candidate's version (`settings.harness`), so
nothing is generated or changed; their threads are archived and pruned like eval threads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from evals.harness import Harness as EvalHarness
from evals.harness import Run, Task

from .. import context as ctx


@dataclass
class Record:
    """What a real chat did, for its replay."""
    thread: str
    turns: list[str]
    answers: dict[str, str] = field(default_factory=dict)            # question → answer
    cards: list[dict[str, Any]] = field(default_factory=list)          # [{tool, final, edited, approve}] in order
    errors: int = 0

    @property
    def edited(self) -> int:
        return sum(len(c["edited"]) for c in self.cards)


def record(events: list[dict[str, Any]], tid: str) -> Record:
    rec = Record(tid, [])
    approvals: dict[str, dict[str, Any]] = {}
    for e in events:
        t, p = e["type"], e.get("payload") or {}
        if t == "user" and ctx.said(p):
            rec.turns.append(ctx.said(p))      # the text and any replies to quoted parts
        elif t == "answer":
            rec.answers.update({q: a for q, a in (p.get("answers") or {}).items() if isinstance(a, str)})
        elif t == "approval":
            approvals[p.get("id")] = p
        elif t == "decision":
            a = approvals.get(p.get("id")) or {}
            final = p.get("arguments") if p.get("arguments") is not None else (a.get("arguments") or {})
            proposed = a.get("arguments") or {}
            edited = [k for k in final if json.dumps(final.get(k), sort_keys=True) != json.dumps(proposed.get(k), sort_keys=True)]
            rec.cards.append({"tool": a.get("tool"), "final": final, "edited": edited, "approve": bool(p.get("approve")),
                              "proposed": proposed})
        elif t == "tool_result" and p.get("status") == "error":
            rec.errors += 1
    return rec


def _cards(rec: Record):
    """The replay's card script: your recorded final arguments for the n-th card of each tool."""
    seen: dict[str, int] = {}

    def card(a: dict[str, Any]):
        tool = a.get("tool")
        i = seen.get(tool, 0)
        seen[tool] = i + 1
        mine = [c for c in rec.cards if c["tool"] == tool]
        if i >= len(mine):
            return a.get("risk") != "destructive", None
        c = mine[i]
        keep = {k: v for k, v in c["final"].items() if k in ((a.get("schema") or {}).get("properties") or {})}
        return c["approve"], keep or None
    return card


def _answer(rec: Record):
    def answer(q: dict[str, Any]) -> dict[str, str]:
        out = {}
        for x in q.get("questions") or []:
            got = rec.answers.get(x["question"])
            out[x["question"]] = got if got is not None else (x.get("options") or [{"label": "yes"}])[0]["label"]
        return out
    return answer


def score(rec: Record, run: Run) -> dict[str, Any]:
    """The record's checks against a replay run."""
    cards = run.of("approval")
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for a in cards:
        by_tool.setdefault(a.get("tool"), []).append(a)
    hit = total = 0
    for tool in {c["tool"] for c in rec.cards}:
        mine = [c for c in rec.cards if c["tool"] == tool]
        theirs = by_tool.get(tool, [])
        for c, a in zip(mine, theirs):
            for f in c["edited"]:
                total += 1
                hit += json.dumps((a.get("arguments") or {}).get(f), sort_keys=True) == json.dumps(c["final"].get(f), sort_keys=True)
        total += sum(len(c["edited"]) for c in mine[len(theirs):])      # cards the replay never reached
    denied = [c for c in rec.cards if not c["approve"]]
    repeats = sum(1 for d in denied for a in by_tool.get(d["tool"], []) if (a.get("arguments") or {}) == d["proposed"])
    errors = sum(1 for r in run.of("tool_result") if r.get("status") == "error")
    return {"pre_chosen": round(hit / total, 3) if total else None, "edited_fields": total, "denied_repeats": repeats,
            "errors": errors, "errors_before": rec.errors, "ran": not run.error, "seconds": run.seconds}


async def replay(rec: Record, version: int, base: str, model: str, transport: Any = None, timeout: float = 600) -> dict[str, Any]:
    """Run the record under harness `version` (a dry run) and score it."""
    h = EvalHarness(base, model, dry_run=True, transport=transport, log=lambda _m: None)
    try:
        task = Task(f"replay-{rec.thread}-v{version}", "replay", rec.turns[:8], [], settings={"harness": version},
                    answer=_answer(rec), card=_cards(rec), timeout=timeout)
        run = await h.run(task)
    finally:
        await h.close()
    return {"thread": rec.thread, "version": version, **score(rec, run)}
