"""Conversations you can look up (plan 28.5): when a chat has been quiet for `idle_min` minutes, the agent writes
a short summary of it (what was asked, what was done, the outputs made, decisions, open ends) and sends it to the
embed mod's `chats` collection, which embeds it under its idle rule. The Chat list's "by meaning" search and the
`chat_search` tool find chats through it.

- **No document text:** the summary is written from the learner's view of the chat (`learn.loop.render`):
  documents as their cards, tool results as their status, so a file's, a page's or a transcript's words never
  get into it (plan 24.8's rule).
- **Rewritten** when the chat continues and goes quiet again; dry runs and `no_learn` chats are skipped; deleting
  a chat deletes its summary here and in the embed mod.
- **Not memory:** nothing here feeds preferences or the prompt unless a chat is looked up.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from .learn.loop import render

log = logging.getLogger("agent.summaries")
CHECK_S = 60
EMBED = "/api/s/embed/v1"
SCHEMA = """CREATE TABLE IF NOT EXISTS thread_summaries (
    thread_id TEXT PRIMARY KEY, summary TEXT NOT NULL, upto_seq INTEGER NOT NULL, made REAL NOT NULL,
    model TEXT, sent INTEGER NOT NULL DEFAULT 0)"""
PROMPT = """Summarise this chat between a user and an AI assistant so it can be found again by searching. Write
3 to 6 plain sentences, no headings or lists: what the user wanted, what was done (the tools or kinds of work), the
outputs made (by name, with their output: refs), any decisions or settings chosen, and what was left open.
Documents, web pages and transcripts appear only as their names: name them, never quote or paraphrase their
contents. The transcript below is abridged: long replies end in […] where they were shortened for you, so don't
call them cut off or incomplete. Don't invent anything that isn't in the chat.

