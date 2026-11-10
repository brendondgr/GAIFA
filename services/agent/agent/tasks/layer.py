"""The Calendar's layer of scheduled tasks (plan calendar 6.4): each task's due times in a range (from its schedule;
a task before a calendar event is marked on the event itself, so it has none here) and its runs there."""

from __future__ import annotations

from typing import Any

from . import when

MAX_PER_TASK = 200


def due_times(schedule: dict[str, Any], frm: float, to: float) -> list[float]:
    out: list[float] = []
    t = frm - 1
    while len(out) < MAX_PER_TASK:
        nxt = when.next_due(schedule, t)
        if nxt is None or nxt >= to:
            break
        out.append(nxt)
        t = nxt
    return out


def calendar_layer(store: Any, frm: float, to: float) -> list[dict[str, Any]]:
    out = []
    for t in store.list():
        runs = [r for r in store.runs(t["id"], limit=MAX_PER_TASK, before=to) if r["due"] >= frm]
        due = due_times(t["schedule"], max(frm, store.clock()), to) if t["enabled"] else []
        if not due and not runs:
            continue
        out.append({"id": t["id"], "name": t["name"], "when": t.get("when"), "enabled": t["enabled"], "project_id": t.get("project_id"),
                    "due": due, "runs": [{"id": r["id"], "due": r["due"], "state": r["state"], "seen": r["seen"], "thread_id": r["thread_id"],
                                          "late": r["late"], "test": r["test"], "refused": r["refused"]} for r in runs]})
    return out
