"""A sub-agent's approvals and questions go to the agent that started it (plan agent-workflows 2.2).

When a sub-agent's turn ends waiting on a card (a hub approval, or a question it asked anyway), its parent gets an
`agent_request` event per open card: `{id, child, label, kind: approval | question, call, approval_id?, tool?, risk?,
arguments?, questions?, in_result}`. A foreground `agent` call returns `needs_review` with them (`in_result`: the model
reads them there, not again as a message) and the sub-agent goes on in the background; a background sub-agent's
request reaches the parent as a message from GAIFA and starts an idle parent's turn.

The parent reviews each with `agent_review {request, action: deny | forward, reason}` (an `agent_review` event):
deny decides the approval as denied, or answers the question, with the reason the sub-agent reads; forward leaves the
card to the user. There is no approve: the parent can never say yes. A request the parent's model read but didn't
review by the end of its turn is forwarded. The user can decide any card at any time (the header's Approvals, the
sub-agent's chat, the parent's dock), and a request decided that way is no longer open.
"""

from __future__ import annotations

import json
from typing import Any

from .. import context as ctx
from ..store import new_id
from .runner import spawn_of

DENIED_BY_PARENT = "the chat that started you said no: {reason}"


def _decided(agent: Any, child: str, call: str) -> bool:
    return agent._find(child, "decision", call) is not None or agent._find(child, "tool_result", call) is not None


def open_cards(agent: Any, child: str) -> list[dict[str, Any]]:
    """The sub-agent's cards still waiting: its last step's approvals without a decision, and questions without an answer."""
    out = []
    for e in agent._unresolved(child):
        cid = e["payload"]["id"]
        if (ap := agent._find(child, "approval", cid)) is not None and not _decided(agent, child, cid):
            p = ap["payload"]
            out.append({"kind": "approval", "call": cid, "approval_id": p["approval_id"], "tool": p.get("tool"),
                        "risk": p.get("risk"), "arguments": p.get("arguments"),
                        **{k: p[k] for k in ("ask_fields", "schema", "description", "grant_key", "limits", "why") if p.get(k)}})   # the card (3.4)
        elif (q := agent._find(child, "question", cid)) is not None and not _decided(agent, child, cid):
            out.append({"kind": "question", "call": cid, "questions": q["payload"].get("questions")})
    return out


def requests_of(agent: Any, parent: str) -> list[dict[str, Any]]:
    """Every `agent_request` in the parent, with `waiting` (its card still waits), `open` (waiting and not reviewed:
    the parent's model still has to deny or forward it) and `seq`."""
    reviewed = {e["payload"]["id"] for e in agent.store.events(parent, types=("agent_review",))}
    out = []
    for e in agent.store.events(parent, types=("agent_request",)):
        p = e["payload"]
        live = agent.store.thread(p["child"]) is not None and not _decided(agent, p["child"], p["call"])
        out.append({**p, "seq": e["seq"], "waiting": live, "open": p["id"] not in reviewed and live})
    return out


def open_requests(agent: Any, parent: str, child: str | None = None) -> list[dict[str, Any]]:
    return [r for r in requests_of(agent, parent) if r["open"] and (child is None or r["child"] == child)]


def emit(agent: Any, child: str) -> list[dict[str, Any]]:
    """The sub-agent's open cards as `agent_request` events in its parent (each card once). Returns the new ones."""
    t = agent.store.thread(child)
    sp = spawn_of(t)
    parent = str(sp.get("parent") or "")
    if not sp or agent.store.thread(parent) is None:
        return []
    known = {r["call"] for r in requests_of(agent, parent) if r["child"] == child}
    new = []
    for card in open_cards(agent, child):
        if card["call"] in known:
            continue
        req = {"id": new_id("rq_"), "child": child, "label": sp.get("label") or t["title"], **card,
               "in_result": not sp.get("background")}
        agent.emit(parent, "agent_request", req)
        new.append(req)
    return new


def summary(r: dict[str, Any]) -> dict[str, Any]:
    """A request as the parent's tool result lists it."""
    if r["kind"] == "question":
        return {"request": r["id"], "child": r["child"], "label": r["label"], "asks": r.get("questions")}
    return {"request": r["id"], "child": r["child"], "label": r["label"], "tool": r.get("tool"), "risk": r.get("risk"),
            "arguments": r.get("arguments")}


def request_text(p: dict[str, Any]) -> str:
    """How the model reads a background sub-agent's request: from GAIFA; what it wants as untrusted data."""
    what = (f"wants to run {ctx.label(p.get('tool'))} ({p.get('risk')})" if p["kind"] == "approval"
            else "asks a question")
    body = json.dumps({k: v for k, v in summary(p).items() if k in ("arguments", "asks")}, ensure_ascii=False)[:3000]
    return (f"(From GAIFA, not the user: your sub-agent “{ctx.label(p.get('label'))}” {what}. Review it with agent_review "
            f"request {p['id']}: deny (with a reason it reads) or forward (the user decides on a card); you can't approve "
            "it.)\n" + ctx.untrusted(f"sub-agent {p.get('label')} request", body))


async def review(agent: Any, parent: str, rid: str, action: str, reason: str) -> dict[str, Any]:
    """deny or forward one open request (`rid` may be left out when only one is open); raises ValueError."""
    if not rid:
        live = open_requests(agent, parent)
        if len(live) != 1:
            raise ValueError(f"{len(live)} requests are open: name one as `request`")
        rid = live[0]["id"]
    r = next((x for x in requests_of(agent, parent) if x["id"] == rid), None)
    if r is None:
        raise ValueError(f"no request {rid} in this chat")
    if not r["open"]:
        raise ValueError(f"request {rid} is settled already (reviewed, or the user decided its card)")
    if action not in ("deny", "forward"):
        raise ValueError("action is deny or forward: you can't approve a sub-agent's request; forward it and the user decides")
    reason = " ".join(str(reason or "").split())[:500] or ("no reason given" if action == "deny" else "")
    agent.emit(parent, "agent_review", {"id": rid, "child": r["child"], "action": action, "reason": reason,
                                        "kind": r["kind"], **({"approval_id": r["approval_id"]} if r.get("approval_id") else {})})
    if action == "deny":
        why = DENIED_BY_PARENT.format(reason=reason)
        if r["kind"] == "approval":
            await agent.approval(r["child"], r["approval_id"], False, reason=why)
        else:
            await agent.answer(r["child"], r["call"], {"(the chat that started you)": why})
    return {"request": rid, "action": action, **({"note": "the user decides it on a card in this chat"} if action == "forward" else {})}


def forward_read(agent: Any, parent: str, upto: int | None) -> int:
    """At the end of the parent's turn: the open requests its model read (seq ≤ `upto`) are forwarded to the user."""
    n = 0
    for r in open_requests(agent, parent):
        if upto is None or r["seq"] <= upto or r.get("in_result"):
            agent.emit(parent, "agent_review", {"id": r["id"], "child": r["child"], "action": "forward", "kind": r["kind"],
                                                "reason": "the chat that started it didn't review it", "auto": True,
                                                **({"approval_id": r["approval_id"]} if r.get("approval_id") else {})})
            n += 1
    return n
