"""Other embed models (plan capability-enablement 7.3): models described by gaifa-model.toml, two fake models of
different sizes, a switch that keeps search working while the new index is built, and a text-only model's answer to
a picture search."""

from __future__ import annotations

import asyncio
import json
import threading

import httpx
import numpy as np
from fastapi.testclient import TestClient

from embed import models
from embed.encoder import Encoder, FakeBackend
from embed.hubclient import Hub
from embed.library import Library
from embed.search import search
from embed.server import create_app, model_info
from embed.store import Store
from embed.switch import Switch
from tests.conftest import png
from tests.test_library import make, run


def fake_model(root, mid: str, dim: int, kinds=("text",), name: str | None = None) -> models.ModelInfo:
    d = root / mid
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.safetensors").write_bytes(b"fake")
    (d / models.FILE).write_text(f'name = "{name or mid}"\ndim = {dim}\nkinds = {json.dumps(list(kinds))}\n'
                                 'query_prompt = "query: "\ndocument_prompt = "passage: {text}"\nsize_gb = 0.1\n')
    return models.read(d)


def text_lib(settings, hub, info: models.ModelInfo) -> Library:
    enc = Encoder(FakeBackend(info.dim), settings.state_dir, info)
    return Library(Store(settings.databases / models.db_name(info.id), info.dim), enc,
                   Hub("http://hub", transport=httpx.MockTransport(hub.handler)), settings, gpu=None)


def test_models_are_read_and_listed(settings):
    root = settings.model_dir.parent
    a = fake_model(root, "mini-a", 384, name="Mini A")
    fake_model(root, "tiny-b", 128)
    (root / "not-a-model").mkdir()
    have = models.available(root)
    assert [m.id for m in have] == ["embeddinggemma-2", "mini-a", "tiny-b"]
    assert have[0].full and have[0].dims == (768, 512, 256, 128) and not a.full and a.dims == (384,)
    assert a.prompt("cats", "query") == "query: cats" and a.prompt("cats", "document", "T") == "passage: cats"
    assert models.db_name("embeddinggemma-2") == "embed.db" and models.db_name("mini-a") == "embed-mini-a.db"
    # the model in use: EMBED_MODEL, unless a finished switch saved another
    assert model_info(settings).id == "embeddinggemma-2"
    models.choose(settings.state_dir, "mini-a")
    assert model_info(settings).id == "mini-a"
    models.choose(settings.state_dir, "gone")                       # a model that went away: the mod still starts
    assert model_info(settings).id == "embeddinggemma-2"
    (settings.model_dir / "model.safetensors").unlink()              # set up with a smaller model alone: it's used
    assert model_info(settings).id == "mini-a"


def test_two_models_of_different_sizes(settings, hub):
    root = settings.model_dir.parent
    hub.add("doc", "text", text="red car parked by the river", title="notes.txt")
    for mid, dim in (("mini-a", 384), ("tiny-b", 128)):
        info = fake_model(root, mid, dim)
        lib = text_lib(settings, hub, info)
        run(lib.reconcile())
        run(lib.drain())
        assert lib.store.matrix().vectors.shape[1] == dim
        hits = run(search(lib, lib.enc, "red car"))
        assert hits and hits[0]["output"] == "output:doc"
        lib.store.close()
    assert (settings.databases / "embed-mini-a.db").exists() and (settings.databases / "embed-tiny-b.db").exists()
    # /v1/embed answers in the model's own size; a size it can't give is refused
    info = models.read(root / "tiny-b")
    with TestClient(create_app(settings, encoder=Encoder(FakeBackend(128), settings.state_dir, info),
                               hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)))) as c:
        r = c.post("/v1/embed", json={"inputs": [{"text": "hello"}]})
        assert r.status_code == 200 and r.json()["dim"] == 128 and len(r.json()["vectors"][0]) == 128
        r = c.post("/v1/embed", json={"inputs": [{"text": "hello"}], "dim": 768})
        assert r.status_code == 422 and r.json()["code"] == "bad_dim"
        assert c.get("/v1/info").json()["dims"] == [128]


class HeldBackend(FakeBackend):
    """Waits at each encode until `go` is set: the new index is still being built."""

    def __init__(self, dim: int, go: threading.Event):
        super().__init__(dim)
        self.go = go

    def encode(self, kind, items, batch_size):
        assert self.go.wait(5), "the test never let the build go on"
        return super().encode(kind, items, batch_size)


