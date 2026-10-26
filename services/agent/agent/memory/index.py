"""Keeping the embed mod's `memory` collection in step (plan structured-memory 2.2).

Every change to a fact or an entity marks it (`MemoryStore.dirty`); this sends them a batch at a time: a current
fact as `fact:<id>` (its sentence, titled by its entities' paths), an active entity as `entity:<id>` (its path,
name, aliases and summary); anything else (proposed, replaced, retired, forgotten, merged) is deleted from the
collection. When the embed mod isn't there the marks wait and are tried again later. At start, and on
`reindex()`, a collection that is empty while memory isn't is filled again from scratch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .store import MemoryStore

NS = "/api/s/embed/v1/texts/memory"
log = logging.getLogger("agent.memory")


def text_of(m: MemoryStore, ref: str) -> dict[str, Any] | None:
    """What the collection holds for `ref`, or None when it shouldn't hold it."""
    kind, _, rid = ref.partition(":")
    if kind == "fact":
        f = m.fact_row(rid)
        if f is None:
            return None
        pub = m.fact_public(f)
        if not pub["current"]:
            return None
        return {"text": pub["text"], "title": "; ".join(e["path"] for e in pub["entities"]), "meta": {"kind": "fact"}}
    e = m.entity_row(rid)
    if e is None or e["state"] != "active":
        return None
    aliases = m.aliases(rid)
    words = e["name"] + (f" (also {', '.join(aliases)})" if aliases else "") + (f": {e['summary']}" if e["summary"] else "")
    return {"text": words, "title": m.path(e), "meta": {"kind": "entity"}}


class MemoryIndex:
    def __init__(self, memory: MemoryStore, hub: Any, every: float = 2.0) -> None:
        self.m, self.hub, self.every = memory, hub, every
        self.wake = asyncio.Event()
        loop = asyncio.get_running_loop()                 # changes come from route threads too
        memory.on_dirty = lambda: loop.call_soon_threadsafe(self.wake.set)

    async def flush(self) -> int:
        """Send what changed; returns how many were sent. Raises when the embed mod can't be reached (they stay marked)."""
        refs = sorted(self.m.dirty)
        n = 0
        for ref in refs:
            body = text_of(self.m, ref)
            if body is None:
                try:
                    await self.hub._json("DELETE", f"{NS}/{ref}")
                except Exception as e:  # noqa: BLE001: not there is fine; anything else waits
                    if getattr(e, "status", None) != 404:
                        raise
            else:
                await self.hub._json("PUT", f"{NS}/{ref}", json=body)
            self.m.dirty.discard(ref)
            n += 1
        return n

    def all_refs(self) -> list[str]:
        facts = [f"fact:{f['id']}" for f in self.m.facts(current=True, limit=100000)]
        ents = [f"entity:{e['id']}" for e in self.m.entities()]
        return facts + ents

    async def reindex(self) -> int:
        """Empty the collection and send everything current again."""
        await self.hub._json("DELETE", NS)
        self.m.dirty.update(self.all_refs())
        return await self.flush()

    async def fill_if_empty(self) -> None:
        counts = await self.hub._json("GET", NS)
        if not (counts.get("pending") or counts.get("done")) and (refs := self.all_refs()):
            self.m.dirty.update(refs)

    async def run_forever(self, stop: asyncio.Event) -> None:
        checked, backoff = False, self.every
        while not stop.is_set():
            try:
                if not checked:
                    await self.fill_if_empty()
                    checked = True
                if self.m.dirty:
                    await self.flush()
                backoff = self.every
            except Exception as e:  # noqa: BLE001: the embed mod is away: try again later
                log.debug("memory index: %s", e)
                backoff = min(300.0, backoff * 2)
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=backoff if self.m.dirty or not checked else 60)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0.2)                            # gather a burst of changes into one batch