The chat:
{chat}"""


def chat_text(events: list[dict[str, Any]], cap: int = 8000) -> str:
    """The chat as the summary's model sees it: the learner's rendering plus the outputs it made, by name."""
    made = []
    for e in events:
        if e["type"] == "tool_result":
            for o in (e.get("payload") or {}).get("outputs") or []:
                ref = o.get("ref") or (f"output:{o['output_id']}" if o.get("output_id") else "")
                made.append(f"{ref} {o.get('title') or ''} ({o.get('kind') or 'output'})".strip())
    text = render(events, cap=cap, reply_cap=1200)
    return text + ("\nOUTPUTS MADE: " + "; ".join(dict.fromkeys(made)) if made else "")


class Summaries:
    def __init__(self, agent: Any, idle_min: float = 30, clock: Callable[[], float] = time.time) -> None:
        self.agent, self.idle_s, self.clock = agent, idle_min * 60, clock
        self.store = agent.store
        with self.store._lock:
            self.store._c.execute(SCHEMA)
        self.busy = False

    # ---- the table ---------------------------------------------------------------------------

    def get(self, tid: str) -> dict[str, Any] | None:
        rows = self.store._all("SELECT * FROM thread_summaries WHERE thread_id = ?", [tid])
        return dict(rows[0]) if rows else None

    def _save(self, tid: str, summary: str, upto: int, model: str) -> None:
        with self.store._lock:
            self.store._c.execute("INSERT INTO thread_summaries (thread_id, summary, upto_seq, made, model, sent) "
                                  "VALUES (?, ?, ?, ?, ?, 0) ON CONFLICT(thread_id) DO UPDATE SET summary = excluded.summary, "
                                  "upto_seq = excluded.upto_seq, made = excluded.made, model = excluded.model, sent = 0",
                                  (tid, summary, upto, self.clock(), model))
            self.store._c.commit()

    def _sent(self, tid: str) -> None:
        with self.store._lock:
            self.store._c.execute("UPDATE thread_summaries SET sent = 1 WHERE thread_id = ?", (tid,))
            self.store._c.commit()

    # ---- which chats ---------------------------------------------------------------------------

    def due(self) -> list[dict[str, Any]]:
        """Chats quiet for `idle_s` whose summary is missing or older than their last event."""
        now, out = self.clock(), []
        for t in self.store.threads(limit=1000) + self.store.threads(archived=True, limit=1000):
            st = t.get("settings") or {}
            if st.get("dry_run") or st.get("no_learn") or self.agent.running(t["id"]):
                continue
            last = self.store.last_seq(t["id"])
            evs = self.store.events(t["id"], max(0, last - 1))
            if not evs or now - evs[-1]["ts"] < self.idle_s:
                continue
            s = self.get(t["id"])
            if s and s["upto_seq"] >= last:
                continue
            if not self.store.events(t["id"], types=("user",)):
                continue
            out.append(t)
        return out

    # ---- writing and sending -------------------------------------------------------------------

    async def summarize(self, tid: str) -> str | None:
        t = self.store.thread(tid)
        if t is None:
            return None
        events = self.store.events(tid)
        model = t.get("model") or self.agent.cfg.model
        if model != self.agent.cfg.model and await self.agent.llm.is_cloud(model):
            model = self.agent.cfg.model        # background work never goes to a paid provider (plan llm-servers 2.1)
        reply = await self.agent.llm.chat(model, [{"role": "user", "content": PROMPT.format(chat=chat_text(events))}],
                                          stream=False)
        text = (reply.text or "").strip()
        if not text:
            return None
        self._save(tid, text, events[-1]["seq"] if events else 0, model)
        await self.send(tid)
        return text

    async def send(self, tid: str) -> bool:
        """To the embed mod's `chats` (kept unsent, and retried, when it isn't there)."""
        s, t = self.get(tid), self.store.thread(tid)
        if not s or not t:
            return False
        try:
            await self.agent.hub._json("PUT", f"{EMBED}/chats/{tid}", json={
                "title": t.get("title") or "", "summary": s["summary"], "created_ts": t.get("created"),
                "updated_ts": t.get("updated")})
        except Exception as e:  # noqa: BLE001: no embed mod, or it's starting
            log.debug("sending the summary of %s: %s", tid, e)
            return False
        self._sent(tid)
        return True

    async def forget(self, tid: str) -> None:
        with self.store._lock:
            self.store._c.execute("DELETE FROM thread_summaries WHERE thread_id = ?", (tid,))
            self.store._c.commit()
        try:
            await self.agent.hub._json("DELETE", f"{EMBED}/chats/{tid}")
        except Exception:  # noqa: BLE001: not there, or no embed mod
            pass

    async def check(self) -> int:
        """One pass: summarise what's due (one chat at a time), resend what didn't reach the embed mod."""
        if self.busy:
            return 0
        self.busy = True
        n = 0
        try:
            for t in self.due():
                try:
                    if await self.summarize(t["id"]):
                        n += 1
                except Exception:  # noqa: BLE001: the model may be away; the next pass tries again
                    log.exception("summarising %s", t["id"])
            for r in self.store._all("SELECT thread_id FROM thread_summaries WHERE sent = 0", []):
                await self.send(r["thread_id"])
        finally:
            self.busy = False
        return n

    async def run_forever(self, stop: asyncio.Event, every: float = CHECK_S) -> None:
        while not stop.is_set():
            try:
                await self.check()
            except Exception:  # noqa: BLE001
                log.exception("summaries")
            try:
                await asyncio.wait_for(stop.wait(), timeout=every)
            except asyncio.TimeoutError:
                pass

    # ---- looking up ---------------------------------------------------------------------------

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Chats by meaning: title, date, summary and a link, best first. Raises when the embed mod isn't there."""
        body = await self.agent.hub._json("POST", f"{EMBED}/chats/search", json={"query": query, "limit": limit},
                                          timeout=120)
        out = []
        for h in body.get("results") or []:
            t = self.store.thread(h["thread_id"])
            if t is None:                                  # deleted here since: tidy the index
                asyncio.create_task(self.forget(h["thread_id"]))
                continue
            out.append({"thread_id": t["id"], "title": t.get("title") or "", "summary": h.get("summary") or "",
                        "date": time.strftime("%Y-%m-%d", time.localtime(t.get("updated") or 0)),
                        "link": f"#/chat/{t['id']}", "score": h.get("score")})
        return out
