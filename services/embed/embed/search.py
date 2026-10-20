"""Search by meaning over the library (plan 28.3): the query embedded with the query prompt, cosine against every
chunk, at most two hits an output, filtered by kind, a collection, or the chat's attachments.

A scoped search (a collection, or `thread_only`) first indexes its own outputs that aren't indexed yet: someone
is asking about them now, so it doesn't wait for the GPU to be idle, the rule for indexing everything else. A
search of everything does the same for outputs made in the last day (newest first, for up to 10 s), so what was
just made is found; older ones are left to the idle indexer.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import numpy as np

from .encoder import Encoder, prompt
from .hubclient import Hub, HubError
from .library import Library, signature

PER_OUTPUT = 2
SCOPED_BUDGET_S = 120          # how long a scoped search may spend indexing its outputs first
RECENT_S = 86400               # an unscoped search indexes pending outputs this new…
RECENT_BUDGET_S = 10           # …for up to this long
_CLOSE = re.compile(r"</\s*untrusted", re.I)


def untrusted(source: str, text: str) -> str:
    """The base prompt's rule (Stage J): text from a file is data inside this block."""
    return f'<untrusted source="{source.replace(chr(34), chr(39))}">\n{_CLOSE.sub("</ untrusted", text)}\n</untrusted>'


def origin_thread(header: str | None) -> str | None:
    """The chat a tool call came from: the hub's `X-AIHub-Origin` header (`{"thread": …}`)."""
    try:
        return (json.loads(header) or {}).get("thread") if header else None
    except (ValueError, AttributeError):
        return None


async def scope(lib: Library, hub: Hub, collection: str | None, thread: str | None) -> set[str] | None:
    """The output ids a search is limited to, or None for everything."""
    ids: set[str] | None = None
    if collection:
        if collection.startswith("thread:"):
            ids = set(await hub.thread_attachments(collection.split(":", 1)[1]))
        else:
            c = lib.store.collection(collection)
            if c is None:
                raise HubError(404, f"no collection {collection!r}", "not_found",
                               fix="library_collections lists them; leave collection out to search everything")
            ids = set(c["outputs"])
    if thread:
        mine = set(await hub.thread_attachments(thread))
        ids = mine if ids is None else ids & mine
    return ids


async def index_scope(lib: Library, ids: set[str], budget_s: float = SCOPED_BUDGET_S) -> int:
    """Index the scope's outputs that aren't done yet (new ones are queued first). Returns how many are left."""
    deadline = time.monotonic() + budget_s
    for oid in ids:
        row = lib.store.get(oid)
        if row is None:
            try:
                rec = await lib.hub.record(oid)
            except HubError:
                continue
            lib.store.queue(rec, signature(rec))
    left = 0
    for oid in ids:
        row = lib.store.get(oid)
        if row is None or row["state"] != "pending":
            continue
        if time.monotonic() > deadline:
            left += 1
            continue
        try:
            await lib.index_one(row, gate=False)
        except Exception as e:                      # noqa: BLE001: the search still answers with what's there
            lib.store.fail(oid, f"{type(e).__name__}: {e}")
    return left


async def index_recent(lib: Library, budget_s: float = RECENT_BUDGET_S, recent_s: float = RECENT_S) -> None:
    deadline = time.monotonic() + budget_s
    tried: set[str] = set()
    while time.monotonic() < deadline:
        rows = [r for r in lib.store.pending(50) if r["id"] not in tried and (r["created_ts"] or 0) > time.time() - recent_s]
        if not rows:
            return
        row = rows[0]
        tried.add(row["id"])
        try:
            await lib.index_one(row, gate=False)
        except Exception as e:                      # noqa: BLE001
            lib.store.fail(row["id"], f"{type(e).__name__}: {e}")


async def search(lib: Library, enc: Encoder, query: str, kind: str | None = None, ids: set[str] | None = None,
                 limit: int = 8) -> list[dict[str, Any]]:
    m = lib.store.matrix()
    if not len(m.ids):
        return []
    q = (await asyncio.to_thread(enc.embed, [("text", prompt(query, "query"))], 768, {"text": 1}))[0]
    scores = m.vectors @ q
    kinds = {r["id"]: r["kind"] for r in lib.store.all()}
    hits: list[tuple[int, float]] = []
    per: dict[str, int] = {}
    for i in np.argsort(-scores):
        oid = m.outputs[i]
        if ids is not None and oid not in ids:
            continue
        if kind and kinds.get(oid) != kind:
            continue
        if per.get(oid, 0) >= PER_OUTPUT:
            continue
        per[oid] = per.get(oid, 0) + 1
        hits.append((int(m.ids[i]), float(scores[i])))
        if len(hits) >= limit:
            break
    rows = lib.store.chunk_rows([h for h, _ in hits])
    out = []
    for cid, score in hits:
        r = rows.get(cid)
        if r is None:
            continue
        hit: dict[str, Any] = {"output": f"output:{r['output_id']}", "kind": r["output_kind"], "title": r["title"],
                               "match": r["kind"], "score": round(score, 3)}
        for k in ("page", "line", "start_s", "end_s"):
            if r.get(k) is not None:
                hit[k] = r[k]
        if r.get("snippet"):
            hit["snippet"] = untrusted(f"output:{r['output_id']} {r['title']}", r["snippet"])
        out.append(hit)
    return out
