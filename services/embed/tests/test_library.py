"""The library (plan 28.2) with the fake backend and a fake hub: indexing on create, removal on delete, chunk
positions, re-index on change, collections, a restart resuming, the GPU slot (plan 31.3) and the memory gate."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from embed.chunks import OVERLAP, SIZE, chunk
from embed.encoder import Encoder, FakeBackend
from embed.hubclient import Hub
from embed.library import Library, signature
from embed.server import create_app
from embed.store import Store
from tests.conftest import FakeGpu, mp4, png, wav


async def nosleep(_s: float) -> None:
    return None


class GpuBackend(FakeBackend):
    device = "cuda"                                     # takes the GPU slot (the plain fake runs on the CPU)


def make(settings, hub, backend=None, gpu: FakeGpu | None = None) -> Library:
    """A library on the fake hub. Without `gpu` the hub has no GPU queue (404: the work runs at once)."""
    enc = Encoder(backend or FakeBackend(), settings.state_dir)
    return Library(Store(settings.databases / "embed.db"), enc, Hub("http://hub", transport=httpx.MockTransport(hub.handler)),
                   settings, gpu=gpu.slot() if gpu else None, sleep=nosleep)


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
    gpu = FakeGpu(cancel_after=2 * 2)                                # 2 batches an output (meta, image); then cancelled
    lib = make(settings, hub, backend=GpuBackend(), gpu=gpu)
    run(lib.reconcile())
    assert run(lib.drain()) == 2 and lib.state == "paused"         # cancelled from the queue: tries again later
    assert not gpu.held
    assert lib.store.counts()["done"] == 2 and lib.store.counts()["pending"] == 2
    lib.store.close()
    backend = FakeBackend()
    again = make(settings, hub, backend=backend)                    # a restart: same database
    assert run(again.reconcile())["queued"] == 0                     # done ones aren't redone
    assert run(again.drain()) == 2
    assert again.store.counts() == {"pending": 0, "done": 4, "skipped": 0, "failed": 0, "chunks": 8}
    assert len([b for b in backend.batches if b[0] == "image"]) == 2


def test_indexing_waits_for_the_gpu_as_background_work(settings, hub):
    """Each batch takes a background lease; while other work holds or waits for the slot the library waits
    (state and status job `waiting_gpu`, with what runs before it), then indexes when the slot is free."""
    hub.add("a", "image", png("a"))
    gpu = FakeGpu(blocked={"background"})
    lib = make(settings, hub, backend=GpuBackend(), gpu=gpu)

    async def go() -> None:
        await lib.reconcile()
        task = asyncio.create_task(lib.drain())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if lib.state == "waiting_gpu":
                break
        assert lib.state == "waiting_gpu" and not lib.enc.backend.batches          # nothing encoded while it waits
        job = lib.job()
        assert job["stage"] == "waiting_gpu" and job["state"] == "queued" and job["ahead"][0]["service"] == "comfy"
        assert lib.status()["gpu"]["waiting"] and lib.status()["gpu"]["eta_s"] == 120
        gpu.blocked.clear()                                         # the other work is done
        assert await asyncio.wait_for(task, 5) == 1
    run(go())
    assert lib.store.counts()["done"] == 1 and "stage" not in lib.job()      # indexing again (run() makes it idle)
    assert {c for e, c in gpu.log if e == "granted"} == {"background"} and not gpu.held
    assert gpu.log.count(("granted", "background")) == 2               # one short lease a batch (meta, image)


def test_the_lease_is_released_when_a_batch_fails(settings, hub):
    from embed.worker import WorkerDied

    hub.add("a", "image", png("a"))
    gpu = FakeGpu()
    lib = make(settings, hub, backend=FlakyBackend(WorkerDied("the encoder worker died (exit code -9)", "call")), gpu=gpu)
    lib.enc.backend.device = "cuda"
    run(lib.reconcile())
    run(lib.drain())
    assert ("released", "background") in gpu.log and not gpu.held


def test_cpu_takes_no_slot(settings, hub):
    from dataclasses import replace

    hub.add("a", "image", png("a"))
    gpu = FakeGpu(blocked={"background", "interactive"})               # would wait forever if it asked
    lib = make(replace(settings, device="cpu"), hub, gpu=gpu)
    run(lib.reconcile())
    assert run(lib.drain()) == 1 and gpu.log == []


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
        assert st["counts"]["pending"] == 0 and st["gpu"]["waiting"] is False
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


class FlakyBackend(FakeBackend):
    """Fails its first `n` encodes with `error` (a worker that died, no weights), then works."""

    def __init__(self, error: Exception, n: int = 1, on: str = "encode"):
        super().__init__()
        self.error, self.n, self.on = error, n, on

    def _maybe_fail(self, where: str) -> None:
        if where == self.on and self.n > 0:
            self.n -= 1
            raise self.error

    def load(self, parts):
        self._maybe_fail("load")
        super().load(parts)

    def encode(self, kind, items, batch_size):
        self._maybe_fail("encode")
        return super().encode(kind, items, batch_size)


def test_an_encoder_error_never_ends_the_loop(settings, hub, monkeypatch):
    """A worker that died (or no weights) stops indexing for a back-off, says why, keeps following the hub, and
    counts nothing against the outputs; the next pass starts a new worker and indexes everything."""
    from embed import library as library_mod
    from embed.worker import WorkerDied
    monkeypatch.setattr(library_mod, "BACKOFF_S", (0.05, 0.1))
    hub.add("a", "image", png("a"), title="a cat")
    lib = make(settings, hub, backend=FlakyBackend(WorkerDied("the encoder worker died (exit code -9)", "idle"), n=2))
    lib.backoff = 0.05
    run(lib.reconcile())                                            # (the fake hub has no event stream)
    lib.store.put_chat("t_00000000000a", "x", "a summary", 1, 1)
    seen = set()

    async def go() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(lib.run(stop))
        for _ in range(200):
            await asyncio.sleep(0.02)
            seen.add(lib.state)
            assert not task.done(), task.exception()
            if lib.store.counts()["done"] == 1 and lib.store.chat_counts()["done"] == 1 and lib.state == "idle":
                break
        stop.set()
        await asyncio.wait_for(task, 5)
    run(go())
    assert "error" in seen and lib.store.counts()["done"] == 1 and lib.store.chat_counts()["done"] == 1
    assert lib.store.get("a")["attempts"] == 0 and lib.error is None


@pytest.mark.parametrize("error,on,counted", [
    (FileNotFoundError("no weights in /models/embed"), "load", False),
    ("idle", "encode", False),                       # killed while idle: nothing to do with the output
    ("call", "encode", True),                        # died on the output's own inputs: it may be the cause
])
def test_encoder_errors_stop_indexing_and_count_only_a_crash_on_the_inputs(settings, hub, error, on, counted):
    from embed.worker import WorkerDied
    if isinstance(error, str):
        error = WorkerDied("the encoder worker died (exit code -9)", error)
    hub.add("a", "image", png("a"), title="a cat")
    hub.add("b", "image", png("b"), title="a dog")
    lib = make(settings, hub, backend=FlakyBackend(error, on=on))
    run(lib.reconcile())
    assert run(lib.drain()) == 0 and lib.state == "error" and type(error).__name__ in lib.error
    assert lib.store.counts()["pending"] == 2 and lib.store.get("b")["attempts"] == int(counted)
    assert lib.status()["error"] == lib.error
    assert run(lib.drain()) == 2 and lib.store.counts()["done"] == 2 and lib.error is None


def test_an_output_deleted_while_it_is_indexed_leaves_no_chunks(settings, hub):
    from embed.store import Chunk
    hub.add("o", "text", text="some words", title="note")
    lib = make(settings, hub)
    run(lib.reconcile())
    lib.store.delete("o")                                           # output_deleted arrives during index_one
    lib.store.finish("o", [Chunk("text", FakeBackend.vector("some words"), "x")], sig=lib.store.sigs().get("o"))
    assert lib.store.counts()["chunks"] == 0 and len(lib.store.matrix().ids) == 0
    with lib.store.lock:                                            # one left by an older version: reconcile drops it
        lib.store.db.execute("INSERT INTO chunks (output_id, kind, vector) VALUES ('gone', 'text', ?)",
                             (FakeBackend.vector("x").astype("float16").tobytes(),))
    run(lib.reconcile())
    assert lib.store.counts()["chunks"] == 0
