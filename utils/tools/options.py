"""Per-choice capabilities on enum parameters (plan 20.1): `x-options`.

Any tool may put `x-options` on an `enum` property, one entry per allowed value:

    "engine": {"type": "string", "enum": ["cube3d", "trellis2"], "x-options": {
        "cube3d":   {"label": "Cube3D", "needs": ["prompt"], "excludes": ["image"], "default": true, "good_for": "…"},
        "trellis2": {"label": "TRELLIS.2", "needs": ["image"], "default": true, "allows": {"preset": ["base", "fast"]}}}}

- `needs`: parameters that must be given for this choice; `excludes`: ones that must not be.
- `default`: used when the parameter is left out, among the choices that fit the other arguments.
- `allows`: for a parameter that says `"x-depends-on": "<this one>"`, its valid values with this choice.
- Shown, not checked: `label`, `good_for`, `speed`, `kind` (e.g. an edit style), `quality` and `when`
  (on a dependent parameter's own options, e.g. a preset that is only for quick drafts).

The hub fills defaults and refuses choices that don't fit before a card is made (`calls.py`), the
model reads the choices as text (`for_model`), and the card and the MCP form list only those that fit.
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

KEY = "x-options"
DEPENDS = "x-depends-on"


def present(args: dict[str, Any], name: str) -> bool:
    v = args.get(name)
    return v is not None and v != "" and v != [] and v != {}


def options(p: Any) -> dict[str, dict[str, Any]] | None:
    o = p.get(KEY) if isinstance(p, dict) else None
    return o if isinstance(o, dict) and o else None


def fits(opt: dict[str, Any], args: dict[str, Any]) -> bool:
    return all(present(args, n) for n in opt.get("needs") or []) and not any(present(args, n) for n in opt.get("excludes") or [])


def choices(params: dict[str, Any], name: str, args: dict[str, Any]) -> list[Any]:
    """The values of `name` that fit `args` (all of its enum when it has no `x-options`)."""
    p = (params.get("properties") or {}).get(name) or {}
    enum = list(p.get("enum") or [])
    o = options(p)
    if o:
        enum = [v for v in enum if fits(o.get(str(v)) or {}, args)]
    dep = p.get(DEPENDS)
    if dep:
        allowed = _allowed(params, name, args)
        if allowed is not None:
            enum = [v for v in enum if v in allowed]
    return enum


def _allowed(params: dict[str, Any], name: str, args: dict[str, Any]) -> list[Any] | None:
    props = params.get("properties") or {}
    dep = (props.get(name) or {}).get(DEPENDS)
    po = options(props.get(dep)) if dep else None
    parent = args.get(dep) if dep else None
    opt = po.get(str(parent)) if po and parent is not None else None
    allows = opt.get("allows") if isinstance(opt, dict) else None
    return list(allows[name]) if isinstance(allows, dict) and isinstance(allows.get(name), list) else None


def fill_defaults(params: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """`args` with each absent `x-options` parameter set to the default that fits; and which were set."""
    out, filled = dict(args), []
    for k, p in (params.get("properties") or {}).items():
        o = options(p)
        if not o or present(out, k):
            continue
        pick = next((v for v, opt in o.items() if isinstance(opt, dict) and opt.get("default") and fits(opt, out)), None)
        if pick is not None:
            enum = p.get("enum") or []
            out[k] = next((e for e in enum if str(e) == pick), pick)
            filled.append(k)
    return out, filled


def _name(v: Any, opt: dict[str, Any]) -> str:
    return f"{v} ({opt['label']})" if opt.get("label") and opt["label"] != v else str(v)


def _ticks(names: list[str]) -> str:
    return ", ".join(f"`{n}`" for n in names)


def problems(params: dict[str, Any], args: dict[str, Any]) -> list[dict[str, str]]:
    """Choices that don't fit the other arguments, each `{field, detail, fix}`."""
    out: list[dict[str, str]] = []
    props = params.get("properties") or {}
    for k, p in props.items():
        o = options(p)
        v = args.get(k)
        if o and present(args, k) and str(v) in o:
            opt = o[str(v)]
            missing = [n for n in opt.get("needs") or [] if not present(args, n)]
            extra = [n for n in opt.get("excludes") or [] if present(args, n)]
            if missing or extra:
                why = []
                if missing:
                    why.append(f"needs {_ticks(missing)}")
                if extra:
                    why.append(f"can't use {_ticks(extra)}")
                ok = [x for x, xo in o.items() if isinstance(xo, dict) and fits(xo, args)]
                if ok:
                    fix = f"with these inputs, use {k} " + " or ".join(
                        _name(x, o[x]) + (f": {o[x]['good_for']}" if o[x].get("good_for") else "") for x in ok)
                    if missing:
                        fix += f"; or add {_ticks(missing)} to keep {v}"
                else:
                    fix = f"add {_ticks(missing)}" if missing else f"leave out {_ticks(extra)}"
                out.append({"field": k, "detail": f"{k} {_name(v, opt)} {' and '.join(why)}", "fix": fix})
        if p.get(DEPENDS) and present(args, k):
            allowed = _allowed(params, k, args)
            if allowed is not None and v not in allowed:
                dep = p[DEPENDS]
                out.append({"field": k, "detail": f"{dep} {args.get(dep)} has no {k} {v!r}",
                            "fix": f"use one of: {', '.join(map(str, allowed))}" if allowed else f"leave out {k}"})
    return out


