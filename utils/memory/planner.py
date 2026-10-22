"""The load rule (architecture §7, plan 5.3): does a mod fit, and if not, which idle mods
to unload. Pure: it gets numbers and returns the brief's `MakeRoomPlan`.

- `available` = MemAvailable − reserve − what other loads have reserved but not used yet.
- `needs` = the bytes asked for, else max(estimate, learned peak).
- **Candidates:** other mods that are loaded, may be auto-unloaded, aren't in
  `never_unload`, aren't busy, have no proxied request in flight, and have an `unload`
  operation. **Order:** priority (lowest first), then longest idle.
- Candidates are added until the gap is covered; each frees what it uses now (or its
  estimate, if it isn't measured yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GB = 1000**3  # decimal GB, as the UI shows it (and config, manifests and status use)


@dataclass
class Candidate:
    id: str
    name: str
    load: str
    up: bool
    busy: bool
    in_flight: int
    auto_unload: bool
    unloadable: bool
    priority: int
    idle_s: float | None
    used_bytes: int
    estimate_bytes: int | None


def fmt_gb(n: float) -> str:
    return f"{n / GB:.1f} GB"


def fmt_idle(s: float | None) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h {s % 3600 // 60}m"


def why_not(c: Candidate, target: str, never: set[str]) -> str | None:
    """Why a mod can't be unloaded for this plan, or None if it can."""
    if c.id == target:
        return "the mod being loaded"
    if c.load != "loaded" or not c.up:
        return "not loaded"
    if c.id in never:
        return "never_unload"
    if not c.auto_unload:
        return "auto_unload is off"
    if c.busy or c.in_flight > 0:
        return "busy"
    if not c.unloadable:
        return "no unload operation"
    return None


def make_plan(target: str, needs: int, available: int, candidates: list[Candidate], never: set[str]) -> dict[str, Any]:
    plan: dict[str, Any] = {"service": target, "needs_bytes": int(needs), "available_bytes": int(max(0, available)), "unload": [], "enough": needs <= available}
    if plan["enough"]:
        return plan
    pool = [c for c in candidates if why_not(c, target, never) is None]
    pool.sort(key=lambda c: (c.priority, -(c.idle_s or 0), c.id))
    have = max(0, available)
    for c in pool:
        if have >= needs:
            break
        frees = c.used_bytes or c.estimate_bytes or 0
        if frees <= 0:
            continue
        idle = fmt_idle(c.idle_s)
        plan["unload"].append({"id": c.id, "frees_bytes": int(frees), "reason": f"priority {c.priority}" + (f", idle {idle}" if idle else "")})
        have += frees
    plan["enough"] = have >= needs
    return plan


def extend_plan(plan: dict[str, Any], pool: str, pool_name: str, needs: int, available: int, candidates: list[Candidate],
                never: set[str], frees: dict[str, int]) -> dict[str, Any]:
    """Add a dedicated GPU's pool to a system plan (plan 36.2): what the mods already chosen free
    there counts first, then more idle mods (same order) until its gap is covered. Their steps
    carry `pool` and free that pool's bytes."""
    chosen = {u["id"] for u in plan["unload"]}
    have = max(0, available) + sum(frees.get(i, 0) for i in chosen)
    if have < needs:
        pool_c = [c for c in candidates if c.id not in chosen and why_not(c, plan["service"], never) is None]
        pool_c.sort(key=lambda c: (c.priority, -(c.idle_s or 0), c.id))
        for c in pool_c:
            if have >= needs:
                break
            f = frees.get(c.id, 0)
            if f <= 0:
                continue
            idle = fmt_idle(c.idle_s)
            plan["unload"].append({"id": c.id, "frees_bytes": int(f), "reason": f"priority {c.priority}" + (f", idle {idle}" if idle else ""), "pool": pool})
            have += f
    plan["pools"].append({"pool": pool, "name": pool_name, "needs_bytes": int(needs), "available_bytes": int(max(0, available)), "enough": have >= needs})
    plan["enough"] = all(p["enough"] for p in plan["pools"])
    short = [p["pool"] for p in plan["pools"] if p["needs_bytes"] > p["available_bytes"]]
    plan["pool"] = short[0] if short else "system"
    return plan


def describe(plan: dict[str, Any], name: str) -> str:
    """The `needs_room` error detail; for a GPU's pool, its own numbers (plan 36.2)."""
    pool = next((p for p in plan.get("pools", []) if p["pool"] == plan.get("pool") and p["pool"] != "system"), None)
    if pool:
        head = f"Loading {name} needs ~{fmt_gb(pool['needs_bytes'])} on {pool['name']}, {fmt_gb(pool['available_bytes'])} free there"
    else:
        head = f"Loading {name} needs ~{fmt_gb(plan['needs_bytes'])}, {fmt_gb(plan['available_bytes'])} available"
    if not plan["unload"]:
        return head + ", and no idle mod can be unloaded to make room."
    names = ", ".join(u["id"] for u in plan["unload"])
    if plan["enough"]:
        return f"{head}. Unloading {names} makes room."
    return f"{head}. Even unloading {names} isn't enough."
