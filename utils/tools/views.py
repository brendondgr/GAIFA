"""A tool's default view (plan 46.1): how its result draws in Chat when no card is registered for it.

    view = { kind = "table", rows = "jobs", columns = [{ key = "title", label = "Job" }, { key = "request.engine", label = "Engine" },
             { key = "status", label = "State" }, { key = "created", label = "Made", format = "time" }] }
    view = { kind = "bar", rows = "models", x = "name", y = ["size_bytes"], unit = "bytes" }

`rows` is the path (dotted) to the list in the result ("" for a result that is itself the list); a column `key` may be
dotted too; `format` is time, bytes, seconds, gb, list or yesno. Chart kinds take `x` (a key) and `y` (keys) and use
`show`'s views and chart components (chat-show.js).
"""

from __future__ import annotations

import re
from typing import Any

KINDS = ("table", "bar", "hbar", "line", "area", "donut")
FORMATS = ("time", "bytes", "seconds", "gb", "list", "yesno")
KEY = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$")


def check(view: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """A declared view → (the cleaned view, problems). None and no problems when there is none."""
    if view is None:
        return None, []
    if not isinstance(view, dict):
        return None, ["view must be a table {kind, rows, columns} or a chart {kind, rows, x, y}"]
    problems: list[str] = []
    kind = view.get("kind")
    if kind not in KINDS:
        return None, [f"view.kind {kind!r} isn't one of {', '.join(KINDS)}"]
    rows = view.get("rows", "")
    if not isinstance(rows, str) or (rows and not KEY.match(rows)):
        problems.append("view.rows must be a dotted path to the list in the result (\"\" for the result itself)")
    out: dict[str, Any] = {"kind": kind, "rows": rows if isinstance(rows, str) else ""}
    if kind == "table":
        cols = []
        for i, c in enumerate(view.get("columns") or []):
            c = {"key": c} if isinstance(c, str) else c
            if not isinstance(c, dict) or not isinstance(c.get("key"), str) or not KEY.match(c["key"]):
                problems.append(f"view.columns[{i}] needs a key (a dotted path in a row)")
                continue
            if c.get("format") is not None and c["format"] not in FORMATS:
                problems.append(f"view.columns[{i}].format {c['format']!r} isn't one of {', '.join(FORMATS)}")
            cols.append({"key": c["key"], "label": str(c.get("label") or c["key"]), **({"format": c["format"]} if c.get("format") in FORMATS else {})})
        if cols:
            out["columns"] = cols[:12]
    else:
        x, y = view.get("x"), view.get("y")
        if not isinstance(x, str) or not KEY.match(x):
            problems.append("a chart view needs x: the key of each row's label")
        if not isinstance(y, list) or not y or not all(isinstance(k, str) and KEY.match(k) for k in y):
            problems.append("a chart view needs y: the keys of the numbers to draw")
        out.update(x=x, y=y)
        if isinstance(view.get("unit"), str):
            out["unit"] = view["unit"]
    if isinstance(view.get("title"), str):
        out["title"] = view["title"][:80]
    return (None if problems else out), problems
