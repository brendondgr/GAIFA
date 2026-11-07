"""Messages sent during a turn, held until it ends (plan chat-responsive 2.1).

A message sent while a chat's turn runs, or while it waits for a card, goes here rather than into the event log, so the
model never reads it early. When the turn ends (or the user stops it) the agent posts every held message, in order, as
its own user event and starts one turn that answers them together; a turn that ends in an error pauses the queue
instead, until Resume. The page shows the queue above the composer (`queue` events on the stream, and in `ready`)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .store import Store, new_id

log = logging.getLogger("agent.queue")

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id        TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    position  INTEGER NOT NULL,
    body      TEXT NOT NULL,
    created   REAL NOT NULL,
    edited    REAL
);
CREATE INDEX IF NOT EXISTS queue_thread ON queue (thread_id, position);
CREATE TABLE IF NOT EXISTS queue_paused (
    thread_id TEXT PRIMARY KEY,
    reason    TEXT NOT NULL,
    ts        REAL NOT NULL
);
"""
# What a held message keeps: the body of POST /v1/threads/{id}/messages, its quotes already checked.
FIELDS = ("text", "attachments", "doc_modes", "quotes", "mentions", "client_id")


class Queue:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _item(self, r: Any) -> dict[str, Any]:
        return {"id": r["id"], "position": r["position"], "created": r["created"], "edited": r["edited"], **json.loads(r["body"])}

    def items(self, tid: str) -> list[dict[str, Any]]:
        return [self._item(r) for r in self.store._all("SELECT * FROM queue WHERE thread_id = ? ORDER BY position, created", (tid,))]

    def has(self, tid: str) -> bool:
        return self.store._one("SELECT 1 FROM queue WHERE thread_id = ? LIMIT 1", (tid,)) is not None

    def get(self, tid: str, qid: str) -> dict[str, Any] | None:
        r = self.store._one("SELECT * FROM queue WHERE thread_id = ? AND id = ?", (tid, qid))
        return self._item(r) if r else None

    def add(self, tid: str, body: dict[str, Any]) -> dict[str, Any]:
        qid = new_id("q_")
        with self.store._lock:
            n = self.store._c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM queue WHERE thread_id = ?", (tid,)).fetchone()[0]
            self.store._c.execute("INSERT INTO queue (id, thread_id, position, body, created) VALUES (?, ?, ?, ?, ?)",
                                  (qid, tid, n, json.dumps({k: body[k] for k in FIELDS if body.get(k)}, ensure_ascii=False), time.time()))
        return self.get(tid, qid) or {}

    def edit(self, tid: str, qid: str, text: str | None = None, index: int | None = None) -> dict[str, Any] | None:
        """A new text, or a new place in the queue (0 is first)."""
        item = self.get(tid, qid)
        if item is None:
            return None
        with self.store._lock:
            if text is not None:
                body = {k: item[k] for k in FIELDS if item.get(k)} | {"text": text}
                self.store._c.execute("UPDATE queue SET body = ?, edited = ? WHERE id = ?", (json.dumps(body, ensure_ascii=False), time.time(), qid))
            if index is not None:
                order = [i["id"] for i in self.items(tid) if i["id"] != qid]
                order.insert(max(0, min(index, len(order))), qid)
                for pos, i in enumerate(order):
                    self.store._c.execute("UPDATE queue SET position = ? WHERE id = ?", (pos, i))
        return self.get(tid, qid)

    def remove(self, tid: str, qid: str) -> bool:
        with self.store._lock:
            return bool(self.store._c.execute("DELETE FROM queue WHERE thread_id = ? AND id = ?", (tid, qid)).rowcount)

    def take(self, tid: str, qid: str | None = None) -> list[dict[str, Any]]:
        """Removes and returns one held message, or all of them in order."""
        with self.store._lock:
            got = [i for i in self.items(tid) if qid is None or i["id"] == qid]
            for i in got:
                self.store._c.execute("DELETE FROM queue WHERE id = ?", (i["id"],))
        return got

    def clear(self, tid: str) -> int:
        with self.store._lock:
            self.store._c.execute("DELETE FROM queue_paused WHERE thread_id = ?", (tid,))
            return self.store._c.execute("DELETE FROM queue WHERE thread_id = ?", (tid,)).rowcount

    def paused(self, tid: str) -> str | None:
        """Why the queue is paused (`error`), or None."""
        r = self.store._one("SELECT reason FROM queue_paused WHERE thread_id = ?", (tid,))
        return r["reason"] if r else None

    def pause(self, tid: str, reason: str) -> None:
        with self.store._lock:
            self.store._c.execute("INSERT OR REPLACE INTO queue_paused (thread_id, reason, ts) VALUES (?, ?, ?)", (tid, reason, time.time()))

    def unpause(self, tid: str) -> None:
        with self.store._lock:
            self.store._c.execute("DELETE FROM queue_paused WHERE thread_id = ?", (tid,))

    def state(self, tid: str) -> dict[str, Any]:
        """What the page draws: `{items, paused}`."""
        return {"items": self.items(tid), "paused": self.paused(tid)}


class Queueing:
    """The Agent's side of the queue (a mixin): hold a message, and send the held ones when a turn ends."""

    def publish_queue(self, tid: str) -> None:
        self.transient(tid, "queue", self.queue.state(tid))

    def _hold(self, tid: str, thread: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
        """Holds a message sent while a turn runs, or behind messages already held; None: send it now. With no turn
        running (a paused queue, or held messages waiting for a card), the message sends them all, itself last: typing
        instead of answering a card dismisses it, as a message sent on its own does."""
        busy = self.busy(tid)
        if not busy and not self.queue.has(tid):
            return None
        item = self.queue.add(tid, body)
        self.publish_queue(tid)
        if not busy:
            self._drain_soon(tid)
        return {"queued": item}

    def _queue_after(self, tid: str, final: str) -> None:
        """A turn ended (or Stop dismissed a card): an error pauses the queue; otherwise it's sent, unless a card waits."""
        if self.shutting_down or not self.queue.has(tid):
            return
        if final == "error":
            self.queue.pause(tid, "error")
            self.publish_queue(tid)
        elif final == "idle" and not self.queue.paused(tid):
            self._drain_soon(tid)

    def _drain_soon(self, tid: str, qid: str | None = None) -> None:
        task = asyncio.create_task(self._drain(tid, qid))
        self._drains.add(task)
        task.add_done_callback(self._drains.discard)

    async def _drain(self, tid: str, qid: str | None = None) -> list[dict[str, Any]]:
        """Sends the held messages (or one: Send now), each as its own user event, then one turn answers them."""
        if qid is None:
            self.queue.unpause(tid)
        items = self.queue.take(tid, qid)
        self.publish_queue(tid)
        sent = []
        for it in items:
            try:
                sent.append(await self.send(tid, it.get("text") or "", it.get("attachments"), it.get("doc_modes"), quotes=it.get("quotes"),
                                            mentions=it.get("mentions"), client_id=it.get("client_id"), when="now", start=False))
            except Exception:  # noqa: BLE001: one message that can't go doesn't keep the others
                log.exception("sending a held message of %s", tid)
        if sent:
            self.start(tid)
        return sent
