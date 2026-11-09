"""Pages fetched again when a question needs them (plan projects 3.5), never on a schedule.

Before each answer in a project chat, the user's message is compared by meaning with the project's pages (`match`):
page chunks only, grouped by page; a page counts when its best score reaches MATCH_MIN (by meaning; WORDS_MIN by
words, when the embed mod is off), or when its title's or URL's words are in the message; at most MAX_PAGES. Matched
pages older than their `max_age_s` (and not set to never) are fetched again in parallel and re-indexed (`refresh_for`),
and a `project_refresh {for: seq, pages: [{sid, title, ok, error?, slow?}]}` event is written. The turn's first model
call waits for this beside recall; a page still fetching after FRESH_WAIT_S is read as its last copy (the prompt says
it is being fetched again), and its fetch finishes in the background.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from . import sources

log = logging.getLogger("agent.projects")
MATCH_MIN = 0.6          # a cosine score (~0.5 is unrelated for EmbeddingGemma)
WORDS_MIN = 1.0          # a BM25 score, when the embed mod is off
MAX_PAGES = 3
FRESH_WAIT_S = 8.0       # under the loop's RECALL_WAIT_S, so the event is written before the model call goes ahead
STOP = {"the", "and", "for", "with", "from", "that", "this", "what", "about", "page", "news", "www", "com", "org", "net",
        "html", "http", "https", "index", "latest"}
WORD = re.compile(r"[a-z0-9]{4,}")


def words(text: str) -> set[str]:
    return {w for w in WORD.findall((text or "").lower()) if w not in STOP}


def named(src: dict[str, Any], said: set[str]) -> bool:
    """The message names the page: a word of its title, or of its URL's host or path."""
    u = urlparse(src.get("url") or "")
    return bool(said & (words(src.get("title") or "") | words(u.netloc.replace(".", " ")) | words(u.path.replace("/", " "))))


def stale(src: dict[str, Any], now: float) -> bool:
    if src.get("max_age_s") is None:                     # never fetched again on its own
        return False
    return not src.get("fetched") or now - float(src["fetched"]) > int(src["max_age_s"])


async def match(agent: Any, pid: str, text: str) -> list[dict[str, Any]]:
    """The project's pages this message touches, best first (at most MAX_PAGES)."""
    pages = {s["id"]: s for s in agent.projects.sources(pid) if s["kind"] == "page"}
    if not pages or not text.strip():
        return []
    best: dict[str, float] = {}
    try:
        for h in await agent.project_index_store.search(pid, text, 12, kinds=("page",)):
            floor = MATCH_MIN if h["by"] == "meaning" else WORDS_MIN
            if h["score"] >= floor:
                best[h["sid"]] = max(best.get(h["sid"], 0.0), h["score"])
    except Exception as e:  # noqa: BLE001: the names still match
        log.info("matching project %s's pages: %s", pid, e)
    said = words(text)
    for sid, s in pages.items():
        if sid not in best and named(s, said):
            best[sid] = 0.0
    order = sorted(best, key=lambda k: -best[k])
    return [pages[k] for k in order[:MAX_PAGES]]


async def refresh_for(agent: Any, tid: str, pid: str, text: str, seq: int, wait: float | None = None) -> dict[str, Any] | None:
    """Fetch the stale pages this message matches; the `project_refresh` event, or None when none needed it."""
    now = time.time()
    due = [s for s in await match(agent, pid, text) if stale(s, now)]
    if not due:
        return None
    tasks = {s["id"]: asyncio.create_task(sources.fetch(agent, s["id"])) for s in due}
    for t in tasks.values():
        sources._tasks(agent).add(t)
        t.add_done_callback(sources._tasks(agent).discard)
    await asyncio.wait(tasks.values(), timeout=FRESH_WAIT_S if wait is None else wait)
    pages = []
    for s in due:
        t = tasks[s["id"]]
        if not t.done():
            pages.append({"sid": s["id"], "title": s.get("title") or s.get("url"), "ok": False, "slow": True})
            continue
        got = t.result() if not t.exception() else None
        ok = bool(got and got.get("status") == "ok")
        pages.append({"sid": s["id"], "title": (got or s).get("title") or s.get("url"), "ok": ok,
                      **({} if ok else {"error": (got or {}).get("error") or "the fetch failed"})})
    return agent.emit(tid, "project_refresh", {"for": seq, "pages": pages})