def test_a_switch_keeps_search_working_until_the_new_index_is_ready(settings, hub):
    hub.add("doc", "text", text="red car parked by the river", title="notes.txt")
    hub.add("pic", "image", png("blue boat"), title="A blue boat")
    old = make(settings, hub)
    run(old.reconcile())
    run(old.drain())
    old.store.put_chat("t1", "Trip", "we talked about the red car", 1.0, 1.0)
    old.store.put_text("memory", "f1", "", "the user likes boats", "{}")
    run(old.index_chats())
    old.store.save_collection("cars", ["doc"])
    info = fake_model(settings.model_dir.parent, "mini-a", 384)
    go = threading.Event()
    restarted: list[bool] = []

    async def body():
        sw = Switch(old, lambda i: Encoder(HeldBackend(i.dim, go), settings.state_dir, i),
                    on_done=lambda: restarted.append(True), pause_s=0.01)
        job = sw.start(info)
        assert job["state"] == "building" and job["model"] == "mini-a"
        await asyncio.sleep(0.05)
        # the build waits on the new model; search still answers from the model in use
        hits = await search(old, old.enc, "red car")
        assert hits and hits[0]["output"] == "output:doc"
        assert sw.status()["state"] == "building" and models.chosen(settings.state_dir, "embeddinggemma-2") == "embeddinggemma-2"
        old.store.put_text("memory", "f2", "", "a fact that came in during the build", "{}")
        go.set()
        await asyncio.wait_for(sw.task, 10)
        return sw

    sw = asyncio.run(body())
    assert sw.status()["state"] == "done" and restarted == [True]
    assert models.chosen(settings.state_dir, "embeddinggemma-2") == "mini-a"
    new = Store(settings.databases / "embed-mini-a.db", 384)
    assert new.counts()["done"] == 2 and new.counts()["pending"] == 0
    assert new.chat_counts() == {"pending": 0, "done": 1}
    assert new.text_counts("memory") == {"pending": 0, "done": 2}             # f2 came in during the build: copied too
    assert [c["name"] for c in new.collections()] == ["cars"]
    assert new.matrix().vectors.shape[1] == 384
    assert [k["kind"] for k in new.chunks_of("pic")] == ["meta"]              # text-only: the picture's words alone


def test_switch_refusals(settings, hub):
    old = make(settings, hub)
    sw = Switch(old, lambda i: Encoder(FakeBackend(i.dim), settings.state_dir, i))
    try:
        sw.start(models.gemma(settings.model_dir))
    except Exception as e:                                                     # noqa: BLE001
        assert getattr(e, "code", None) == "same_model"
    else:
        raise AssertionError("switching to the model in use was allowed")
    bare = settings.model_dir.parent / "bare"
    bare.mkdir()
    (bare / models.FILE).write_text("dim = 8\n")
    try:
        sw.start(models.read(bare))
    except Exception as e:                                                     # noqa: BLE001
        assert getattr(e, "code", None) == "no_weights"


def test_a_text_only_model_answers_picture_searches(settings, hub):
    info = fake_model(settings.model_dir.parent, "mini-a", 384)
    hub.add("pic", "image", png("red car"), title="Red car at noon")
    lib = text_lib(settings, hub, info)
    run(lib.reconcile())
    run(lib.drain())
    lib.run = lambda stop: asyncio.sleep(0)
    with TestClient(create_app(settings, encoder=lib.enc, hub=lib.hub, library=lib)) as c:
        r = c.post("/v1/search", json={"query": "red car", "kind": "image"})
        assert r.status_code == 422 and r.json()["code"] == "needs_full_model" and "needs the full model" in r.json()["detail"]
        r = c.post("/v1/embed", json={"inputs": [{"image": "output:pic"}]})
        assert r.status_code == 422 and r.json()["code"] == "needs_full_model"
        r = c.post("/v1/search", json={"query": "red car at noon"})            # its title still finds it
        assert r.status_code == 200 and r.json()["results"][0]["output"] == "output:pic"
        listed = c.get("/v1/models").json()
        assert listed["model"] == "mini-a" and {m["id"]: m["in_use"] for m in listed["models"]} == \
            {"embeddinggemma-2": False, "mini-a": True}
        r = c.post("/v1/model", json={"model": "nope"})
        assert r.status_code == 404 and r.json()["code"] == "no_model"
    assert np.isfinite(lib.store.matrix().vectors).all()
