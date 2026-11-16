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
from . import models
from .encoder import KINDS, Encoder, GemmaBackend, parts_for
from .switch import Switch, SwitchError
from .gpu import slot_for, take
from .gpu_slot import GpuCancelled, GpuSlot
from .models import NeedsFullModel
from .hubclient import Hub, HubError
from .settings import REPO, REVISION, Settings
from .worker import WorkerBackend, WorkerDied
from .api_chats import add_chat_routes
from .api_texts import add_text_routes
from .api_library import add_library_routes, backend_error
from .library import Library, open_library

log = logging.getLogger("embed")
MAX_BYTES = {"image": 64_000_000, "audio": 512_000_000, "video": 2_000_000_000}
ACCEPTS = {"image": {"image"}, "audio": {"audio", "video"}, "video": {"video"}}   # a video's soundtrack is audio


def _file(kind: str) -> Any:
    return Field(None, description=f"A GAIFA output ({kind}): `output:<id>` or the bare id",
                 json_schema_extra={"format": "gaifa-file", "x-kind": kind})


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
    dim: int | None = Field(None, description="The vector size: the model's own when left out; EmbeddingGemma 2 can be "
                            "cut to 512, 256 or 128 (Matryoshka). Queries and the documents they're scored against must match")
    task: Literal["query", "document"] = Field("document", description="query: a search query (gets the query "
                                               "prompt); document: what is searched. Media take no prompt")


class LoadRequest(BaseModel):
    kinds: list[Literal["text", "image", "audio", "video"]] = Field(
        default_factory=list, description="Also load the encoders these kinds need (text alone: 270M)")


def _error(e: HubError) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status)


