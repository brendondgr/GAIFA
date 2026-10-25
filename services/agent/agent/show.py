"""`show`: charts, tables and pictures in a reply (plan 47.1).

The model never writes numbers into a chart by hand when it can point at them. Data comes from one of:
- inline: a small set the model worked out (≤ 500 points per series, ≤ 200 rows);
- a file: `source: "#5"` (a CSV or JSON output of this chat) with its columns; the card reads the file itself;
- the hub: `source: "hub:memory" | "hub:outputs_per_day" | "hub:job_times" | "hub:mod_stat"` with a `range`;
- outputs: `outputs: ["#1", "#3"]` for `image` and `gallery`.

Everything is checked before anything shows; an error names the field and the fix, as the hub's tool errors do. The
result is the checked spec (the chat draws it from the event's `data.show`) and, for the model, a one-line summary.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Awaitable, Callable

VIEWS = ("line", "area", "bar", "hbar", "donut", "heatmap", "kpi", "table", "image", "gallery")
CHARTS = ("line", "area", "bar", "hbar")
HUB = ("hub:memory", "hub:outputs_per_day", "hub:job_times", "hub:mod_stat")
RANGES = ("1h", "6h", "24h", "7d", "30d")
POINTS, ROWS, FILE_BYTES, FILE_ROWS, SERIES = 500, 200, 5_000_000, 50_000, 8

TOOL: dict[str, Any] = {
    "name": "show",
    "description": "Show a chart, a table or pictures in your reply, drawn in GAIFA's own style. Use it for numbers worth "
    "comparing (a chart), a list with several fields (a table) or outputs worth seeing together (a gallery). Give the data "
    "one way: inline (small sets you worked out), `source` \"#n\" (a CSV or JSON output: name its columns, never copy its "
    "numbers), `source` \"hub:memory\" | \"hub:outputs_per_day\" | \"hub:job_times\" | \"hub:mod_stat\" with `range` (GAIFA's own "
    "data, always current), or `outputs` [\"#1\", …] for image and gallery. Inline: charts take `x` (labels) and `series` "
    "[{name, values, unit?}]; donut and kpi take `items` [{label, value, unit?}]; table takes `columns` and `rows`; heatmap "
    "takes `rows`, `columns` and `values` (one list per row).",
    "parameters": {"type": "object", "properties": {
        "view": {"type": "string", "enum": list(VIEWS)},
        "title": {"type": "string"}, "caption": {"type": "string"},
        "x": {"description": "Charts: the labels along the axis (inline), or a file's column"},
        "series": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "values": {"type": "array"},
                                                                             "unit": {"type": "string"}}}},
        "y": {"type": "array", "items": {"type": "string"}, "description": "A file's columns to draw as series"},
        "items": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "number"},
                                                                            "unit": {"type": "string"}, "sub": {"type": "string"}}}},
        "columns": {"type": "array", "items": {"type": "string"}}, "rows": {"type": "array"},
        "values": {"type": "array", "description": "Heatmap: one list of numbers per row"},
        "source": {"type": "string", "description": "#n or output:<id> (a CSV or JSON file), or hub:memory, hub:outputs_per_day, hub:job_times, hub:mod_stat"},
        "range": {"type": "string", "enum": list(RANGES), "default": "24h"},
        "mod": {"type": "string", "description": "hub:mod_stat: the mod id"}, "stat": {"type": "string", "description": "hub:mod_stat: the stat's label"},
        "unit": {"type": "string", "description": "The values' unit: bytes, seconds, ratio, or a word"},
        "outputs": {"type": "array", "items": {"type": "string"}, "description": "image and gallery: #n or output:<id>"},
    }, "required": ["view"]},
}


class ShowError(Exception):
    def __init__(self, field: str, detail: str, fix: str):
        super().__init__(detail)
        self.field, self.detail, self.fix = field, detail, fix


def _num(v: Any) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _lists(a: dict[str, Any]) -> dict[str, Any]:
    """Models sometimes send a list as its JSON text (\"[\\\"Mon\\\", …]\"): read those as lists."""
    out = dict(a)
    for k in ("x", "y", "series", "items", "columns", "rows", "values", "outputs"):
        v = out.get(k)
        if isinstance(v, str) and v.strip().startswith("["):
            try:
                out[k] = json.loads(v)
            except ValueError:
                pass
    return out


def _inline(view: str, a: dict[str, Any]) -> dict[str, Any]:
    if view in CHARTS:
        x, series = a.get("x"), a.get("series")
        if not isinstance(x, list) or not x:
            raise ShowError("x", "x needs the labels along the axis, one per point", "give x as a list, e.g. [\"Mon\", \"Tue\"]")
        if len(x) > POINTS:
            raise ShowError("x", f"{len(x)} points; inline charts take {POINTS}", "save the data as a CSV output and pass source \"#n\"")
        if not isinstance(series, list) or not series:
            raise ShowError("series", "series is missing", "give series [{name, values}], one value per x")
        if len(series) > SERIES:
            raise ShowError("series", f"{len(series)} series; a chart takes {SERIES}", "pick the most telling ones")
        for i, s in enumerate(series):
            vals = s.get("values") if isinstance(s, dict) else None
            if not isinstance(vals, list) or len(vals) != len(x):
                raise ShowError(f"series[{i}].values", f"{len(vals) if isinstance(vals, list) else 0} values for {len(x)} x labels",
                                "give one value per x (null for a gap)")
            if not all(_num(v) for v in vals):
                raise ShowError(f"series[{i}].values", "values must be numbers (or null)", "write numbers without units; put the unit in `unit`")
        return {"x": [str(v) for v in x], "series": [{"name": str(s.get("name") or f"Series {i + 1}"), "values": s["values"],
                                                    **({"unit": s["unit"]} if s.get("unit") else {})} for i, s in enumerate(series)]}
    if view in ("donut", "kpi"):
        items = a.get("items")
        if not isinstance(items, list) or not items:
            raise ShowError("items", "items is missing", "give items [{label, value}]")
        if len(items) > (12 if view == "donut" else 6):
            raise ShowError("items", f"{len(items)} items is too many for a {view}", "keep the largest and sum the rest as Other" if view == "donut" else "show up to 6 numbers")
        for i, it in enumerate(items):
            if not isinstance(it, dict) or not isinstance(it.get("label"), str) or not _num(it.get("value")) or it.get("value") is None:
                raise ShowError(f"items[{i}]", "each item needs a label and a number value", "e.g. {\"label\": \"Images\", \"value\": 12}")
        return {"items": items}
    if view == "table":
        cols, rows = a.get("columns"), a.get("rows")
        if not isinstance(cols, list) or not cols or not all(isinstance(c, str) for c in cols):
            raise ShowError("columns", "columns needs the column names", "e.g. [\"Name\", \"Size\"]")
        if not isinstance(rows, list):
            raise ShowError("rows", "rows is missing", "give rows as lists, one value per column")
        if len(rows) > ROWS:
            raise ShowError("rows", f"{len(rows)} rows; inline tables take {ROWS}", "save it as a CSV output and pass source \"#n\"")
        out = []
        for i, r in enumerate(rows):
            if isinstance(r, dict):
                r = [r.get(c) for c in cols]
            if not isinstance(r, list) or len(r) != len(cols):
                raise ShowError(f"rows[{i}]", f"{len(r) if isinstance(r, list) else 0} values for {len(cols)} columns", "give one value per column")
            out.append(r)
        return {"columns": cols, "rows": out}
    if view == "heatmap":
        rows, cols, vals = a.get("rows"), a.get("columns"), a.get("values")
        if not isinstance(rows, list) or not isinstance(cols, list) or not rows or not cols:
            raise ShowError("rows", "a heatmap needs rows and columns (their labels)", "give rows, columns and values")
        if not isinstance(vals, list) or len(vals) != len(rows) or any(not isinstance(v, list) or len(v) != len(cols) or not all(_num(x) for x in v) for v in vals):
            raise ShowError("values", f"values needs {len(rows)} lists of {len(cols)} numbers", "one list per row, one number per column")
        return {"rows": [str(r) for r in rows], "columns": [str(c) for c in cols], "values": vals}
    raise ShowError("view", f"{view} takes outputs", "pass outputs [\"#1\", …]")


def _table(data: bytes, name: str) -> tuple[list[str], list[list[Any]]]:
    """A CSV or JSON file → (columns, rows)."""
    text = data.decode("utf-8-sig", errors="replace")
    if name.lower().endswith(".json") or text.lstrip()[:1] in "[{":
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("columns"), list):
            return [str(c) for c in obj["columns"]], list(obj.get("rows") or [])
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            cols = list(obj[0].keys())
            return cols, [[r.get(c) for c in cols] for r in obj]
        raise ValueError("the JSON isn't a list of objects or {columns, rows}")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("the file is empty")
    return [c.strip() for c in rows[0]], rows[1:]


