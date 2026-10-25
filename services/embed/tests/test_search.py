"""Search (plan 28.3) with the fake backend: ranking, at most two hits an output, kind and collection filters,
the chat's attachments, indexing a scope on demand, untrusted snippets, and the errors."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from embed.server import create_app
from tests.conftest import FakeGpu, png
from tests.test_library import make, run

T1, T2 = "t_00000000000a", "t_00000000000b"                       # the agent's id shape
ORIGIN = {"X-GAIFA-Origin": json.dumps({"tool_call": "c1", "service": "agent", "thread": T1})}


@pytest.fixture
def lib(settings, hub):
    hub.add("car", "image", png("red car"), title="IMG_0042.png")
    hub.add("dog", "image", png("a dog"), title="IMG_0043.png")
    hub.add("doc", "document", title="Notes", pages=["blue sky\n" * 400, "red car\n" * 500])
    hub.add("txt", "text", text="green field", title="field.txt")
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    return lib


@pytest.fixture
def client(settings, lib):
    lib.run = lambda stop: asyncio.sleep(0)
    with TestClient(create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib)) as c:
        yield c


def hits(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_ranks_by_meaning_and_wraps_snippets(client, hub):
    res = hits(client.post("/v1/search", json={"query": "red car"}))
    assert res[0]["score"] == pytest.approx(1.0, abs=1e-3) and all(h["score"] > 0.9 for h in res[:3])
    assert sorted((h["output"], h["match"]) for h in res[:3]) == [("output:car", "image"), ("output:doc", "text"),
                                                                    ("output:doc", "text")]
    text = hub.texts["doc"][0]
    docs = [h for h in res[:3] if h["output"] == "output:doc"]
    assert any(h["page"] == 2 for h in docs) and all(h["kind"] == "document" for h in docs)
    lines = text.split("\n")
    for h in docs:                                                   # the lines that matched, not the chunk's start
        assert lines[h["line"] - 1] == "red car"
        assert "red car" in h["snippet"] and "blue" not in h["snippet"]


def test_two_hits_an_output_at_most_and_the_limit(client):
    res = hits(client.post("/v1/search", json={"query": "anything", "limit": 30}))
    per = {}
    for h in res:
        per[h["output"]] = per.get(h["output"], 0) + 1
    assert max(per.values()) == 2 and set(per) == {"output:car", "output:dog", "output:doc", "output:txt"}
    assert len(hits(client.post("/v1/search", json={"query": "x", "limit": 3}))) == 3


def test_kind_and_collection_filters(client):
    assert {h["output"] for h in hits(client.post("/v1/search", json={"query": "red car", "kind": "image"}))} == \
        {"output:car", "output:dog"}
    cid = client.post("/v1/collections", json={"name": "pets", "outputs": ["dog"]}).json()["id"]
    res = hits(client.post("/v1/search", json={"query": "red car", "collection": "pets"}))
    assert {h["output"] for h in res} == {"output:dog"}
    assert hits(client.post("/v1/search", json={"query": "red car", "collection": cid}))[0]["output"] == "output:dog"
    r = client.post("/v1/search", json={"query": "x", "collection": "nope"})
    assert r.status_code == 404 and r.json()["fix"]


def test_thread_only_uses_the_chats_attachments(client, hub):
    hub.threads[T1] = [{"type": "user", "payload": {"text": "look", "attachments": ["txt"]}},
                         {"type": "assistant", "payload": {"text": "ok"}},
                         {"type": "user", "payload": {"text": "and this", "attachments": ["dog", "txt"]}}]
    res = hits(client.post("/v1/search", json={"query": "red car", "thread_only": True}, headers=ORIGIN))
    assert {h["output"] for h in res} == {"output:txt", "output:dog"}
    cols = client.get("/v1/collections", headers=ORIGIN).json()["collections"]
    assert cols[0] == {"id": f"thread:{T1}", "name": "this chat's attachments", "outputs": ["txt", "dog"], "count": 2,
                       "implicit": True}
    assert {h["output"] for h in hits(client.post("/v1/search", json={"query": "x", "collection": f"thread:{T1}"}))} == \
        {"output:txt", "output:dog"}
    r = client.post("/v1/search", json={"query": "x", "thread_only": True})
    assert r.status_code == 422 and r.json()["code"] == "no_thread"
    hub.threads[T2] = []
    r = client.post("/v1/search", json={"query": "x", "thread_only": True},
                    headers={"X-GAIFA-Origin": json.dumps({"thread": T2})})
    assert r.json()["results"] == [] and "no attachments" in r.json()["note"]


def test_scoped_search_indexes_its_outputs_first(client, hub, lib):
    hub.add("new", "image", png("red car"), title="just attached")
    hub.threads[T1] = [{"type": "user", "payload": {"text": "find it", "attachments": ["new"]}}]
    gpu = FakeGpu(blocked={"background"})                           # other work waits: background indexing would wait
    lib.gpu = gpu.slot()
    lib.enc.backend.device = "cuda"
    assert lib.store.get("new") is None
    res = hits(client.post("/v1/search", json={"query": "red car", "thread_only": True}, headers=ORIGIN))
    assert res[0]["output"] == "output:new" and lib.store.get("new")["state"] == "done"
    assert {c for e, c in gpu.log if e == "granted"} == {"interactive"} and not gpu.held    # someone is waiting: interactive


def test_unscoped_search_notes_what_isnt_indexed(client, hub, lib):
    hub.add("later", "image", png("x"))
    run(lib.reconcile())
    r = client.post("/v1/search", json={"query": "red car"})
    assert "1 output(s) aren't indexed yet" in r.json()["note"] and r.json()["searched"] == 4
    assert all(h["output"] != "output:later" for h in r.json()["results"])


def test_empty_library(settings, hub):
    lib = make(settings, hub)
    lib.run = lambda stop: asyncio.sleep(0)
    with TestClient(create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib)) as c:
        assert c.post("/v1/search", json={"query": "anything"}).json()["results"] == []
        assert c.post("/v1/search", json={"query": ""}).status_code == 422


def test_search_of_everything_indexes_what_was_just_made(client, hub, lib):
    import time
    hub.add("fresh", "image", png("red car"), title="made a minute ago")
    hub.outputs["fresh"][0]["created_ts"] = time.time() - 60
    run(lib.reconcile())
    gpu = FakeGpu(blocked={"background"})                           # other work waits: background indexing would wait
    lib.gpu = gpu.slot()
    lib.enc.backend.device = "cuda"
    res = hits(client.post("/v1/search", json={"query": "red car", "kind": "image"}))
    assert "output:fresh" in {h["output"] for h in res[:2]} and lib.store.get("fresh")["state"] == "done"


def test_the_snippet_is_the_line_that_matched(settings, hub):
    """A rule on page 2, behind routine lines: the hit's line and snippet are that rule, not the chunk's start."""
    page2 = "\n".join(["routine inspection line"] * 12 + ["stop lifting in high wind"] + ["routine inspection line"] * 5)
    hub.add("m", "document", title="Manual", pages=["cover page\n" * 30, page2 + "\n"])
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    lib.run = lambda stop: asyncio.sleep(0)
    with TestClient(create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib)) as c:
        h = next(x for x in hits(c.post("/v1/search", json={"query": "stop lifting in high wind"})) if x["match"] == "text")
    text = hub.texts["m"][0]
    assert h["page"] == 2 and text.split("\n")[h["line"] - 1] == "stop lifting in high wind"
    assert h["snippet"] == ('<untrusted source="output:m Manual">\nroutine inspection line stop lifting in high wind '
                            'routine inspection line\n</untrusted>')                 # the line, one on each side


def test_chunks_of_a_deleted_output_take_no_hit_slots(client, lib):
    """Left from an output deleted mid-index: they're skipped before the limit, not after (which left no hits)."""
    from embed.encoder import FakeBackend
    with lib.store.lock:
        for _ in range(3):
            lib.store.db.execute("INSERT INTO chunks (output_id, kind, vector) VALUES ('gone', 'image', ?)",
                                 (FakeBackend.vector("zebra stripes").astype("float16").tobytes(),))
        lib.store.version += 1
    res = hits(client.post("/v1/search", json={"query": "zebra stripes", "limit": 1}))
    assert len(res) == 1 and res[0]["output"] != "output:gone"


