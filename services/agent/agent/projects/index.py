"""A project's collection (plan projects 3.2): its sources' text in chunks, searched by meaning or by words.

Each source's text is cut into chunks of about CHUNK characters with OVERLAP of overlap, preferring to end at a line
break, each with its number, the PDF page it starts on (the hub's text marks pages `--- page N ---`) and its first line.
The chunks are kept in `agent.db` (`project_chunks`) and sent to the embed mod's text collection `proj-<hex>` as
`<sid>#<n>`, titled by the source. Search asks the embed mod, and falls back to BM25 over the kept chunks when the
embed mod is off or hasn't embedded them yet. Indexing runs in a background task after a source is added or fetched
again (sources.after_change), and never holds up a route.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any
from urllib.parse import quote

from . import sources

log = logging.getLogger("agent.projects")
CHUNK = 3000
OVERLAP = 300
EMBED = "/api/s/embed/v1/texts"
SCHEMA = """
CREATE TABLE IF NOT EXISTS project_chunks (
    pid  TEXT NOT NULL,
    sid  TEXT NOT NULL,
    n    INTEGER NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    line INTEGER NOT NULL,
    PRIMARY KEY (sid, n)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS project_chunks_pid ON project_chunks (pid);
"""
PAGE = re.compile(r"--- page (\d+) ---")
WORD = re.compile(r"\w+", re.UNICODE)


def ns(pid: str) -> str:
    """The embed collection's name: `proj-<the project id's hex>` (the embed mod's names are [a-z][a-z0-9-]{1,31})."""
    return "proj-" + pid.removeprefix("p_").lower()


def chunks(text: str, size: int = CHUNK, overlap: int = OVERLAP) -> list[dict[str, Any]]:
    """`[{n, text, page?, line}]`: about `size` characters each, the next starting `overlap` before the end of the last;
    a chunk ends at the last line break in its final quarter when there is one."""
    if not text.strip():
        return []
    marks = [(m.start(), int(m.group(1))) for m in PAGE.finditer(text)]
    out, start, n = [], 0, 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            brk = text.rfind("\n", start + size * 3 // 4, end)
            if brk > start:
                end = brk + 1
        piece = text[start:end]
        if piece.strip():
            page = next((p for at, p in reversed(marks) if at <= start + (len(piece) - len(piece.lstrip()))), None)
            out.append({"n": n, "text": piece, "line": text.count("\n", 0, start) + 1, **({"page": page} if page else {})})
            n += 1
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


class ProjectIndex:
    def __init__(self, agent: Any) -> None:
        self.a = agent
        self.c, self.lock = agent.store._c, agent.store._lock
        with self.lock:
            self.c.executescript(SCHEMA)

    def rows(self, pid: str, sids: list[str] | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM project_chunks WHERE pid = ?", [pid]
        if sids is not None:
            sql += f" AND sid IN ({','.join('?' * len(sids))})"
            args += sids
        with self.lock:
            return [dict(r) for r in self.c.execute(sql + " ORDER BY sid, n", args).fetchall()]

    async def index_source(self, pid: str, src: dict[str, Any]) -> int:
        """The source's chunks, replacing its old ones here and in the embed mod (its old ids deleted first); returns
        how many. The embed mod being off only skips the embed part (search then uses words)."""
        text = await sources.text(self.a, src)
        cs = chunks(text)
        with self.lock:
            old = self.c.execute("SELECT COUNT(*) FROM project_chunks WHERE sid = ?", (src["id"],)).fetchone()[0]
            self.c.execute("BEGIN")
            self.c.execute("DELETE FROM project_chunks WHERE sid = ?", (src["id"],))
            self.c.executemany("INSERT INTO project_chunks (pid, sid, n, text, page, line) VALUES (?, ?, ?, ?, ?, ?)",
                               [(pid, src["id"], x["n"], x["text"], x.get("page"), x["line"]) for x in cs])
            self.c.execute("COMMIT")
        try:
            if old:
                await self._forget_ids(pid, src["id"], old)
            for x in cs:
                await self.a.hub._json("PUT", f"{EMBED}/{ns(pid)}/{quote(src['id'] + '#' + str(x['n']), safe='')}", json={
                    "text": x["text"][:8000], "title": (src.get("title") or src["id"])[:300],
                    "meta": {"sid": src["id"], "n": x["n"], "kind": src["kind"], "line": x["line"],
                             **({"page": x["page"]} if x.get("page") else {})}})
        except Exception as e:  # noqa: BLE001: the words fallback has them
            log.info("embedding %s of project %s: %s", src["id"], pid, e)
        return len(cs)

    async def _forget_ids(self, pid: str, sid: str, count: int) -> None:
        ids = ",".join(f"{sid}#{i}" for i in range(count))
        await self.a.hub._json("DELETE", f"{EMBED}/{ns(pid)}", params={"ids": ids})

    async def forget_source(self, pid: str, src: dict[str, Any]) -> None:
        with self.lock:
            count = self.c.execute("SELECT COUNT(*) FROM project_chunks WHERE sid = ?", (src["id"],)).fetchone()[0]
            self.c.execute("DELETE FROM project_chunks WHERE sid = ?", (src["id"],))
        if count:
            await self._forget_ids(pid, src["id"], count)

    async def forget_project(self, agent: Any, p: dict[str, Any]) -> str:
        """When the project is deleted: its whole collection (its chunks here go with its sources)."""
        with self.lock:
            self.c.execute("DELETE FROM project_chunks WHERE pid = ?", (p["id"],))
        await self.a.hub._json("DELETE", f"{EMBED}/{ns(p['id'])}")
        return ns(p["id"])

    async def search(self, pid: str, query: str, k: int = 8, kinds: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """The best passages, `[{sid, n, title, kind, text, page?, line, score, by}]`: by meaning through the embed mod,
        by words (BM25) when it is off or has none of them yet. `kinds`: only sources of these kinds."""
        by_src = {s["id"]: s for s in self.a.projects.sources(pid) if not kinds or s["kind"] in kinds}
        rows = {(r["sid"], r["n"]): r for r in self.rows(pid) if r["sid"] in by_src}
        if not rows:
            return []
        hits: list[dict[str, Any]] = []
        try:
            got = await self.a.hub._json("POST", f"{EMBED}/{ns(pid)}/search", json={"query": query, "limit": max(k * 3, 10)})
            for h in got.get("results") or []:
                m = h.get("meta") or {}
                r = rows.get((m.get("sid"), m.get("n")))
                if r is not None:
                    hits.append({**self._hit(r, by_src[r["sid"]]), "score": float(h.get("score") or 0), "by": "meaning"})
        except Exception as e:  # noqa: BLE001: the words fallback
            log.info("searching project %s by meaning: %s", pid, e)
        if not hits:
            hits = [{**self._hit(r, by_src[r["sid"]]), "score": s, "by": "words"} for r, s in bm25(list(rows.values()), query)]
        return hits[:k]

    @staticmethod
    def _hit(r: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
        return {"sid": r["sid"], "n": r["n"], "title": src.get("title") or src["id"], "kind": src["kind"], "url": src.get("url"),
                "text": r["text"], "line": r["line"], **({"page": r["page"]} if r.get("page") else {})}


def bm25(rows: list[dict[str, Any]], query: str, k1: float = 1.5, b: float = 0.75) -> list[tuple[dict[str, Any], float]]:
    """The rows that share a word with the query, best first, scored by BM25."""
    q = [w.lower() for w in WORD.findall(query)]
    if not q or not rows:
        return []
    docs = [Counter(w.lower() for w in WORD.findall(r["text"])) for r in rows]
    lens = [sum(d.values()) for d in docs]
    avg = sum(lens) / len(lens) or 1
    df = Counter(w for d in docs for w in set(d))
    out = []
    for r, d, ln in zip(rows, docs, lens):
        s = 0.0
        for w in set(q):
            if w in d:
                idf = math.log(1 + (len(rows) - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * d[w] * (k1 + 1) / (d[w] + k1 * (1 - b + b * ln / avg))
        if s > 0:
            out.append((r, round(s, 3)))
    return sorted(out, key=lambda x: -x[1])