def _number(v: Any) -> bool:
    if v is None or v == "":
        return True
    if isinstance(v, (int, float)):
        return True
    return bool(re.fullmatch(r"\s*-?[\d,]*\.?\d+(e-?\d+)?\s*%?", str(v)))


async def check(args: dict[str, Any], resolve: Callable[[str], str | None],
                read: Callable[[str], Awaitable[tuple[bytes, dict[str, Any]]]]) -> dict[str, Any]:
    """The checked spec, or ShowError naming the field and the fix."""
    args = _lists(args)
    view = args.get("view")
    if view not in VIEWS:
        raise ShowError("view", f"{view!r} isn't a view", "one of " + ", ".join(VIEWS))
    spec: dict[str, Any] = {"view": view}
    for k in ("title", "caption", "unit"):
        if isinstance(args.get(k), str) and args[k].strip():
            spec[k] = args[k].strip()[:200]
    if view in ("image", "gallery"):
        refs = args.get("outputs")
        if not isinstance(refs, list) or not refs:
            raise ShowError("outputs", f"{view} needs outputs", "pass outputs [\"#1\", …] from this chat")
        if view == "image" and len(refs) > 1:
            raise ShowError("outputs", "image shows one output", "use gallery for several")
        ids = []
        for i, r in enumerate(refs[:24]):
            oid = resolve(str(r))
            if not oid:
                raise ShowError(f"outputs[{i}]", f"{r!r} isn't an output in this chat", "use #n from the outputs table, or output:<id>")
            ids.append(oid)
        spec["outputs"] = ids
        return spec
    src = args.get("source")
    if isinstance(src, str) and src.startswith("hub:"):
        if src not in HUB:
            raise ShowError("source", f"{src!r} isn't one of GAIFA's sources", "one of " + ", ".join(HUB))
        rng = args.get("range") or "24h"
        if rng not in RANGES:
            raise ShowError("range", f"{rng!r} isn't a range", "one of " + ", ".join(RANGES))
        hub: dict[str, Any] = {"name": src[4:], "range": rng}
        if src == "hub:mod_stat":
            if not args.get("mod") or not args.get("stat"):
                raise ShowError("mod", "hub:mod_stat needs mod and stat", "e.g. mod \"comfy\", stat \"Made today\"")
            hub.update(mod=str(args["mod"]), stat=str(args["stat"]))
        spec["hub"] = hub
        return spec
    if isinstance(src, str) and src:
        oid = resolve(src)
        if not oid:
            raise ShowError("source", f"{src!r} isn't an output in this chat", "use #n of a CSV or JSON output, or output:<id>")
        data, meta = await read(oid)
        if len(data) > FILE_BYTES:
            raise ShowError("source", f"the file is {len(data) // 1_000_000} MB; show takes 5 MB", "summarize it into a smaller CSV first")
        try:
            cols, rows = _table(data, meta.get("name") or "")
        except (ValueError, json.JSONDecodeError) as e:
            raise ShowError("source", f"{src} isn't a table: {e}", "pass a CSV (a header row) or a JSON list of objects") from None
        if len(rows) > FILE_ROWS:
            raise ShowError("source", f"{len(rows)} rows; show takes {FILE_ROWS}", "summarize it first")
        want = ([args["x"]] if isinstance(args.get("x"), str) else []) + list(args.get("y") or []) + (list(args.get("columns") or []) if view == "table" else [])
        missing = [c for c in want if c not in cols]
        if missing:
            raise ShowError("columns" if view == "table" else "y", f"no column {', '.join(map(repr, missing))} in {src}", "its columns: " + ", ".join(cols[:30]))
        file: dict[str, Any] = {"output_id": oid, "rows": len(rows), "columns": cols}
        if view in CHARTS or view in ("donut", "kpi"):
            if not isinstance(args.get("x"), str) or not args.get("y"):
                raise ShowError("x", "a chart from a file needs x (a column) and y (columns)", "its columns: " + ", ".join(cols[:30]))
            for c in args["y"]:
                j = cols.index(c)
                if not all(_number(r[j] if j < len(r) else None) for r in rows[:200]):
                    raise ShowError("y", f"column {c!r} isn't numbers", "pick numeric columns for y")
            file.update(x=args["x"], y=list(args["y"]))
        elif view == "table":
            file["show"] = list(args.get("columns") or cols)
        else:
            raise ShowError("view", f"{view} can't come from a file", "use inline values")
        spec["file"] = file
        return spec
    spec["data"] = _inline(view, args)
    return spec


def summary(spec: dict[str, Any]) -> str:
    v = spec["view"]
    if "outputs" in spec:
        n = len(spec["outputs"])
        return "Shown: a picture." if v == "image" else f"Shown: a gallery of {n}."
    if "hub" in spec:
        return f"Shown: a {v} of GAIFA's {spec['hub']['name'].replace('_', ' ')} over {spec['hub']['range']}, kept current."
    if "file" in spec:
        f = spec["file"]
        return f"Shown: a {v} from a file of {f['rows']} rows" + (f" ({', '.join(f.get('y') or [])} by {f['x']})." if f.get("x") else ".")
    d = spec["data"]
    if v in CHARTS:
        return f"Shown: a {v} chart of {len(d['series'])} series, {len(d['x'])} points."
    if v == "table":
        return f"Shown: a table of {len(d['rows'])} rows."
    return f"Shown: a {v}."