def _option_line(v: Any, opt: dict[str, Any]) -> str:
    bits = [str(opt["good_for"])] if opt.get("good_for") else []
    if opt.get("kind"):
        bits.append(str(opt["kind"]))
    if opt.get("speed"):
        bits.append(str(opt["speed"]))
    if opt.get("needs"):
        bits.append(f"needs {_ticks(list(opt['needs']))}")
    if opt.get("excludes"):
        bits.append(f"not with {_ticks(list(opt['excludes']))}")
    if opt.get("quality"):
        bits.append(f"{opt['quality']} quality")
    if opt.get("when"):
        bits.append(str(opt["when"]))
    for dep, vals in (opt.get("allows") or {}).items():
        bits.append(f"{dep}: {', '.join(map(str, vals)) if vals else 'none'}")
    if opt.get("default"):
        cond = [f"with {_ticks(list(opt['needs']))}"] if opt.get("needs") else []
        cond += [f"without {_ticks(list(opt['excludes']))}"] if opt.get("excludes") else []
        bits.append("the default" + (" " + " and ".join(cond) if cond else ""))
    return f"- {_name(v, opt)}" + (": " + "; ".join(bits) if bits else "")


def for_model(params: dict[str, Any]) -> dict[str, Any]:
    """The schema the model reads: each parameter's `x-options` as lines in its description."""
    out = copy.deepcopy(params)
    for k, p in (out.get("properties") or {}).items():
        if not isinstance(p, dict):
            continue
        o = options(p)
        lines = []
        if o:
            lines = [_option_line(v, o.get(str(v)) or {}) for v in p.get("enum") or o]
            p.pop(KEY, None)
        if p.get(DEPENDS):
            lines.insert(0, f"(Which values are allowed depends on `{p.pop(DEPENDS)}`.)")
        if lines:
            p["description"] = ((p.get("description") or "").rstrip() + "\n" + "\n".join(lines)).strip()
    return out


def spec_problems(params: dict[str, Any]) -> list[str]:
    """Mistakes in a tool's `x-options` (for `aihub check`): unknown values, unknown parameters, and
    more than one default fitting the same inputs."""
    out: list[str] = []
    props = params.get("properties") or {}
    for k, p in props.items():
        o = options(p)
        if not o:
            if isinstance(p, dict) and p.get(DEPENDS) and not options(props.get(p[DEPENDS])):
                out.append(f"{k}: {DEPENDS} {p[DEPENDS]!r} has no {KEY}")
            continue
        enum = [str(e) for e in p.get("enum") or []]
        out += [f"{k}: {KEY} has {v!r}, which isn't in its enum" for v in o if v not in enum]
        fields = sorted({n for opt in o.values() if isinstance(opt, dict) for n in [*(opt.get("needs") or []), *(opt.get("excludes") or [])]})
        out += [f"{k}: {KEY} names {n!r}, which isn't a parameter" for n in fields if n not in props]
        defaults = {v: opt for v, opt in o.items() if isinstance(opt, dict) and opt.get("default")}
        for combo in itertools.product((False, True), repeat=min(len(fields), 8)):
            args = {f: "x" for f, on in zip(fields, combo) if on}
            hits = [v for v, opt in defaults.items() if fits(opt, args)]
            if len(hits) > 1:
                given = ", ".join(f for f in fields if f in args) or "nothing else"
                out.append(f"{k}: {len(hits)} defaults ({', '.join(hits)}) fit when {given} is given")
                break
    return out
