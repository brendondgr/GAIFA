"""A save merged with what is saved now (plan settings-that-stick 2.1).

A writer (the Settings page, a chat's "Always allow", another tab) loads the settings, changes some keys and
sends them with `base`: what each changed key held when it loaded. Something else may have saved since. For each
key the writer sent, against `current` (what is saved now):

- nobody else changed it (`current == base`), or both made the same change: the writer's value;
- a list: the current list, without what the writer removed, plus what it added (in the writer's order);
- a table (`services.enabled`, `ui.nav`, …): the same, entry by entry;
- a plain value both changed differently: a conflict (`409 settings_conflict`), the caller decides.

A key sent without a `base` replaces what is saved, as before (the CLI, older pages).
"""

from __future__ import annotations

import json
from typing import Any

MISSING = object()


class Conflict(Exception):
    def __init__(self, field: str, current: Any, yours: Any) -> None:
        super().__init__(field)
        self.field, self.current, self.yours = field, current, yours


def _key(v: Any) -> str:
    return json.dumps(v, sort_keys=True)


def merge_list(current: list[Any], base: list[Any], mine: list[Any]) -> list[Any]:
    base_k, mine_k = {_key(x) for x in base}, {_key(x) for x in mine}
    removed = base_k - mine_k
    out = [x for x in current if _key(x) not in removed]
    have = {_key(x) for x in out}
    for x in mine:
        if _key(x) not in base_k and _key(x) not in have:
            out.append(x)
            have.add(_key(x))
    return out


def merge_value(field: str, current: Any, base: Any, mine: Any) -> Any:
    if current == base or current == mine or base == mine:
        return mine if base != mine else current
    if isinstance(current, list) and isinstance(base, list) and isinstance(mine, list):
        return merge_list(current, base, mine)
    if isinstance(current, dict) and isinstance(base, dict) and isinstance(mine, dict):
        out = dict(current)
        for k in {*base, *mine}:
            b, m = base.get(k, MISSING), mine.get(k, MISSING)
            if b == m:
                continue      # the writer didn't change this entry: keep what is saved
            c = current.get(k, MISSING)
            if m is MISSING:
                out.pop(k, None)
            elif b is MISSING or c is MISSING:
                out[k] = m
            else:
                out[k] = merge_value(f"{field}.{k}", c, b, m)
        return out
    raise Conflict(field, current, mine)


def rebase(current: dict[str, Any], patch: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    """`patch` with every key that has a `base` merged against `current` (the `Settings` shape: section → key → value)."""
    if not base:
        return patch
    out: dict[str, Any] = {}
    for section, values in patch.items():
        bsec = base.get(section) if isinstance(base.get(section), dict) else None
        if not isinstance(values, dict) or bsec is None:
            out[section] = values
            continue
        cur = current.get(section) or {}
        out[section] = {k: (merge_value(f"{section}.{k}", cur.get(k), bsec[k], v) if k in bsec and k in cur else v)
                        for k, v in values.items()}
    return out
