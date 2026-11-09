"""Plan projects 3.2: a project's sources in chunks, sent to the embed mod's collection and searched by meaning, or by
words (BM25) when the embed mod is off; re-indexing replaces old chunks; removing a source or the project forgets them."""

from __future__ import annotations

import asyncio
import time

from agent.projects.index import CHUNK, OVERLAP, bm25, chunks, ns


def test_chunk_edges():
    assert chunks("") == [] and chunks("  \n ") == []
    one = chunks("short text\n")
    assert one == [{"n": 0, "text": "short text\n", "line": 1}]
    exact = chunks("x" * CHUNK)
    assert len(exact) == 1
    text = "".join(f"line {i:04d} " + "w" * 40 + "\n" for i in range(400))          # ~20,000 characters
    cs = chunks(text)
    assert all(len(c["text"]) <= CHUNK for c in cs) and [c["n"] for c in cs] == list(range(len(cs)))
    assert all(c["text"].endswith("\n") for c in cs[:-1])                              # ends at a line break
    for a, b in zip(cs, cs[1:]):
        tail = a["text"][-OVERLAP // 2:]
        assert tail in b["text"][:OVERLAP + 60], "the next chunk starts inside the last one's end"
        assert text.count("\n", 0, text.index(b["text"])) + 1 == b["line"]
    assert cs[0]["line"] == 1 and "page" not in cs[0]
    assert cs[-1]["text"].rstrip().endswith("line 0399 " + "w" * 40)                  # nothing lost at the end
    pdf = "--- page 1 ---\n" + "a b c\n" * 700 + "\f--- page 2 ---\n" + "d e f\n" * 700
    pages = [c.get("page") for c in chunks(pdf)]
    assert pages[0] == 1 and pages[-1] == 2 and pages == sorted(pages)
    assert ns("p_0a1b2c3d4e") == "proj-0a1b2c3d4e"


def test_bm25():
    rows = [{"text": "glaciers lost mass in the alps"}, {"text": "tomatoes by the fence"}, {"text": "alps alps alps glaciers"}]
    got = bm25(rows, "Alps glaciers")
    assert [r["text"] for r, _ in got] == ["alps alps alps glaciers", "glaciers lost mass in the alps"]
    assert bm25(rows, "") == [] and bm25([], "x") == []


async def _wait(cond, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError


async def test_index_search_reindex_and_forget(env):
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Thesis"})).json()
    col = ns(p["id"])
    oid = env.hub.doc("Paper.pdf", pages=["Mass balance of alpine glaciers fell sharply in 2024.\n" * 80, "Tomato yields rose.\n" * 80])
    src = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": oid})).json()
    await _wait(lambda: len(env.hub.texts.get(col, {})) >= 2)
    ids = sorted(env.hub.texts[col])
    assert all(i.startswith(src["id"] + "#") for i in ids)
    t = env.hub.texts[col][ids[0]]
    assert t["title"] == "Paper.pdf" and t["meta"]["sid"] == src["id"] and t["meta"]["page"] == 1
    idx = env.agent.project_index_store
    hits = await idx.search(p["id"], "glaciers mass balance", 3)
    assert hits and hits[0]["by"] == "meaning" and hits[0]["sid"] == src["id"] and "glaciers" in hits[0]["text"]
    # re-indexing replaces the old chunks (here and in the embed mod)
    env.hub.texts[oid]["text"] = "A much shorter text about moraines."
    env.agent.project_texts.clear()
    n = await idx.index_source(p["id"], env.agent.projects.source(src["id"]))
    assert n == 1 and sorted(env.hub.texts[col]) == [src["id"] + "#0"]
    assert [r["text"] for r in idx.rows(p["id"])] == ["A much shorter text about moraines."]
    # the embed mod off: search by words over the kept chunks
    env.hub.embed_down = True
    hits = await idx.search(p["id"], "moraines", 3)
    assert hits and hits[0]["by"] == "words" and hits[0]["text"].startswith("A much shorter")
    assert await idx.search(p["id"], "unrelated", 3) == []
    env.hub.embed_down = False
    # removing the source forgets its chunks; deleting the project forgets its collection
    other = env.hub.doc("Notes.md", text="Field notes on crevasses.", kind="text")
    s2 = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": other})).json()
    await _wait(lambda: any(i.startswith(s2["id"]) for i in env.hub.texts.get(col, {})))
    await c.delete(f"/v1/projects/{p['id']}/sources/{src['id']}")
    assert not any(i.startswith(src["id"]) for i in env.hub.texts[col]) and idx.rows(p["id"], [src["id"]]) == []
    done = (await c.delete(f"/v1/projects/{p['id']}")).json()
    assert done["collection"] == col and col not in env.hub.texts and idx.rows(p["id"]) == []


async def test_indexing_never_holds_up_a_route(env):
    env.hub.embed_down = True                          # the embed mod off: indexing still keeps the chunks
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Quiet"})).json()
    oid = env.hub.doc("a.md", text="alpha beta gamma", kind="text")
    r = await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": oid})
    assert r.status_code == 201
    idx = env.agent.project_index_store
    await _wait(lambda: idx.rows(p["id"]))
    assert (await idx.search(p["id"], "gamma"))[0]["by"] == "words"
