"""The GPU slot for embed's work (plan 31.3; it replaced the GPU-idle gate of plan 28.2).

Every encode takes a lease from GAIFA's GPU queue (`gpu_slot.py`, the reference client): searches and `/v1/embed`
as `interactive` work, library indexing as `background` work, one lease per batch. The hub starts background work
only when no other mod's GPU work runs or waits, and a batch is short, so indexing yields to anything else between
batches. An encoder on the CPU takes no slot.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from .gpu_slot import GpuSlot, Lease


def on_cpu(enc: Any, device: str) -> bool:
    """The encoder runs (or will load) on the CPU."""
    return enc.backend.device == "cpu" if enc.loaded else device == "cpu"


def slot_for(hub: Any) -> GpuSlot:
    """A client that reaches the hub the way `hub` does (its URL, service id and transport)."""
    return GpuSlot(hub_url=hub.url or "", service=hub.service, cls="interactive", transport=hub.transport)


def take(gpu: GpuSlot, enc: Any, device: str, label: str, cls: str = "interactive", est_s: float | None = None,
         on_wait: Callable[[Lease], Awaitable[None] | None] | None = None) -> Any:
    """`async with take(...)`: the slot around one encode, or nothing on the CPU."""
    if on_cpu(enc, device):
        return contextlib.nullcontext()
    return gpu.slot(label, est_s=est_s, cls=cls, on_wait=on_wait)
