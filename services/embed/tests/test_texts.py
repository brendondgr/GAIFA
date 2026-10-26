"""structured-memory 2.1: named text collections with the fake backend: put, embedded idle or on a search,
unchanged text keeps its vector, search by meaning within a collection (and ids), delete; chats untouched."""

from __future__ import annotations

from tests.test_chats import client_for
from tests.test_library import make, run


def test_texts_are_embedded_found_filtered_and_deleted(settings, hub):
    lib = make(settings, hub)
    with client_for(settings, lib) as c:
        for i, t in [("fact:1", "the hub listens on port 7000"), ("fact:2", "prefers sixteen by nine images"),
                     ("entity:3", "GAIFA, AIHub: the local AI hub project")]:
            assert c.put(f"/v1/texts/memory/{i}", json={"text": t, "meta": {"kind": i.split(':')[0]}}).status_code == 200
        c.put("/v1/texts/other/x", json={"text": "the hub listens on port 7000"})
        assert c.get("/v1/texts/memory").json() == {"pending": 3, "done": 0}
        assert run(lib.drain()) == 4
        assert c.get("/v1/texts/memory").json() == {"pending": 0, "done": 3}
        r = c.post("/v1/texts/memory/search", json={"query": "the hub listens on port 7000"}).json()
        assert r["results"][0]["id"] == "fact:1" and r["results"][0]["meta"] == {"kind": "fact"}
        assert {x["id"] for x in r["results"]} == {"fact:1", "fact:2", "entity:3"}        # never another collection
        only = c.post("/v1/texts/memory/search", json={"query": "port", "ids": ["fact:2"]}).json()["results"]
        assert [x["id"] for x in only] == ["fact:2"]
        c.put("/v1/texts/memory/fact:2", json={"text": "prefers sixteen by nine images", "meta": {"kind": "fact", "v": 2}})
        assert c.get("/v1/texts/memory").json() == {"pending": 0, "done": 3}                # unchanged text: kept
        c.put("/v1/texts/memory/fact:2", json={"text": "prefers square images"})
        assert c.get("/v1/texts/memory").json()["pending"] == 1
        assert c.post("/v1/texts/memory/search", json={"query": "prefers square images"}).json()["results"][0]["id"] == "fact:2"
        assert c.delete("/v1/texts/memory/fact:1").json() == {"deleted": "fact:1"}
        assert c.delete("/v1/texts/memory/fact:1").status_code == 404
        assert c.delete("/v1/texts/memory?ids=fact:2,entity:3").json() == {"deleted": 2}
        assert c.post("/v1/texts/memory/search", json={"query": "x"}).json() == {"results": [], "pending": 0}
        assert c.get("/v1/texts/other").json() == {"pending": 0, "done": 1}
        assert c.put("/v1/texts/Bad NS/x", json={"text": "x"}).status_code in (404, 422)
        assert c.get("/v1/chats").json() == {"pending": 0, "done": 0}
