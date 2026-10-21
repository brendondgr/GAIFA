"""The embed mod's API: POST /v1/embed (text, images, audio and video into one 768-d space), load and unload,
status. Media come from the hub's outputs over HTTP."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from . import media
from .encoder import DIMS, KINDS, Encoder, GemmaBackend, parts_for, prompt
from .hubclient import Hub, HubError
from .settings import MODEL_ID, REPO, REVISION, Settings
from .worker import WorkerBackend, WorkerDied
from .api_chats import add_chat_routes
from .api_library import add_library_routes, backend_error
from .library import Library, open_library

log = logging.getLogger("embed")
MAX_BYTES = {"image": 64_000_000, "audio": 512_000_000, "video": 2_000_000_000}
ACCEPTS = {"image": {"image"}, "audio": {"audio", "video"}, "video": {"video"}}   # a video's soundtrack is audio


def _file(kind: str) -> Any:
    return Field(None, description=f"An AIHub output ({kind}): `output:<id>` or the bare id",
                 json_schema_extra={"format": "aihub-file", "x-kind": kind})


class Input(BaseModel):
    """Exactly one of text, image, audio or video."""
    text: str | None = Field(None, description="Text or code, up to about 8k tokens", max_length=200_000)
    title: str | None = Field(None, description="The document's title, for task=document text (else `none`)",
                              max_length=500)
    image: str | None = _file("image")
    audio: str | None = _file("audio")
    video: str | None = _file("video")

    @model_validator(mode="after")
    def one_kind(self) -> "Input":
        given = [k for k in KINDS if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"each input needs exactly one of text, image, audio or video (got {given or 'none'})")
        return self

    @property
    def kind(self) -> str:
        return next(k for k in KINDS if getattr(self, k) is not None)


class EmbedRequest(BaseModel):
    inputs: list[Input] = Field(min_length=1, description="What to embed; every kind lands in the same space")
    dim: Literal[768, 512, 256, 128] = Field(768, description="Matryoshka size: the leading values, normalized "
                                             "again. Queries and the documents they're scored against must match")
    task: Literal["query", "document"] = Field("document", description="query: a search query (gets the query "
                                               "prompt); document: what is searched. Media take no prompt")


class LoadRequest(BaseModel):
    kinds: list[Literal["text", "image", "audio", "video"]] = Field(
        default_factory=list, description="Also load the encoders these kinds need (text alone: 270M)")


def _error(e: HubError) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status)


def create_app(settings: Settings, encoder: Encoder | None = None, hub: Hub | None = None,
               library: Library | None = None) -> FastAPI:
    """`library`: the index to run (tests pass their own); by default one is opened when `settings.index`."""
    enc = encoder or Encoder(WorkerBackend(functools.partial(GemmaBackend, settings.model_dir, settings.device)),
                             settings.state_dir)
    hub = hub or Hub(settings.hub_url)
    lib = library or (open_library(settings, enc, hub) if settings.index else None)
    stop = asyncio.Event()
    tmp = settings.state_dir / "tmp"
    day = {"date": date.today(), "inputs": 0}

    async def idle_unloader() -> None:
        while True:
            await asyncio.sleep(10)
            if enc.idle_due(settings.idle_unload_s):
                log.info("idle for %.0f s: unloading", time.time() - enc.last_used)
                await asyncio.to_thread(enc.unload)

    async def register() -> None:
        if (settings.model_dir / "model.safetensors").is_file():
            path = f"embed/{settings.model_dir.name}"
            res = await hub.register_model({"path": path, "name": "EmbeddingGemma 2", "kind": "text-encoder",
                                            "tags": ["embedding", "multimodal"],
                                            "source": {"type": "huggingface", "repo": REPO, "revision": REVISION}})
            log.info("models registry: %s %s", path, res)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(idle_unloader()), asyncio.create_task(register())]
        if lib is not None:
            tasks.append(asyncio.create_task(lib.run(stop)))
        yield
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(enc.unload)
        if lib is not None:
            lib.store.close()

    app = FastAPI(title="Embeddings", version="0.1.0", lifespan=lifespan,
                  description="EmbeddingGemma 2: text, code, images, audio and video in one 768-d space")
    app.state.library = lib
    if lib is not None:
        add_library_routes(app, lib, enc)
        add_chat_routes(app, lib, enc)

    async def make_room(kinds: set[str]) -> None:
        """Loading another encoder while loaded needs more memory: ask the hub for the difference. (A load from
        unloaded is covered by [memory] triggers, which make room before the call reaches us.)"""
        want = enc.needs(kinds)
        if want is not None and enc.loaded:
            more = enc.estimate_gb(want) - enc.estimate_gb(enc.parts or frozenset())
            await hub.acquire(more, f"EmbeddingGemma 2 {enc.key(want)}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/info", summary="The model, its sizes, what is loaded and on which device")
    def info() -> dict:
        return {"model": MODEL_ID, "repo": REPO, "revision": REVISION, "path": str(settings.model_dir),
                "weights": (settings.model_dir / "model.safetensors").is_file(), "dims": list(DIMS),
                "kinds": list(KINDS), "tasks": ["query", "document"], "loaded": enc.key(enc.parts) if enc.loaded else None,
                "device": enc.backend.device if enc.loaded else None, "dtype": enc.backend.dtype if enc.loaded else None,
                "limits": {"inputs": settings.max_inputs, "audio_s": settings.audio_max_s,
                           "video_frames": settings.video_max_frames}}

    @app.get("/v1/status", summary="Load state, busy, stats (architecture §4.6)")
    def status() -> dict:
        if day["date"] != date.today():
            day.update(date=date.today(), inputs=0)
        stats: list[dict] = [{"label": "Inputs today", "value": day["inputs"], "reset": "daily"}]
        jobs: list[dict] = []
        if lib is not None:
            c = lib.store.counts()
            stats.append({"label": "Indexed", "value": c["done"]})
            if lib.state == "indexing":
                jobs.append({"id": "library", "label": f"Indexing outputs ({c['pending']} to go)", "state": "running",
                             "progress": round(c["done"] / max(1, c["done"] + c["pending"]), 3), "route": "#/s/embed"})
        else:
            stats.append({"label": "Inputs", "value": sum(enc.counts.values())})
        if enc.loaded:
            stats.append({"label": "Loaded", "value": enc.key(enc.parts).replace("+", ", ")})
            stats.append({"label": "Device", "value": f"{'GPU' if enc.backend.device == 'cuda' else 'CPU'} {enc.backend.dtype}"})
        return {"loaded": enc.loaded, "busy": enc.busy or enc.loading,
                "idle_s": round(time.time() - enc.last_used, 1),
                "memory_estimate_gb": enc.estimate_gb(enc.parts or frozenset()), "stats": stats, "jobs": jobs}

    @app.post("/v1/load", summary="Load the text path, plus the encoders `kinds` need")
    async def load(body: LoadRequest | None = None) -> Any:
        kinds = set((body.kinds if body else []) or [])
        try:
            await make_room(kinds)
            await asyncio.to_thread(enc.load, parts_for(kinds))
        except HubError as e:
            return _error(e)
        except (FileNotFoundError, WorkerDied) as e:
            return backend_error(e)
        return {"loaded": enc.key(enc.parts), "device": enc.backend.device, "dtype": enc.backend.dtype,
                "memory_gb": enc.estimate_gb(enc.parts)}

    @app.post("/v1/unload", summary="Free the model's memory")
    async def unload() -> dict:
        return {"unloaded": await asyncio.to_thread(enc.unload)}

    async def prepare(inp: Input, task: str) -> media.Prepared:
        kind = inp.kind
        if kind == "text":
            return media.Prepared("text", prompt(inp.text or "", task, inp.title), {"chars": len(inp.text or "")})
        rec, data = await hub.output(getattr(inp, kind), MAX_BYTES[kind])
        if rec.get("kind") not in ACCEPTS[kind]:
            other = rec.get("kind")
            fix = f"pass it as {{\"{other}\": ...}}" if other in ("image", "video", "audio") else \
                "embed takes images, audio and video outputs; pass text as {\"text\": ...}"
            raise HubError(422, f"output {rec.get('id')} is {other or 'of no kind'}, not {kind}", "wrong_kind", fix=fix)
        try:
            if kind == "image":
                p = await asyncio.to_thread(media.image, data)
            elif kind == "audio":
                p = await asyncio.to_thread(media.audio, data, settings.audio_max_s, tmp)
            else:
                p = await asyncio.to_thread(media.video, data, settings.video_max_frames, tmp)
        except media.MediaError as e:
            raise HubError(415, f"output {rec.get('id')}: {e}", "bad_media") from e
        p.info["output"] = rec.get("id")
        return p

    @app.post("/v1/embed", summary="Embed text, images, audio and video into one space")
    async def embed(body: EmbedRequest) -> Any:
        """Vectors are unit length at the size asked for (cosine = dot product), in input order. The first call
        loads the text path; the vision and audio encoders load on first use of those kinds."""
        if len(body.inputs) > settings.max_inputs:
            return JSONResponse({"detail": f"{len(body.inputs)} inputs; at most {settings.max_inputs} per call",
                                 "code": "too_many", "fix": "split the inputs over several calls"}, 413)
        t0 = time.perf_counter()
        try:
            prepared = [await prepare(i, body.task) for i in body.inputs]
            await make_room({p.kind for p in prepared})
        except HubError as e:
            return _error(e)
        batch = {"text": settings.batch_text, "image": settings.batch_media, "audio": 1, "video": 1}
        t1 = time.perf_counter()
        try:
            vecs = await asyncio.to_thread(enc.embed, [(p.kind, p.value) for p in prepared], body.dim, batch)
        except (FileNotFoundError, WorkerDied) as e:
            return backend_error(e)
        day["inputs"] += len(prepared)
        if lib is not None:
            lib.last_api = time.time()
        t2 = time.perf_counter()
        return {"model": MODEL_ID, "dim": body.dim, "task": body.task,
                "vectors": [[round(float(x), 6) for x in v] for v in vecs],
                "inputs": [{"kind": p.kind, **p.info} for p in prepared],
                "device": enc.backend.device, "dtype": enc.backend.dtype,
                "ms": {"prepare": round((t1 - t0) * 1000, 1), "encode": round((t2 - t1) * 1000, 1)}}

    return app
