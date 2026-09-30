"""Fan-out of job/worker updates to Server-Sent Events subscribers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

HEARTBEAT_S = 15.0


class Broadcaster:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def publish(self, kind: str, data: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((kind, data))
            except asyncio.QueueFull:  # a stalled client: drop it rather than grow without bound
                self._subs.discard(q)

    async def stream(self, match=None) -> AsyncIterator[str]:
        """SSE text frames. `match(kind, data)` filters; a comment line every 15 s keeps proxies and
        the browser from timing the stream out."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    kind, data = await asyncio.wait_for(q.get(), HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if match is None or match(kind, data):
                    yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
        finally:
            self._subs.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)
