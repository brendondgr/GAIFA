"""The library (plan 28.2) with the fake backend and a fake hub: indexing on create, removal on delete, chunk
positions, re-index on change, collections, a restart resuming, and the GPU and memory gates."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from embed.chunks import OVERLAP, SIZE, chunk
from embed.encoder import Encoder, FakeBackend
from embed.gpu import GpuIdle
from embed.hubclient import Hub
from embed.library import Library, signature
from embed.server import create_app
from embed.store import Store
from tests.conftest import mp4, png, wav


async def nosleep(_s: float) -> None:
    return None


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def make(settings, hub, backend=None, busy=lambda: 0, clock=None, idle_s=0.0) -> Library:
    enc = Encoder(backend or FakeBackend(), settings.state_dir)
    gpu = GpuIdle(10, idle_s, ours=lambda: enc.busy, read=busy, clock=clock or Clock(), sleep=lambda s: None)
    return Library(Store(settings.databases / "embed.db"), enc, Hub("http://hub", transport=httpx.MockTransport(hub.handler)),
                   settings, gpu=gpu, sleep=nosleep)


def run(coro):
    return asyncio.run(coro)


def kinds(lib: Library, oid: str) -> list[str]:
    return [c["kind"] for c in lib.store.chunks_of(oid)]


def test_indexes_every_kind_on_create(settings, hub, tmp_path):
    hub.add("doc", "document", title="Report", pages=["Page one text.\n" * 20, "Page two text.\n" * 20])
    hub.add("img", "image", png("red car"), title="car.png", meta={"prompt": "a red car"})
    hub.add("aud", "audio", wav(70, rate=16000, channels=1), title="talk")
    hub.add("vid", "video", mp4(tmp_path, 3), title="clip")
    hub.add("mesh", "model3d", b"glb", title="fox", preview=png("fox"))
    hub.add("zip", "archive", b"PK", title="bundle.zip")
    lib = make(settings, hub)
    assert run(lib.reconcile()) == {"outputs": 6, "queued": 6, "removed": 0}
    assert run(lib.drain()) == 6
    assert lib.store.counts()["done"] == 5 and lib.store.counts()["skipped"] == 1 and lib.store.counts()["pending"] == 0
    assert kinds(lib, "doc") == ["meta", "text", "text"]                 # a chunk a page: none crosses a page's end
    assert kinds(lib, "img") == ["meta", "image"]
    assert kinds(lib, "aud") == ["meta", "audio", "audio", "audio", "audio"]    # whole + 0–30, 30–60, 60–70
    assert [(c["start_s"], c["end_s"]) for c in lib.store.chunks_of("aud")[2:]] == [(0, 30), (30, 60), (60, 70)]
    assert kinds(lib, "vid") == ["meta", "video"]
    assert kinds(lib, "mesh") == ["meta", "image"]                               # its preview
    assert kinds(lib, "zip") == []                                  # a file name says nothing: skipped
    assert lib.store.get("zip")["state"] == "skipped"
    assert lib.store.chunks_of("img")[0]["snippet"] == "a red car"     # the prompt, without the file name
    assert lib.store.matrix().vectors.shape == (len(lib.store.matrix().ids), 768)


def test_chunk_positions(settings, hub):
    para = "word " * 150 + "\n\n"                                   # 752 chars a paragraph
    pages = [para * 6, "line\n" * 40 + para * 6, para * 2]
    hub.add("doc", "document", title="Long", pages=pages)
    hub.window = 2000                                               # several text windows per page
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    rows = [c for c in lib.store.chunks_of("doc") if c["kind"] == "text"]
    text = "".join(pages)
    starts = [0, len(pages[0]), len(pages[0]) + len(pages[1])]
    assert len(rows) >= 4 and rows[0]["offset"] == 0 and rows[0]["page"] == 1 and rows[0]["line"] == 1
    for r in rows:
        assert r["page"] == sum(1 for s in starts if s <= r["offset"])
        assert r["line"] == text.count("\n", 0, r["offset"]) + 1
    assert any(r["page"] == 2 for r in rows) and rows[-1]["page"] == 3


def test_chunker_cuts_at_breaks_and_overlaps():
    text = ("A sentence here. " * 120 + "\n\n") * 6
    parts = chunk(text)
    assert all(len(p.text) <= SIZE for p in parts)
    assert all(p.text.endswith(("\n\n", ". ")) for p in parts[:-1])
    for a, b in zip(parts, parts[1:]):
        assert b.offset < a.offset + len(a.text) <= b.offset + OVERLAP + 20      # they overlap by about OVERLAP
    assert chunk("") == [] and chunk("short")[0].text == "short"


def test_removal_on_delete(settings, hub):
    hub.add("a", "image", png("a"))
    hub.add("b", "image", png("b"))
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    run(lib.on_event({"type": "output_deleted", "id": "a"}))
    assert lib.store.get("a") is None and lib.store.chunks_of("a") == []
    hub.remove("b")                                                 # missed while disconnected
    run(lib.on_event({"type": "output_deleted", "id": "*"}))          # the hub says: refetch everything
    assert lib.store.get("b") is None and lib.store.counts()["chunks"] == 0


def test_reindex_on_change(settings, hub):
    hub.add("t", "text", text="old words", title="note")
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    assert [c["snippet"] for c in lib.store.chunks_of("t")] == ["note", "old words"]
    hub.add("t", "text", text="new words here", title="note")
    run(lib.on_event({"type": "output", "output": hub.outputs["t"][0]}))
    assert lib.store.get("t")["state"] == "pending"
    run(lib.drain())
    assert [c["snippet"] for c in lib.store.chunks_of("t")] == ["note", "new words here"]
    assert run(lib.reconcile())["queued"] == 0                       # nothing changed since
    hub.add("t", "text", text="changed while away", title="note")
    assert run(lib.reconcile())["queued"] == 1


def test_change_during_indexing_stays_pending(settings, hub):
    hub.add("t", "text", text="first", title="n")
    lib = make(settings, hub)
    run(lib.reconcile())
    rec = hub.outputs["t"][0]
    lib.store.finish("t", [], sig="something-else")                  # finished against a sig it no longer has
    assert lib.store.get("t")["state"] == "pending" and lib.store.get("t")["sig"] == signature(rec)


def test_restart_resumes_where_it_was(settings, hub):
    for i in range(4):
        hub.add(f"i{i}", "image", png(f"x{i}"))
    calls = {"n": 0}

    def busy_after_two() -> int:                                    # someone takes the GPU after two outputs
        calls["n"] += 1
        return 50 if calls["n"] > 2 * 2 * 3 else 0                  # 2 batches an output (meta, image), 3 reads each
    lib = make(settings, hub, busy=busy_after_two)
    run(lib.reconcile())
    assert run(lib.drain()) == 2 and lib.state == "waiting_for_gpu"
    assert lib.store.counts()["done"] == 2 and lib.store.counts()["pending"] == 2
    lib.store.close()
    backend = FakeBackend()
    again = make(settings, hub, backend=backend)                    # a restart: same database
    assert run(again.reconcile())["queued"] == 0                     # done ones aren't redone
    assert run(again.drain()) == 2
    assert again.store.counts() == {"pending": 0, "done": 4, "skipped": 0, "failed": 0, "chunks": 8}
    assert len([b for b in backend.batches if b[0] == "image"]) == 2


def test_waits_for_a_quiet_gpu(settings):
    clock, level = Clock(), {"v": 40}
    enc = Encoder(FakeBackend())
    gpu = GpuIdle(10, 300, ours=lambda: enc.busy, read=lambda: level["v"], clock=clock, sleep=lambda s: None)
    gpu.sample()
    assert not gpu.idle()
    level["v"] = 3
    for t in range(0, 300, 60):
        clock.t = t
        gpu.sample()
    assert not gpu.idle()                                           # quiet since the busy sample at 0: 240 s
    clock.t = 301
    gpu.sample()
    assert gpu.idle()
    level["v"] = 90                                                 # our own encoding: not counted
    enc.busy = True
    gpu.sample()
    enc.busy = False
    clock.t = 301.5
    gpu.sample()                                                    # within the grace after our work
    assert gpu.idle()
    clock.t = 303
    gpu.sample()                                                    # someone else's work: wait again
    assert not gpu.idle() and gpu.quiet_s() == 0


def test_unloads_when_the_queue_empties(settings, hub):
    hub.add("a", "image", png("a"))
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    assert not lib.enc.loaded                                       # nobody searched lately: unloaded
    hub.add("b", "image", png("b"))
    run(lib.reconcile())
    import time
    lib.last_api = time.time()
    run(lib.drain())
    assert lib.enc.loaded                                           # a search a moment ago: kept


def test_no_room_waits_without_evicting(settings, hub):
    hub.add("a", "image", png("a"))
    hub.room = False
    lib = make(settings, hub)
    run(lib.reconcile())
    assert run(lib.drain()) == 0 and lib.state == "no_room"
    assert lib.store.get("a")["state"] == "pending" and not lib.enc.loaded
    assert hub.acquires and "make_room" not in str(hub.acquires[0])


def test_failures_are_counted(settings, hub):
    hub.add("bad", "image", b"not a picture")
    lib = make(settings, hub)
    run(lib.reconcile())
    for _ in range(3):
        run(lib.drain())
    row = lib.store.get("bad")
    assert row["state"] == "failed" and row["attempts"] == 3 and "MediaError" in row["error"]


def test_collections_and_status_routes(settings, hub):
    hub.add("a", "image", png("a"))
    lib = make(settings, hub)
    app = create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib)
    lib.run = lambda stop: asyncio.sleep(0)                          # no follower in this test
    with TestClient(app) as c:
        made = c.post("/v1/collections", json={"name": "trip", "outputs": ["output:a", "b"]})
        assert made.status_code == 201 and made.json()["outputs"] == ["a", "b"]
        cid = made.json()["id"]
        assert c.post("/v1/collections", json={"name": "trip"}).status_code == 409
        assert c.put(f"/v1/collections/{cid}", json={"name": "trip 2", "outputs": ["a"]}).json()["outputs"] == ["a"]
        assert [x["name"] for x in c.get("/v1/collections").json()["collections"]] == ["trip 2"]
        assert c.delete("/v1/collections/trip 2").json() == {"deleted": cid}
        assert c.delete(f"/v1/collections/{cid}").status_code == 404
        st = c.get("/v1/library").json()
        assert st["counts"]["pending"] == 0 and st["gpu"]["threshold_pct"] == 10
        assert c.post("/v1/library/reindex", json={}).json() == {"queued": 0}
        assert {"label": "Indexed", "value": 0} in c.get("/v1/status").json()["stats"]


@pytest.mark.parametrize("ev", [{"type": "service"}, {"type": "output"}, {"type": "output_deleted"}])
def test_ignores_other_events(settings, hub, ev):
    lib = make(settings, hub)
    run(lib.on_event(ev))
    assert lib.store.counts()["pending"] == 0


def test_run_follows_events_and_indexes(settings, hub):
    """The whole loop: connect (reconcile), an `output` event from the stream, indexing, then idle."""
    import json as _json
    hub.add("a", "image", png("a"))
    new = {"id": "b", "kind": "text", "title": "b", "size_bytes": 5, "files": [], "preview": None, "created_ts": 2e6, "meta": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/events":
            hub.add("b", "text", text="hello", title="b")
            frame = f"data: {_json.dumps({'type': 'output', 'output': new})}\n\n"
            return httpx.Response(200, content=("retry: 1000\n\n" + frame).encode(),
                                  headers={"content-type": "text/event-stream"})
        return hub.handler(request)
    lib = make(settings, hub)
    lib.hub = Hub("http://hub", transport=httpx.MockTransport(handler))

    async def go() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(lib.run(stop))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if lib.store.counts()["done"] == 2 and lib.state == "idle":
                break
        stop.set()
        await asyncio.wait_for(task, 5)
    run(go())
    assert lib.store.counts()["done"] == 2 and lib.connected and lib.state == "idle"
    assert kinds(lib, "b") == ["meta", "text"] and not lib.enc.loaded


def test_hub_going_away_pauses_without_failing(settings, hub):
    hub.add("a", "image", png("a"))
    lib = make(settings, hub)
    run(lib.reconcile())

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed")
    lib.hub = Hub("http://hub", transport=httpx.MockTransport(down))
    assert run(lib.drain()) == 0 and lib.state == "no_hub"
    row = lib.store.get("a")
    assert row["state"] == "pending" and row["attempts"] == 0