def test_search_answers_the_errors_envelope_when_the_encoder_fails(client, lib, hub):
    from embed.worker import WorkerDied

    def died(*a):
        raise WorkerDied("the encoder worker died (exit code -9); the next call starts a new one")
    orig = lib.enc.backend.encode
    lib.enc.backend.encode = died
    for path in ("/v1/search", "/v1/chats/search"):
        lib.store.put_chat("t_00000000000c", "x", "a summary", 1, 1)
        r = client.post(path, json={"query": "red car"})
        assert r.status_code == 503 and r.json()["code"] == "worker_died" and r.json()["fix"], (path, r.text)
    lib.enc.backend.encode = orig
    lib.enc.unload()
    hub.room = False                                                 # loading for the pending summary: no room
    r = client.post("/v1/chats/search", json={"query": "a summary"})
    assert r.status_code == 409 and r.json()["code"] == "needs_room"


def test_thread_ids_are_checked_and_odd_answers_handled(client, hub):
    for bad in ("../../../api/settings", "t1", "t_00000000000a/../x", "t_00000000000A"):
        r = client.post("/v1/search", json={"query": "x", "collection": f"thread:{bad}"})
        assert r.status_code == 422 and r.json()["code"] == "bad_thread", bad
    r = client.post("/v1/search", json={"query": "x", "thread_only": True},
                    headers={"X-GAIFA-Origin": json.dumps({"thread": "../x"})})
    assert r.status_code == 422 and r.json()["code"] == "no_thread"
    for odd in ({"events": []}, [1, "x", {"type": "user", "payload": "p"}, {"type": "user", "payload": {"attachments": "a"}}]):
        hub.threads[T1] = odd
        r = client.post("/v1/search", json={"query": "x", "thread_only": True}, headers=ORIGIN)
        if isinstance(odd, dict):
            assert r.status_code == 502 and r.json()["code"] == "hub_error"
        else:
            assert r.status_code == 200 and r.json()["results"] == []
