"""The calendar's preflight (calendar plan 4.1; `[agent] limits = "POST /v1/limits"`): what one of the agent's
calendar calls would do, for the hub's mode × action table.

- reads and proposals (which add nothing) are `read`;
- adding, changing and completing an item, and deleting one somebody else made, are `change`: they run in Auto only
  when the judge finds you asked for them, and ask in Manual and Accept edits;
- changing or deleting an item the agent made in this same chat, which nobody changed since (a test it made), is
  `edit`: it runs in Accept edits, Auto and Bypass;
- an item that isn't there is refused (`not_found`).
`allow_bypass` is always true: Bypass may change the calendar. There's no grant key: "Allow in this chat" covers
every call of that tool in the chat.
"""

from __future__ import annotations

from typing import Any

import repeat as R
import timeutil as T
import when as W
from store import NotFound

READS = {"agenda", "search", "when", "free", "propose", "plan_day"}
OWN = {"update", "delete"}


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


def preflight(store: Any, settings: dict[str, Any], tool: str, args: dict[str, Any], origin: dict[str, Any]) -> dict[str, Any]:
    if tool in READS:
        return {"action": "read", "allow_bypass": True}
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
