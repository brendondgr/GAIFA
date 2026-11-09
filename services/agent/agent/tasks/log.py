"""A run's judgement log (plan scheduled-tasks 3.3): every tool call of the run, in order, with what decided it.

`log(agent, thread_id) -> [{seq, tool, summary, outcome, by, reason}]`:
- `outcome`: `allowed` (it ran), `refused` (it would have asked; no one was there), `denied` (a rule, the mode or a
  folder's level said no), `asked` (a card, in a test run or after the run) or `pending`;
- `by`: `pre-allow` (one of the run chat's own grants ran it: the task's pre-allows, or one approved in a test run),
  `always` (one of your grants for every chat, Settings → Permissions), `rules` (the judge's rules or your command rules), `judge`
  (the decision model), `mode` (the mode and the tool's risk, your permission lists, a preflight), `you` (a card you
  decided), `local` (the agent's own tools: notes, questions, finding tools).

It reads the chat's own events: each call's result carries the judge's verdict (`judge`) and the grant that ran it
(`grant_id`), and a card its decision. Only the run's chat is read: after the run, it's an ordinary chat and its
later calls are listed too.
"""

from __future__ import annotations

import json
from typing import Any

from ..tools import LOCAL_NAMES

RULES = ("rules", "user")


def _summary(name: str, args: Any, judge: dict[str, Any] | None) -> str:
    if judge and judge.get("summary"):
        return str(judge["summary"])[:200]
    try:
        text = json.dumps(args, ensure_ascii=False, separators=(", ", ": "))
    except (TypeError, ValueError):
        text = str(args)
    return f"{name}: {text[:160]}"


def log(agent: Any, thread_id: str, own: set[str] | None = None) -> list[dict[str, Any]]:
    """`own`: the ids of the chat's own grants (`GET /api/grants?thread=`); a grant not among them is one of yours
    for every chat. None: every grant counts as the chat's own."""
    evs = agent.store.events(thread_id, types=("tool_call", "tool_result", "approval", "decision", "call"))
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for e in evs:
        if e["type"] != "tool_call":
            by_id.setdefault(e["payload"].get("id"), {})[e["type"]] = e["payload"]
    out = []
    for e in evs:
        if e["type"] != "tool_call":
            continue
        p = e["payload"]
        name, rest = p.get("name") or "?", by_id.get(p.get("id"), {})
        res, ap, dec, call = rest.get("tool_result") or {}, rest.get("approval"), rest.get("decision"), rest.get("call") or {}
        judge = res.get("judge") or call.get("judge") or (ap or {}).get("judge")
        err = res.get("error") or {}
        row = {"seq": e["seq"], "tool": name, "summary": _summary(name, p.get("arguments"), judge)}
        if name in LOCAL_NAMES and name != "remember":
            outcome = "refused" if err.get("code") == "unattended" else "allowed"
            row.update(outcome=outcome, by="local", reason=err.get("detail") or "the agent's own tool")
        elif gid := res.get("grant_id") or call.get("grant_id"):
            if own is None or gid in own:
                row.update(outcome="allowed", by="pre-allow", reason="the task allows it ahead of time")
            else:
                row.update(outcome="allowed", by="always", reason="you allow it in every chat (Settings → Permissions)")
        elif dec is not None:
            row.update(outcome="asked", by="you", reason="you approved it" if dec.get("approve") else (dec.get("reason") or "you said no"))
        elif ap is not None:
            row.update(outcome="pending", by="you", reason="waiting for your answer")
        elif err.get("code") == "unattended":
            row.update(outcome="refused", by=("rules" if judge.get("source") in RULES else "judge") if judge else "mode",
                       reason=(judge or {}).get("reason") or err.get("detail") or "it asks first")
        elif res.get("status") == "denied":
            row.update(outcome="denied", by="mode", reason=err.get("detail") or "not allowed")
        elif judge:
            row.update(outcome="allowed", by="rules" if judge.get("source") in RULES else "judge", reason=judge.get("reason") or "")
        elif not res:
            row.update(outcome="pending", by="mode", reason="still running")
        else:
            row.update(outcome="allowed", by="mode", reason="the mode and the tool's risk let it run")
        out.append(row)
    return out
