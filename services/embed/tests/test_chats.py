"""The `chats` collection (plan 28.5) with the fake backend: summaries queued, embedded under the idle rule or
on a search, found by meaning, replaced when a chat continues, and forgotten when it's deleted."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from embed.server import create_app
from tests.test_library import make, run


def client_for(settings, lib):
    lib.run = lambda stop: asyncio.sleep(0)
    return TestClient(create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib))


def test_summaries_are_embedded_found_replaced_and_deleted(settings, hub):
    lib = make(settings, hub)
    with client_for(settings, lib) as c:
        for tid, title, summary in [("t1", "Fox picture", "made a picture of a red fox in snow"),
                                    ("t2", "Taxes", "worked out the quarterly tax estimate"),
                                    ("t3", "Trip", "planned a train trip to the mountains")]:
            assert c.put(f"/v1/chats/{tid}", json={"title": title, "summary": summary, "updated_ts": 1.0}).json()["state"] == "pending"
        assert c.get("/v1/chats").json() == {"pending": 3, "done": 0}
        assert run(lib.drain()) == 3                                     # the idle indexer takes them
        assert c.get("/v1/chats").json() == {"pending": 0, "done": 3}
        r = c.post("/v1/chats/search", json={"query": "quarterly tax estimate"}).json()
        assert r["results"][0]["thread_id"] == "t2" and r["results"][0]["summary"].startswith("worked out")
        c.put("/v1/chats/t2", json={"title": "Taxes", "summary": "filed the annual return instead"})   # the chat went on
        r = c.post("/v1/chats/search", json={"query": "filed the annual return"}).json()          # embedded on search
        assert r["results"][0]["thread_id"] == "t2" and r["pending"] == 0
        assert c.delete("/v1/chats/t1").json() == {"deleted": "t1"}
        assert all(h["thread_id"] != "t1" for h in c.post("/v1/chats/search", json={"query": "red fox"}).json()["results"])
        assert c.delete("/v1/chats/t1").status_code == 404


def test_a_newer_summary_stays_pending(settings, hub):
    lib = make(settings, hub)
    lib.store.put_chat("t", "x", "first", 0, 0)
    lib.store.finish_chat("t", "an older text", lib.enc.backend.vector("x") if hasattr(lib.enc.backend, "vector") else [0] * 768)
    assert lib.store.chat_counts() == {"pending": 1, "done": 0}


def test_empty(settings, hub):
    lib = make(settings, hub)
    with client_for(settings, lib) as c:
        assert c.post("/v1/chats/search", json={"query": "x"}).json() == {"results": [], "pending": 0}


def test_summaries_go_between_a_long_outputs_batches(settings, hub):
    """A big document takes many batches (minutes on the CPU); a summary that arrives meanwhile doesn't wait."""
    hub.add("big", "text", text=("A paragraph about rivers and bridges. " * 90 + "\n\n") * 12, title="big.txt")
    lib = make(settings, hub)
    run(lib.reconcile())
    seen = []
    orig = lib.enc.backend.encode

    def encode(kind, items, bs):
        if not seen:                                              # during the document's first batch
            lib.store.put_chat("t9", "Taxes", "worked out the quarterly tax estimate", 0, 0)
        seen.append(len(items))
        return orig(kind, items, bs)
    lib.enc.backend.encode = encode
    run(lib.drain())
    assert lib.store.chat_counts() == {"pending": 0, "done": 1}
    assert seen.index(1) < len(seen) - 1                             # the summary went before the document's last batch
