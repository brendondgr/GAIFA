"""A project's files and web pages (plan projects 3.1). Both stay hub outputs; the project keeps references.

- **A file** is an output already in GAIFA (an upload, or one picked from Outputs): its title and size are read once.
  Removing it from the project never deletes the output.
- **A page** is a URL, fetched through the hub's `POST /api/web/read` (the user asked for it, so no card; the hub
  screens the whole page and keeps the report). Each fetch saves a new hidden output, and the source keeps the newest;
  a fetch that fails keeps the last copy and stores the error. A page added is fetched in the background.
- **Text** is read through the hub's output text route (`/api/outputs/{id}/text`, screened as the chat model may read
  it), a `docs.MAX_FETCH` window at a time, and kept in memory per output id (an output's text never changes).

Every change is `{type: "project_source", id: <pid>, source}` to the streams watching projects, so a page shows
fetching, ok and error as they happen; and a source added or fetched is (re)indexed in the background (index.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

from ..docs import MAX_FETCH
from ..hubapi import HubCallError

log = logging.getLogger("agent.projects")
TEXT_CACHE = 64                   # outputs whose text is kept in memory
FETCH_TIMEOUT_S = 300.0           # the hub screens pages one at a time, a long page in about a minute: several added
                                  # together queue behind each other (a chat waits only RECALL_WAIT_S for its own)


def publish(agent: Any, pid: str, src: dict[str, Any] | None, removed: str | None = None) -> None:
    agent.live.broadcast({"type": "project_source", "thread_id": None, "seq": None, "ts": time.time(), "id": pid,
                          "source": src, **({"removed": removed} if removed else {}),
                          "payload": {"id": pid, "source": src, **({"removed": removed} if removed else {})}})


def _texts(agent: Any) -> OrderedDict[str, str]:
    if not hasattr(agent, "project_texts"):
        agent.project_texts = OrderedDict()
    return agent.project_texts


async def text(agent: Any, src: dict[str, Any]) -> str:
    """The source's whole text ("" for a page never fetched)."""
    oid = src.get("output_id")
    if not oid:
        return ""
    cache = _texts(agent)
    if oid in cache:
        cache.move_to_end(oid)
        return cache[oid]
    parts, nxt = [], 0
    while nxt is not None:
        w = await agent.hub.output_text(oid, offset=nxt, limit=MAX_FETCH)
        parts.append(w["text"])
        nxt = w["next_offset"]
    body = "".join(parts)
    cache[oid] = body
    while len(cache) > TEXT_CACHE:
        cache.popitem(last=False)
    return body


async def window(agent: Any, src: dict[str, Any], offset: int = 0, limit: int = 12000) -> dict[str, Any]:
    """A window of the source's text, as the hub reads it (`project_read`)."""
    return await agent.hub.output_text(src["output_id"], offset=offset, limit=limit)


async def add_file(agent: Any, pid: str, output_id: str) -> dict[str, Any]:
    oid = output_id.removeprefix("output:")
    o = await agent.hub.output(oid)
    if o.get("kind") not in ("text", "document"):
        from .store import ProjectError
        raise ProjectError("not_text", f"{o.get('title') or oid} is a {o.get('kind')}: a project holds texts and documents")
    w = await agent.hub.output_text(oid, limit=1)
    src = agent.projects.add_source(pid, "file", output_id=oid, title=o.get("title") or oid, chars=int(w.get("total_chars") or 0))
    publish(agent, pid, src)
    after_change(agent, pid, src)
    return src


async def add_page(agent: Any, pid: str, url: str, max_age_s: int | None) -> dict[str, Any]:
    from .store import ProjectError
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ProjectError("bad_url", "a page is an http:// or https:// URL")
    src = agent.projects.add_source(pid, "page", url=url, title=url, max_age_s=max_age_s, status="fetching")
    publish(agent, pid, src)
    task = asyncio.create_task(fetch(agent, src["id"]))
    _tasks(agent).add(task)
    task.add_done_callback(_tasks(agent).discard)
    return src


def _tasks(agent: Any) -> set[asyncio.Task[Any]]:
    if not hasattr(agent, "project_tasks"):
        agent.project_tasks = set()
    return agent.project_tasks


async def fetch(agent: Any, sid: str) -> dict[str, Any] | None:
    """Fetch a page again: the newest output and its size on success; on failure the last copy stays and `error` says
    why. Re-indexed after a success."""
    src = agent.projects.source(sid)
    if src is None or src["kind"] != "page":
        return src
    pid = src["project_id"]
    src = agent.projects.update_source(sid, status="fetching")
    publish(agent, pid, src)
    try:
        got = await asyncio.wait_for(agent.hub._json("POST", "/api/web/read", json={"url": src["url"]}, timeout=FETCH_TIMEOUT_S), FETCH_TIMEOUT_S)
    except (HubCallError, asyncio.TimeoutError, OSError, ValueError) as e:
        why = e.detail if isinstance(e, HubCallError) else "the page didn't answer in time" if isinstance(e, asyncio.TimeoutError) else str(e)
        log.info("fetching %s for project %s: %s", src["url"], pid, why)
        if agent.projects.source(sid) is None:
            return None                                   # removed meanwhile
        src = agent.projects.update_source(sid, status="error", error=str(why)[:500])
        publish(agent, pid, src)
        return src
    if agent.projects.source(sid) is None:
        return None
    out = got.get("output") or {}
    src = agent.projects.update_source(sid, status="ok", error=None, output_id=out.get("id"), fetched=time.time(),
                                       chars=int(got.get("chars") or 0), title=got.get("title") or src["title"])
    publish(agent, pid, src)
    after_change(agent, pid, src)
    return src


def after_change(agent: Any, pid: str, src: dict[str, Any]) -> None:
    """A source added or fetched again is indexed in the background (3.2); nothing waits for it."""
    hook = getattr(agent, "project_index", None)
    if hook is None:
        return
    task = asyncio.create_task(hook(pid, src))
    _tasks(agent).add(task)
    task.add_done_callback(_tasks(agent).discard)


def age_words(seconds: float) -> str:
    """"5 min", "2 h", "3 days": how old a page's copy is, for the prompt."""
    s = max(0, int(seconds))
    if s < 90:
        return "just now" if s < 45 else "1 min"
    if s < 5400:
        return f"{round(s / 60)} min"
    if s < 36 * 3600:
        return f"{round(s / 3600)} h"
    return f"{round(s / 86400)} days"
