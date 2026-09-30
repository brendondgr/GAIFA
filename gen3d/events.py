"""Fan-out of job/worker updates to Server-Sent Events subscribers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

HEARTBEAT_S = 15.0


class Broadcaster:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def close(self) -> None:
        """End every stream now (server stopping): otherwise uvicorn waits out its graceful timeout
        on each open EventSource and then cancels them with a traceback."""
        for q in list(self._subs):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

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
                    item = await asyncio.wait_for(q.get(), HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    return
                kind, data = item
                if match is None or match(kind, data):
                    yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
        finally:
            self._subs.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)
