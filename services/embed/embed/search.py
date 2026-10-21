"""Search by meaning over the library (plan 28.3): the query embedded with the query prompt, cosine against every
chunk, at most two hits an output, filtered by kind, a collection, or the chat's attachments.

A scoped search (a collection, or `thread_only`) first indexes its own outputs that aren't indexed yet: someone
is asking about them now, so it doesn't wait for the GPU to be idle, the rule for indexing everything else. A
search of everything does the same for outputs made in the last hour (newest first, for up to 5 s), so what
was just made is found; older ones are left to the idle indexer.
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
RECENT_S = 3600                # an unscoped search indexes pending outputs this new…
RECENT_BUDGET_S = 5            # …for up to this long (a backlog after a big batch would slow every search)
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


def lines_of(text: str, first_line: int, size: int = 200) -> list[list[tuple[int, str]]]:
    """A chunk as windows of about `size` characters: each a run of whole lines with their line numbers; a longer
    line comes in sentence-sized pieces with its number. ~16 windows for an 800-token chunk."""
    out: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for i, ln in enumerate(text.split("\n")):
        ln = ln.strip()
        if not ln:
            continue
        if len(ln) > size:
            if cur:
                out.append(cur)
                cur = []
            out += [[(first_line + i, p.strip())] for p in re.split(r"(?<=[.!?])\s+", ln) if p.strip()]
            continue
        cur.append((first_line + i, ln))
        if sum(len(x) + 1 for _, x in cur) >= size:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


async def _closest(enc: Encoder, q: np.ndarray, texts: list[str]) -> np.ndarray:
    vecs = await asyncio.to_thread(enc.embed, [("text", prompt(t, "document")) for t in texts], 768, {"text": 32})
    return vecs @ q


async def best_lines(enc: Encoder, q: np.ndarray, rows: list[dict[str, Any]], per: int = 64) -> dict[int, tuple[int, str]]:
    """For each text hit, where in it the query matched: the closest window of lines (the snippet), then the
    closest line in that window (the line number). A chunk's start often isn't what matched: a rule on page 41
    behind 20 routine ones."""
    wins = [(r["id"], w) for r in rows for w in lines_of(r["text"], r["line"] or 1)[:per]]
    if not wins:
        return {}
    scores = await _closest(enc, q, [" ".join(t for _, t in w) for _, w in wins])
    best: dict[int, tuple[float, list[tuple[int, str]]]] = {}
    for (cid, w), sc in zip(wins, scores):
        if cid not in best or sc > best[cid][0]:
            best[cid] = (float(sc), w)
    lines = [(cid, n, t) for cid, (_, w) in best.items() for n, t in w]
    ls = await _closest(enc, q, [t for _, _, t in lines]) if lines else []
    top: dict[int, tuple[float, int]] = {}
    for (cid, n, _), sc in zip(lines, ls):
        if cid not in top or sc > top[cid][0]:
            top[cid] = (float(sc), n)
    out = {}
    for cid, (_, w) in best.items():
        n = top[cid][1]
        i = next(k for k, (m, _) in enumerate(w) if m == n)
        out[cid] = (n, " ".join(t for _, t in w[max(0, i - 1):i + 2])[:300])     # the line, with one on each side
    return out


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
    best = await best_lines(enc, q, [rows[c] for c, _ in hits if c in rows and rows[c].get("text")])
    out = []
    for cid, score in hits:
        r = rows.get(cid)
        if r is None:
            continue
        hit: dict[str, Any] = {"output": f"output:{r['output_id']}", "kind": r["output_kind"], "title": r["title"],
                               "match": r["kind"], "score": round(score, 3)}
        line, snip = best.get(cid, (r.get("line"), r.get("snippet")))
        for k, v in (("page", r.get("page")), ("line", line), ("start_s", r.get("start_s")), ("end_s", r.get("end_s"))):
            if v is not None:
                hit[k] = v
        if snip:
            hit["snippet"] = untrusted(f"output:{r['output_id']} {r['title']}", snip)
        out.append(hit)
    return out
