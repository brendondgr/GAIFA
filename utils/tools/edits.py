"""Which arguments the user really changed on a parameter card (plan 21.1).

The card sends every checkbox and the folded "All settings" form, so a plain diff of the model's
arguments against the ones that ran marks fields the user never touched. A field counts as edited
only when its value differs after `false`, empty and absent are each read as the schema's default.
"""

from __future__ import annotations

from typing import Any

_EMPTY = (None, "", [], {})


def _norm(p: dict[str, Any], v: Any) -> Any:
    if isinstance(v, dict) and set(v) == {"$file"}:
        v = v["$file"]
    if isinstance(v, str) and v.startswith("output:"):
        return v
    default = p.get("default") if isinstance(p, dict) else None
    if v in _EMPTY or (v is False and default in (None, False)):
        return default if default not in _EMPTY else None
    return v


def edited(schema: dict[str, Any], proposed: dict[str, Any] | None, final: dict[str, Any] | None) -> list[str]:
    props = (schema or {}).get("properties") or {}
    a, b = proposed or {}, final or {}
    out = []
    for k in sorted(set(a) | set(b)):
        p = props.get(k) or {}
        if _norm(p, a.get(k)) != _norm(p, b.get(k)):
            out.append(k)
    return out
