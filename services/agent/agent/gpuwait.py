"""The turn's "Waiting for the GPU" status (plan 31.4).

A model call to a local engine goes through the relay, which takes AIHub's GPU slot for it and names the
chat on the lease (`thread`, from the X-AIHub-Thread header `llm.THREAD` sends). From `DELAY_S` into the
call, `watch` asks the hub's queue (`GET /api/gpu`) every `EVERY_S` for a waiting lease of this chat, and
while there is one it sends the transient event `gpu_wait` `{text, eta_s, ahead}`; an empty `gpu_wait`
clears it. The chat draws it on the turn's live header. It stops once the chat's lease holds the slot
(generation started), or when no lease of the chat shows up within `GIVE_UP_S` (a remote model, or no queue).
It also keeps the call's `llm.GpuWait` up to date, so the model client's stall limit skips the wait.

Polling the hub keeps the relay's reply untouched (no SSE comments before the upstream answered, so its
status code and failover stay as they were) and works for streamed and plain calls alike; a hub that
doesn't answer just means no status.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("agent.gpuwait")

DELAY_S = 1.5
EVERY_S = 2.0
GIVE_UP_S = 10.0


def waiting_text(gpu: dict[str, Any], tid: str) -> tuple[str, dict[str, Any]] | None:
    """The status line for this chat's waiting lease in a `GET /api/gpu` body, or None when it doesn't wait."""
    mine = next((w for w in gpu.get("waiting") or [] if isinstance(w, dict) and w.get("thread") == tid), None)
    if mine is None:
        return None
    names = {x.get("id"): x.get("name") or x.get("service") for x in
             [*((gpu.get("holder") or {}).get("leases") or []), *(gpu.get("waiting") or [])] if isinstance(x, dict)}
    ahead = [a for a in mine.get("ahead") or [] if isinstance(a, dict)]
    first = ahead[0] if ahead else None
    what = ""
    if first:
        name = names.get(first.get("id")) or first.get("service") or "another mod"
        label = str(first.get("label") or "").strip()
        what = f": {name}" + (f" {label[:60]}" if label else "")
    eta = mine.get("eta_s")
    left = ""
    if isinstance(eta, (int, float)) and not isinstance(eta, bool) and eta > 0:
        left = f", about {max(1, round(eta / 60))} min left" if eta >= 90 else f", about {round(eta)} s left"
    return f"Waiting for the GPU{what}{left}", {"eta_s": eta, "ahead": ahead[:5]}


def holds(gpu: dict[str, Any], tid: str) -> bool:
    return any(isinstance(x, dict) and x.get("thread") == tid for x in (gpu.get("holder") or {}).get("leases") or [])


async def watch(client: httpx.AsyncClient, tid: str, send: Callable[[dict[str, Any]], None], delay: float = DELAY_S,
                every: float = EVERY_S, give_up: float = GIVE_UP_S, waiting: Any = None) -> None:
    """Until cancelled (the model call ended): show this chat's GPU wait."""
    shown: str | None = None
    loop = asyncio.get_running_loop()
    end_of_look = loop.time() + delay + give_up
    try:
        await asyncio.sleep(delay)
        while True:
            try:
                r = await client.get("/api/gpu", timeout=5)
                gpu = r.json() if r.status_code == 200 else {}
            except (httpx.HTTPError, ValueError) as e:
                log.debug("GET /api/gpu: %s", e)
                gpu = {}
            gpu = gpu if isinstance(gpu, dict) else {}
            if holds(gpu, tid):
                break                          # its turn came: the model is generating
            found = waiting_text(gpu, tid)
            if waiting is not None:
                waiting.set(found is not None)
            if found is None and shown is None and loop.time() > end_of_look:
                break                          # never queued: a remote model, or no GPU queue
            text = found[0] if found else None
            if text != shown:
                send({"text": text, **found[1]} if found else {})
                shown = text
            await asyncio.sleep(every)
    finally:
        if waiting is not None:
            waiting.set(False)
        if shown:
            send({})
