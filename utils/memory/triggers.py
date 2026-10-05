"""Proxy triggers (plan 5.5): a proxied call that matches a mod's `[memory] triggers` while
the mod is unloaded makes room before it is forwarded (the mod then loads by itself).

Without room, the caller gets `409 needs_room` with the plan; it retries with the header
`X-AIHub-Make-Room: 1` (the UI's "Unload & continue") to have the plan carried out.
Trigger paths may use `{name}` for one path segment and end in `*` for any rest.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from utils.memory.manager import TRIGGER_TTL_S

if TYPE_CHECKING:
    from utils.memory.manager import MemoryManager
    from utils.services.model import Service

HEADER = "x-aihub-make-room"
YES = {"1", "true", "yes"}


@lru_cache(maxsize=256)
def _pattern(path: str) -> re.Pattern[str]:
    rest = path.endswith("*")
    parts = re.split(r"(\{[^/{}]+\})", path.rstrip("*"))
    rx = "".join("[^/]+" if p.startswith("{") and p.endswith("}") else re.escape(p) for p in parts)
    return re.compile("^" + rx + (".*" if rest else "/?") + "$")


def matches(svc: Service, method: str, path: str) -> bool:
    mem = svc.m.memory if svc.m else None
    if not mem:
        return False
    for op in mem.triggers:
        m, _, p = op.partition(" ")
        if m.upper() == method.upper() and _pattern(p).match(path):
            return True
    return False


def hook(memory: MemoryManager) -> Any:
    async def before(svc: Service, method: str, path: str, headers: Any) -> None:
        if svc.load != "unloaded" or not matches(svc, method, path):
            return
        make_room = str(headers.get(HEADER, "")).strip().lower() in YES
        await memory.ensure_room(svc.id, make_room=make_room, ttl=TRIGGER_TTL_S)

    return before
