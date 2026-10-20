"""The miner (plan 21.5): preferences inferred from what the user does, with no model call.

Evidence, read over HTTP and from this mod's own log (eval dry runs and chats that opted out are
never used):
- **card edits**: approved approvals whose `edited` fields the user changed (chat and MCP clients);
- **question answers**: the same question answered the same way;
- **thumbs**: ratings of outputs, counted for the workflow, engine and preset that made them.

A value the user picked `infer_after` times (2) in as many chats, with nothing against it, becomes an
`inferred`, `proposed` preference (the hub derives where it applies from the tool's choices). The
user approves it. Inferred preferences unused for `fade_days` fade out; stated ones never do.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any

log = logging.getLogger("agent.learn")
DAY = 86400
RATED = ("workflow", "engine", "preset")


def _chat(origin: dict[str, Any]) -> str | None:
    if origin.get("dry_run") or origin.get("no_learn"):
        return None
    if origin.get("thread"):
        return "thread:" + str(origin["thread"])
    if origin.get("service") == "mcp":
        return "mcp:" + str(origin.get("client") or "?")
    return None


def _key(v: Any) -> str:
    import json
    return json.dumps(v, sort_keys=True, default=str)


def card_edits(approvals: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """(tool, field, value) → {value, chats, approvals, against}: what the user set on cards."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    picks: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)    # (tool, field) → [(value key, chat)]
    for a in approvals:
        if a.get("state") != "approved" or not a.get("edited"):
            continue
        chat = _chat(a.get("origin") or {})
        if chat is None:
            continue
        final = a.get("final") or {}
        for f in a["edited"]:
            if f not in final:
                continue
            k = (a["tool"], f, _key(final[f]))
            row = out.setdefault(k, {"tool": a["tool"], "field": f, "value": final[f], "chats": set(), "approvals": [], "against": 0})
            row["chats"].add(chat)
            row["approvals"].append(a["id"])
            picks[(a["tool"], f)].append((k[2], chat))
    for k, row in out.items():
        row["against"] = sum(1 for v, _ in picks[(k[0], k[1])] if v != k[2])
    return out