def create_app(settings: Settings, encoder: Encoder | None = None, hub: Hub | None = None,
               library: Library | None = None, gpu: GpuSlot | None = None) -> FastAPI:
    """`library`: the index to run (tests pass their own); by default one is opened when `settings.index`."""
    enc = encoder or make_encoder(settings, model_info(settings))
    if enc.info.id == models.GEMMA and str(enc.info.folder) == ".":   # an encoder given without its folder (tests)
        enc.info = models.gemma(settings.model_dir)
    info_ = enc.info
    model_id = info_.id
    hub = hub or Hub(settings.hub_url)
    lib = library or (open_library(settings, enc, hub) if settings.index else None)
    gpu = gpu or (lib.gpu if lib is not None else slot_for(hub))     # the GPU slot (plan 31.3)
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
        if info_.id == models.GEMMA and (settings.model_dir / "model.safetensors").is_file():
            path = f"embed/{settings.model_dir.name}"
            res = await hub.register_model({"path": path, "name": "EmbeddingGemma 2", "kind": "text-encoder",
                                            "tags": ["embedding", "multimodal"],
                                            "source": {"type": "huggingface", "repo": REPO, "revision": REVISION}})
            log.info("models registry: %s %s", path, res)
        elif info_.id != models.GEMMA and models.weights(info_.folder):
            src = info_.extra.get("repo")
            res = await hub.register_model({"path": f"embed/{info_.id}", "name": info_.name, "kind": "text-encoder",
                                            "tags": ["embedding"], **({"source": {"type": "huggingface", "repo": src}} if src else {})})
            log.info("models registry: embed/%s %s", info_.id, res)

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
                  description="EmbeddingGemma 2 (or another model): text, code, images, audio and video in one space")
    app.state.library = lib
    switch = Switch(lib, lambda i: make_encoder(settings, i), on_done=hub.restart_me) if lib is not None else None
    app.state.switch = switch
    if lib is not None:
        add_library_routes(app, lib, enc)
        add_chat_routes(app, lib, enc)
        add_text_routes(app, lib, enc)                # structured-memory 2.1

    async def make_room(kinds: set[str]) -> None:
        """Loading another encoder while loaded needs more memory: ask the hub for the difference. (A load from
        unloaded is covered by [memory] triggers, which make room before the call reaches us.)"""
        want = enc.needs(kinds)
        if want is not None and enc.loaded:
            more = enc.estimate_gb(want) - enc.estimate_gb(enc.parts or frozenset())
            await hub.acquire(more, f"{info_.name} {enc.key(want)}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/info", summary="The model, its sizes, what is loaded and on which device")
    def info() -> dict:
        gem = info_.id == models.GEMMA
        return {"model": model_id, "name": info_.name, "repo": REPO if gem else info_.extra.get("repo"),
                "revision": REVISION if gem else info_.extra.get("revision"), "path": str(info_.folder),
                "weights": models.weights(info_.folder), "dim": info_.dim, "dims": list(info_.dims),
                "kinds": list(info_.kinds), "full": info_.full, "tasks": ["query", "document"], "loaded": enc.key(enc.parts) if enc.loaded else None,
                "device": enc.backend.device if enc.loaded else None, "dtype": enc.backend.dtype if enc.loaded else None,
                "limits": {"inputs": settings.max_inputs, "audio_s": settings.audio_max_s,
                           "video_frames": settings.video_max_frames}}

    @app.get("/v1/status", summary="Load state, busy, stats (architecture §4.6)")
    def status() -> dict:
        if day["date"] != date.today():
            day.update(date=date.today(), inputs=0)
        stats: list[dict] = [{"label": "Model", "value": info_.name}, {"label": "Inputs today", "value": day["inputs"], "reset": "daily"}]
        jobs: list[dict] = []
        sw = switch.status() if switch else None       # capability-enablement 7.3: a model switch is a job on the page
        if sw and sw["state"] == "building":
            total = (sw.get("done") or 0) + (sw.get("pending") or 0)
            jobs.append({"id": "switch", "label": f"Building {sw['name']}'s index ({sw.get('pending') or 0} to go); search uses {info_.name} until it's ready",
                         "state": "running", "progress": round((sw.get("done") or 0) / max(1, total), 3), "route": "#/settings/agent"})
        if lib is not None:
            c = lib.store.counts()
            stats.append({"label": "Indexed", "value": c["done"]})
            if (job := lib.job()) is not None:          # indexing, or waiting for the GPU (stage waiting_gpu)
                jobs.append(job)
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
        except (FileNotFoundError, WorkerDied, NeedsFullModel) as e:
            return backend_error(e)
        return {"loaded": enc.key(enc.parts), "device": enc.backend.device, "dtype": enc.backend.dtype,
                "memory_gb": enc.estimate_gb(enc.parts)}

    @app.post("/v1/unload", summary="Free the model's memory")
    async def unload() -> dict:
        return {"unloaded": await asyncio.to_thread(enc.unload)}

    async def prepare(inp: Input, task: str) -> media.Prepared:
        kind = inp.kind
        if kind == "text":
            return media.Prepared("text", enc.prompt(inp.text or "", task, inp.title), {"chars": len(inp.text or "")})
        if not info_.reads(kind):                       # a text-only model (7.3)
            raise models.NeedsFullModel(kind, info_.name)
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
        if body.dim is not None and body.dim not in info_.dims:
            return JSONResponse({"detail": f"{info_.name} gives vectors of {', '.join(map(str, info_.dims))}",
                                 "code": "bad_dim", "fix": "leave dim out for the model's own size"}, 422)
        try:
            prepared = [await prepare(i, body.task) for i in body.inputs]
        except HubError as e:
            return _error(e)
        except NeedsFullModel as e:
            return backend_error(e)
        batch = {"text": settings.batch_text, "image": settings.batch_media, "audio": 1, "video": 1}
        t1 = time.perf_counter()
        try:
            async with take(gpu, enc, settings.device, f"Embed {len(prepared)} input{'s' if len(prepared) != 1 else ''}"):
                await make_room({p.kind for p in prepared})               # slot first, then memory
                vecs = await asyncio.to_thread(enc.embed, [(p.kind, p.value) for p in prepared], body.dim, batch)
        except GpuCancelled as e:
            return JSONResponse({"detail": str(e), "code": "gpu_cancelled", "fix": "embed again"}, 409)
        except HubError as e:
            return _error(e)
        except (FileNotFoundError, WorkerDied, NeedsFullModel) as e:
            return backend_error(e)
        day["inputs"] += len(prepared)
        if lib is not None:
            lib.last_api = time.time()
        t2 = time.perf_counter()
        return {"model": model_id, "dim": body.dim or info_.dim, "task": body.task,
                "vectors": [[round(float(x), 6) for x in v] for v in vecs],
                "inputs": [{"kind": p.kind, **p.info} for p in prepared],
                "device": enc.backend.device, "dtype": enc.backend.dtype,
                "ms": {"prepare": round((t1 - t0) * 1000, 1), "encode": round((t2 - t1) * 1000, 1)}}

    @app.post("/v1/selftest", summary="Test the encoder on this machine: the first text, forty more, the device and memory")
    async def selftest() -> Any:
        """capability-enablement 7.2: real work, measured: one text (loading the model if needed), then forty; says it in
        one sentence (texts a second). Advice, never a gate."""
        batch = {"text": settings.batch_text, "image": settings.batch_media, "audio": 1, "video": 1}
        texts = [f"a short sentence about thing number {i}" for i in range(40)]
        try:
            async with take(gpu, enc, settings.device, "Embed: test"):
                await make_room({"text"})
                t0 = time.perf_counter()
                first = await asyncio.to_thread(enc.embed, [("text", "a red bicycle")], None, batch)
                first_s = time.perf_counter() - t0
                t1 = time.perf_counter()
                await asyncio.to_thread(enc.embed, [("text", t) for t in texts], None, batch)
                many_s = time.perf_counter() - t1
        except GpuCancelled as e:
            return JSONResponse({"detail": str(e), "code": "gpu_cancelled", "fix": "test again"}, 409)
        except HubError as e:
            return _error(e)
        except (FileNotFoundError, WorkerDied, NeedsFullModel) as e:
            return backend_error(e)
        dev = enc.backend.device
        rate = len(texts) / many_s if many_s > 0 else 0.0
        gb = enc.estimate_gb(frozenset())
        where = "your GPU" if dev not in ("cpu", None) else "the CPU"
        return {"passed": len(first) == 1, "model": model_id, "device": dev, "dtype": enc.backend.dtype,
                "first_s": round(first_s, 3), "forty_s": round(many_s, 3), "texts_per_s": round(rate, 1), "memory_gb": gb,
                "sentence": f"{info_.name} on {where}: {rate:.0f} texts a second, {gb:.1f} GB"}

    @app.get("/v1/models", summary="The models this mod can run, the one in use and a switch in progress")
    def list_models() -> dict:
        have = models.available(settings.models_root)
        if not any(m.id == info_.id for m in have):
            have.insert(0, info_)
        return {"model": info_.id, "models": [{**m.public(), "in_use": m.id == info_.id} for m in have],
                "switch": switch.status() if switch else None}

    @app.post("/v1/model", summary="Change the model: builds its index beside this one, then restarts on it")
    async def change_model(body: ModelChoice) -> Any:
        """Search keeps using the model in use until the new index is ready (capability-enablement 7.3)."""
        if switch is None:
            return JSONResponse({"detail": "the library is off (EMBED_INDEX=0)", "code": "no_library",
                                 "fix": "set EMBED_MODEL and restart the mod"}, 409)
        try:
            info = model_info(settings, body.model)
        except (FileNotFoundError, ValueError, KeyError) as e:
            return JSONResponse({"detail": str(e), "code": "no_model",
                                 "fix": "GET /v1/models lists the models this mod has; set one up with gaifa setup embed"}, 404)
        try:
            return {"switch": switch.start(info)}
        except SwitchError as e:
            return JSONResponse({"detail": e.detail, "code": e.code, "fix": e.fix}, 409)

    @app.delete("/v1/model/switch", summary="Stop a model switch; the model in use stays")
    def cancel_switch() -> dict:
        return {"cancelled": bool(switch and switch.cancel())}

    return app


