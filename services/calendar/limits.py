"""The calendar's preflight (calendar plan 4.1; `[agent] limits = "POST /v1/limits"`): what one of the agent's
calendar calls would do, for the hub's mode × action table.

- reads and proposals (which add nothing) are `read`;
- adding, changing and completing an item, and deleting one somebody else made, are `change`: they run in Auto only
  when the judge finds you asked for them, and ask in Manual and Accept edits;
- changing or deleting an item the agent made in this same chat, which nobody changed since (a test it made), is
  `edit`: it runs in Accept edits, Auto and Bypass;
- an item that isn't there is refused (`not_found`);
- a fourth different `add` from one chat within two minutes is refused (`use_propose`): many items at once are a
  proposal the user ticks, not a card each (plan 4.2's rule, which a small model may skip). The same add checked
  again (the hub's re-check when you approve its card) isn't counted twice.
`allow_bypass` is always true: Bypass may change the calendar. There's no grant key: "Allow in this chat" covers
every call of that tool in the chat.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import repeat as R
import timeutil as T
import when as W
from store import NotFound

READS = {"agenda", "search", "when", "free", "propose", "plan_day"}
OWN = {"update", "delete"}
BURST_N, BURST_S = 3, 120.0


class Burst:
    """The adds each chat sent lately: {thread: {arguments as JSON: when}}. On `app.state.cal.burst`."""

    def __init__(self) -> None:
        self.seen: dict[str, dict[str, float]] = {}
        self.lock = threading.Lock()

    def over(self, thread: str, args: dict[str, Any], now: float | None = None) -> bool:
        """Counts this add; true when it is past the limit (it isn't counted then, so a proposal of the rest is clean)."""
        now = time.time() if now is None else now
        key = json.dumps(args, sort_keys=True, default=str)
        with self.lock:
            for t in [t for t, d in self.seen.items() if all(now - w > BURST_S for w in d.values())]:
                del self.seen[t]
            mine = {k: w for k, w in self.seen.get(thread, {}).items() if now - w <= BURST_S}
            if key not in mine and len(mine) >= BURST_N:
                self.seen[thread] = mine
                return True
            mine[key] = mine.get(key, now)
            self.seen[thread] = mine
            return False


def _summary(store: Any, settings: dict[str, Any], tool: str, args: dict[str, Any], item: dict[str, Any] | None) -> str:
    title = (args.get("title") or (item or {}).get("title") or "").strip()
    if tool == "add":
        when = str(args.get("when") or args.get("start") or args.get("due") or "")
        try:
            if args.get("when"):
                p = W.parse(str(args["when"]), T.now_local(), kind=args.get("kind") or "event", date_order=settings["date_order"], whole=True)
                when = p.get("start") or p.get("due") or when
                when = when.replace("T", " ")
        except W.Unreadable:
            pass
        return f"adds “{title}”" + (f" · {when}" if when else "") + (f" · {args['repeat']}" if args.get("repeat") else "")
    if tool == "update":
        what = ", ".join(k for k in ("title", "when", "start", "end", "due", "repeat", "rrule", "location", "notes", "calendar", "alerts")
                         if args.get(k) is not None)
        scope = args.get("scope") or "all"
        return f"changes “{title}”" + (f" ({what})" if what else "") + ("" if not (item or {}).get("rrule") else f" · {scope}")
    if tool == "done":
        return f"marks “{title}” {'not ' if args.get('undone') else ''}done"
    if tool == "delete":
        return f"deletes “{title}”" + (" (one occurrence)" if args.get("scope") == "this" else "") + " · to the trash"
    return tool


def preflight(store: Any, settings: dict[str, Any], tool: str, args: dict[str, Any], origin: dict[str, Any],
              burst: Burst | None = None) -> dict[str, Any]:
    if tool in READS:
        return {"action": "read", "allow_bypass": True}
    if tool == "add" and burst is not None and origin.get("thread") and burst.over(str(origin["thread"]), args):
        return {"action": "change", "refuse": {
            "code": "use_propose", "detail": f"more than {BURST_N} calendar items at once go to the user as one proposal, not a card each",
            "fix": "don't retry calendar_add; put this item and the others you haven't added yet in one calendar_propose call "
                   "(the earlier adds already went to the user)"}}
    item = None
    iid = args.get("id") or args.get("iid")
    if tool in ("update", "done", "delete"):
        try:
            item = store.get(str(iid or ""))
        except NotFound:
            return {"action": "change", "refuse": {"code": "not_found", "detail": f"there's no calendar item {iid!r}",
                                                   "fix": "find it with calendar_search or calendar_agenda and use its id"}}
    src = (item or {}).get("source") or {}
    own = (tool in OWN and item is not None and item.get("touched_by") == "agent" and src.get("kind") == "agent"
           and src.get("thread") and src.get("thread") == origin.get("thread"))
    out: dict[str, Any] = {"action": "edit" if own else "change", "allow_bypass": True,
                           "preview": {"what": "changes your calendar" if not own else "changes an item it made in this chat",
                                       "summary": _summary(store, settings, tool, args, item)}}
    if item is not None and item.get("rrule"):
        out["preview"]["repeat"] = R.describe(item["rrule"], R.anchor_of(item))
    return out
