"""AIHub's GPU slot for stt (plan 31.3; the client is ``gpu_slot.py``, a copy of the template's).

- **File jobs** take a ``job`` lease around loading and transcribing: they wait (stage ``waiting_gpu``)
  while another mod's work holds the GPU.
- **Live dictation** never waits. At its start, a stream asks the hub who holds the slot: when another
  group holds it, or doesn't give it within a second, the stream runs on the CPU. Otherwise it takes an
  ``interactive`` lease for as long as it runs on the GPU, and gives it back as soon as another mod's
  work waits: the stream moves to the CPU (the CPU model is loaded first, so no audio is held up).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .gpu_slot import GpuCancelled, GpuSlot, Lease

logger = logging.getLogger(__name__)

__all__ = ["Gpu", "GpuCancelled", "Lease"]


class Gpu:
    def __init__(self, hub_url: str | None, *, service: str = "stt",
                 transport: httpx.AsyncBaseTransport | None = None, poll_s: float = 25.0) -> None:
        self.slot = GpuSlot(hub_url=hub_url or "", service=service, cls="job", transport=transport, poll_s=poll_s)
        self.group = self.slot.group or service
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return self.slot.url is not None

    async def other(self) -> dict[str, Any] | None:
        """Another group's lease that holds the slot or waits for it (the holder first), or None. A hub that
        doesn't answer counts as a free GPU."""
        if not self.enabled:
            return None
        try:
            async with httpx.AsyncClient(base_url=self.slot.url or "", transport=self.transport, timeout=2) as c:
                r = await c.get("/api/gpu")
            body = r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None
        holder = body.get("holder") or {}
        if holder.get("group") and holder.get("group") != self.group:
            leases = holder.get("leases") or [{}]
            return {**leases[0], "state": "held"}
        for w in body.get("waiting") or []:
            if w.get("group") != self.group:
                return {**w, "state": "waiting"}
        return None

    async def enter(self, stack: contextlib.AsyncExitStack, label: str, *, cls: str | None = None,
                    est_s: float | None = None, stop: Callable[[], bool] | None = None, timeout: float | None = None,
                    on_wait: Callable[[Lease], Awaitable[None] | None] | None = None) -> Lease | None:
        """Take the slot, its release registered on ``stack``. None when ``stop()`` turns true or ``timeout``
        passes first (nothing is held then). Raises ``GpuCancelled`` when the queue's Cancel drops it."""
        task = asyncio.ensure_future(stack.enter_async_context(
            self.slot.slot(label, est_s=est_s, cls=cls, on_wait=on_wait)))
        t0 = time.monotonic()
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.1)
                if done:
                    return task.result()
                if (stop is not None and stop()) or (timeout is not None and time.monotonic() - t0 > timeout):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return None
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise


def holder_text(lease: dict[str, Any] | None) -> str:
    """"Images & Video (portrait) is using the GPU"."""
    if not lease:
        return "the GPU is busy"
    who = lease.get("name") or lease.get("service") or "another mod"
    label = f" ({lease['label']})" if lease.get("label") and lease.get("label") != lease.get("service") else ""
    verb = "is using" if lease.get("state") == "held" else "is waiting for"
    return f"{who}{label} {verb} the GPU"