class ModelChoice(BaseModel):
    model: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$", description="A model folder's id (GET /v1/models)")


def model_info(settings: Settings, mid: str | None = None) -> models.ModelInfo:
    """The model `mid`, else the one in use: the last finished switch, else EMBED_MODEL. A model that can't be read
    falls back to EmbeddingGemma 2 (logged) so the mod still starts."""
    want = mid or models.chosen(settings.state_dir, settings.model)
    folder = settings.model_dir if want == settings.model_dir.name else settings.models_root / want
    if mid is not None:
        return models.read(folder)
    try:
        info = models.read(folder)
    except (OSError, ValueError, KeyError) as e:
        log.warning("embed model %s can't be read (%s): using EmbeddingGemma 2", want, e)
        info = models.gemma(settings.model_dir)
    if not models.weights(info.folder):            # set up with another model alone: the first one that's there
        there = [m for m in models.available(settings.models_root) if models.weights(m.folder)]
        if there:
            log.info("embed model %s has no weights: using %s", info.id, there[0].id)
            return there[0]
    return info


def make_encoder(settings: Settings, info: models.ModelInfo) -> Encoder:
    if info.backend == "gemma":
        factory = functools.partial(GemmaBackend, info.folder, settings.device)
    else:
        factory = functools.partial(models.TextBackend, info, settings.device)
    return Encoder(WorkerBackend(factory), settings.state_dir, info)