def _norm_q(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", q.lower()).strip()[:120]


def answers(events: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(question, answer) → {question, answer, chats}: the user's picks on question cards."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    by_q: dict[str, list[str]] = defaultdict(list)
    for e in events:
        if e["type"] != "answer":
            continue
        for q, a in ((e["payload"] or {}).get("answers") or {}).items():
            if not isinstance(a, str) or not q.strip():
                continue
            k = (_norm_q(q), a.strip().lower())
            row = out.setdefault(k, {"question": q.strip(), "answer": a.strip(), "chats": set(), "against": 0})
            row["chats"].add(e["thread_id"])
            by_q[k[0]].append(k[1])
    for (q, a), row in out.items():
        row["against"] = sum(1 for x in by_q[q] if x != a)
    return out


def thumbs(events: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """(tool, field, value) → {up, down, chats}: ratings of outputs, by what made them."""
    made: dict[str, tuple[str, dict[str, Any]]] = {}             # output id → (tool, arguments)
    calls: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    latest: dict[str, tuple[str, str]] = {}                       # output id → (rating, chat): the newest counts
    for e in events:
        p = e["payload"] or {}
        if e["type"] == "tool_call":
            calls[(e["thread_id"], p.get("id"))] = (p.get("name"), p.get("arguments") or {})
        elif e["type"] == "decision" and p.get("approve") and p.get("arguments"):
            c = calls.get((e["thread_id"], p.get("id")))
            if c:
                calls[(e["thread_id"], p.get("id"))] = (c[0], p["arguments"])
        elif e["type"] == "tool_result" and p.get("outputs"):
            c = calls.get((e["thread_id"], p.get("id")))
            for o in p["outputs"]:
                if c:
                    made[o["output_id"]] = c
        elif e["type"] == "feedback" and p.get("output_id"):
            latest[p["output_id"]] = (p.get("value"), e["thread_id"])
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for oid, (value, chat) in latest.items():
        if oid not in made:
            continue
        tool, args = made[oid]
        for f in RATED:
            if f in args:
                row = out.setdefault((tool, f, _key(args[f])), {"tool": tool, "field": f, "value": args[f], "up": 0, "down": 0, "chats": set()})
                row["up" if value == "up" else "down"] += 1
                row["chats"].add(chat)
    return out


async def run(hub: Any, store: Any, now: float | None = None) -> dict[str, Any]:
    """One pass: propose what crossed the threshold, fade what went unused. Returns what it did."""
    now = now or time.time()
    try:
        learning = (await hub.settings()).get("learning") or {}
    except Exception:  # noqa: BLE001
        learning = {}
    if not learning.get("enabled", True):
        return {"off": True}
    n, fade = int(learning.get("infer_after") or 2), int(learning.get("fade_days") or 60)
    existing = await hub.prefs()
    known = {(p.get("tool"), p.get("field"), _key(p.get("value"))) for p in existing if p["scope"] == "tool"}
    known_text = {str(p.get("value")) for p in existing if p["scope"] == "agent"}
    done: dict[str, list[Any]] = {"proposed": [], "faded": []}

    async def propose(body: dict[str, Any]) -> None:
        try:
            p = await hub.create_pref({"source": "inferred", "state": "proposed", **body})
            done["proposed"].append(p)
        except Exception as e:  # noqa: BLE001: a value that no longer fits the tool is skipped
            log.info("not proposed (%s): %s", body.get("field") or body.get("value"), e)

    for k, row in card_edits(await hub.approvals("approved")).items():
        if k in known or len(row["chats"]) < n or len(row["approvals"]) < n or row["against"] * 2 >= len(row["approvals"]):
            continue
        await propose({"tool": row["tool"], "field": row["field"], "value": row["value"], "seen": len(row["approvals"]),
                       "cue": f"you set this on {len(row['approvals'])} cards in {len(row['chats'])} chats",
                       "confidence": round(len(row["approvals"]) / (len(row["approvals"]) + row["against"]), 2),
                       "evidence": [{"kind": "approval", "ref": a} for a in row["approvals"][-10:]]})
    evs = store.events_by_type(["answer", "tool_call", "tool_result", "decision", "feedback"])
    for row in answers(evs).values():
        text = f"When asked \"{row['question']}\", the user answers \"{row['answer']}\": use that without asking."
        if text in known_text or len(row["chats"]) < n or row["against"]:
            continue
        await propose({"value": text, "seen": len(row["chats"]), "cue": "a question card answered the same way",
                       "evidence": [{"kind": "thread", "ref": t} for t in sorted(row["chats"])[:10]]})
    for k, row in thumbs(evs).items():
        if len(row["chats"]) < n:
            continue
        if row["up"] >= n and not row["down"] and k not in known:
            await propose({"tool": row["tool"], "field": row["field"], "value": row["value"], "seen": row["up"],
                           "cue": f"you liked {row['up']} results made this way",
                           "evidence": [{"kind": "feedback", "ref": c} for c in sorted(row["chats"])[:10]]})
        elif row["down"] >= n and not row["up"]:
            text = f"The user disliked {row['down']} results of {row['tool']} with {row['field']}={row['value']}: prefer another."
            if text not in known_text:
                await propose({"value": text, "seen": row["down"], "cue": "thumbs down",
                               "evidence": [{"kind": "feedback", "ref": c} for c in sorted(row["chats"])[:10]]})
    for p in existing:
        last = p.get("last_used_ts") or p.get("updated_ts") or p.get("created_ts") or now
        if p.get("source") == "inferred" and p.get("state") == "active" and now - last > fade * DAY:
            try:
                done["faded"].append(await hub.update_pref(p["id"], {"state": "retired", "note": f"unused for {fade} days"}))
            except Exception:  # noqa: BLE001
                pass
    return done
