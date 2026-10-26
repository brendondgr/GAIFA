"""Searching memory (plan structured-memory 2.3): names, keywords and meaning, fused.

Three ranked lists, combined by reciprocal rank (k = 60):
1. **names**: entities whose name or an alias appears in the query (normalized, whole words; longest first);
2. **keywords**: SQLite FTS5 over current facts and active entities (`MemoryStore.keyword`);
3. **meaning**: the embed mod's `memory` collection (`/v1/texts/memory/search`), when it answers.

An entity found by any of them brings its current facts (and its children's), a little below the facts found
directly. Only current facts unless `history`. Without the embed mod the first two still answer.
"""

from __future__ import annotations

import re
from typing import Any

from .model import norm
from .store import MemoryStore

K = 60
MEANING_FLOOR = 0.55          # the embedding model's cosine: ~0.5 is unrelated


def rrf(lists: list[list[str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for lst in lists:
        for rank, ref in enumerate(lst):
            out[ref] = out.get(ref, 0.0) + 1.0 / (K + rank + 1)
    return out


def names_in(m: MemoryStore, query: str) -> list[str]:
    """Entities named (by name or alias) in the query, longest name first."""
    q = f" {norm(query)} "
    found: list[tuple[int, str]] = []
    for e in m.entities():
        for n in [e["norm"], *(norm(a) for a in m.aliases(e["id"]))]:
            if n and f" {n} " in q:
                found.append((len(n), e["id"]))
                break
    return [eid for _, eid in sorted(found, key=lambda x: -x[0])]


async def meaning(hub: Any, query: str, limit: int = 20) -> list[str] | None:
    """Refs from the embed mod's memory collection, best first; None when it didn't answer."""
    if hub is None:
        return None
    try:
        r = await hub._json("POST", "/api/s/embed/v1/texts/memory/search", json={"query": query, "limit": limit})
    except Exception:  # noqa: BLE001: no embed mod: names and keywords still answer
        return None
    return [h["id"] for h in r.get("results") or [] if h.get("score", 1) >= MEANING_FLOOR]


async def search(m: MemoryStore, hub: Any, query: str, entity: str | None = None, kind: str | None = None,
                 history: bool = False, limit: int = 10) -> dict[str, Any]:
    query = re.sub(r"\s+", " ", query or "").strip()
    by_name = [f"entity:{e}" for e in names_in(m, query)]
    by_word = [ref for ref, _ in m.keyword(query, 40)]
    by_meaning = await meaning(hub, query)
    fused = rrf([by_name, by_word, by_meaning or []])
    scores: dict[str, float] = {}
    for ref, s in fused.items():
        k, _, rid = ref.partition(":")
        if k == "fact":
            scores[rid] = max(scores.get(rid, 0.0), s)
    ents = [ref.partition(":")[2] for ref, _ in sorted(fused.items(), key=lambda x: -x[1]) if ref.startswith("entity:")]
    for rank, eid in enumerate(ents[:5]):                 # a found entity brings its facts, below direct hits
        e = m.entity_row(eid)
        if e is None or e["state"] != "active":
            continue
        kids = [r["id"] for r in m._rows("SELECT id FROM mem_entities WHERE parent = ? AND state = 'active'", (eid,))]
        for x in [eid, *kids]:
            for f in m.facts_of(x, current=not history):
                scores.setdefault(f["id"], 0.5 / (K + rank + 2) * (1.0 if x == eid else 0.8))
    if entity:
        e = m.need(entity)
        allowed = {e["id"], *(r["id"] for r in m._rows("SELECT id FROM mem_entities WHERE parent = ?", (e["id"],)))}
        about = {r["fact"] for r in m._rows(f"SELECT fact FROM mem_fact_entities WHERE entity IN ({','.join('?' * len(allowed))})", list(allowed))}
        scores = {k: v for k, v in scores.items() if k in about}
    facts = []
    for fid, s in sorted(scores.items(), key=lambda x: -x[1]):
        f = m.fact_row(fid)
        if f is None:
            continue
        pub = m.fact_public(f)
        if (not history and not pub["current"]) or pub["state"] in ("proposed", "rejected") or (kind and pub["kind"] != kind):
            continue
        facts.append({"id": pub["id"], "text": pub["text"], "kind": pub["kind"], "about": [x["path"] for x in pub["entities"]],
                      "valid_from": pub["valid_from"], "valid_until": pub["valid_until"], "source": pub["source"],
                      **({"replaced_by": pub["replaced_by"]} if pub["replaced_by"] else {}),
                      **({} if pub["current"] else {"current": False}), "score": round(s, 4)})
        if len(facts) >= limit:
            break
    found = []
    for eid in ents[:5]:
        e = m.entity_row(eid)
        if e is not None and e["state"] == "active":
            p = m.public(e)
            found.append({k: p[k] for k in ("id", "path", "name", "aliases", "summary")})
    return {"facts": facts, "entities": found, "meaning": by_meaning is not None}
