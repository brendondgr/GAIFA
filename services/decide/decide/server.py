"""The decide mod's API: POST /v1/decide (questions about an input, answered with a probability per answer and no
generated text), the models, load and unload, status. Images and videos come from the hub's outputs over HTTP."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from .engine import Decider, LocalBackend
from .gpu_slot import GpuCancelled, GpuSlot
from .hubclient import Hub, HubError
from .models import ADAPTERS
from .settings import Settings
from .worker import WorkerBackend, WorkerDied

log = logging.getLogger("decide")
MAX_BYTES = {"image": 16_000_000, "video": 256_000_000}
WITHIN_HEADER = "X-GAIFA-Answer-Within"


def answer_within(headers: Any) -> float | None:
    """`X-GAIFA-Answer-Within: <seconds>`: how long the caller gives the model once the GPU slot is held (the
    Auto judge and page screening, whose budget shouldn't run out while a job holds the GPU), or None."""
    try:
        s = float(headers.get(WITHIN_HEADER) or "")
    except ValueError:
        return None
    return s if 0 < s <= 3600 else None


def _quiet(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


VIDEO_MIME = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}


class Question(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Your name for the question; answers use it")
    type: Literal["yesno", "choice", "score"] = Field(description="yesno: probabilities for yes and no; choice: "
                                                      "one per option; score: one per level of `scale`")
    question: str = Field(min_length=1, max_length=4000, description="The question, about the input")
    options: list[str] | dict[str, str | None] | None = Field(
        None, description="choice only: 2–64 options, as names or {name: what it means}")
    scale: list[str] | None = Field(None, description="score only: 2–10 levels, lowest first, e.g. "
                                    "[\"none\", \"some\", \"a lot\"]")

    @model_validator(mode="after")
    def shape(self) -> "Question":
        if self.type == "choice":
            n = len(self.options or [])
            if not 2 <= n <= 64:
                raise ValueError(f"a choice question needs 2 to 64 options (got {n})")
            if any(not str(k).strip() for k in self.options):
                raise ValueError("choice options must be nonempty")
        elif self.options is not None:
            raise ValueError(f"options are for choice questions, not {self.type}")
        if self.type == "score":
            n = len(self.scale or [])
            if not 2 <= n <= 10 or len(set(self.scale)) != n:
                raise ValueError(f"a score question needs 2 to 10 distinct levels (got {n})")
        elif self.scale is not None:
            raise ValueError(f"scale is for score questions, not {self.type}")
        return self


class DecideRequest(BaseModel):
    input: str | dict[str, Any] | list[Any] = Field(description="What the questions are about: text, or JSON")
    questions: list[Question] = Field(min_length=1, description="Answered together, each on its own")
    images: list[str] = Field(default_factory=list, max_length=8, description="Images every question sees",
                              json_schema_extra={"items": {"type": "string", "format": "gaifa-file", "x-kind": "image"}})
    videos: list[str] = Field(default_factory=list, max_length=2, description="Videos every question sees "
                              "(2 frames a second, at most 32)",
                              json_schema_extra={"items": {"type": "string", "format": "gaifa-file", "x-kind": "video"}})
    model: str | None = Field(None, description="A model from GET /v1/models (default: the mod's default). "
                              "`<id>@<revision>` names the revision, which must be the pinned one")

    @model_validator(mode="after")
    def unique_ids(self) -> "DecideRequest":
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")
        return self


class LoadRequest(BaseModel):
    model: str | None = Field(None, description="The model to load (default: the mod's default)")


def _err(status: int, detail: str, code: str, fix: str | None = None, data: dict | None = None) -> JSONResponse:
    body: dict[str, Any] = {"detail": detail, "code": code}
    if fix:
        body["fix"] = fix
    if data:
        body["data"] = data
    return JSONResponse(body, status_code=status)


def create_app(settings: Settings, decider: Decider | None = None, hub: Hub | None = None,
               adapters: dict[str, type] | None = None, gpu: GpuSlot | None = None) -> FastAPI:
    adapters = adapters or ADAPTERS
    if decider is None:
        factory = functools.partial(LocalBackend, adapters, settings.models_dir, settings.device,
                                    settings.batch_size, settings.verify)
        decider = Decider(WorkerBackend(factory), settings.state_dir)
    dec = decider
    hub = hub or Hub(settings.hub_url)
    # The GPU slot (plan 31.3): each ask is interactive work, ordered with every other mod's GPU work.
    gpu = gpu or GpuSlot(hub_url=hub.url or "", service=hub.service, cls="interactive", transport=hub.transport)
    day = {"date": date.today(), "calls": 0}

    def on_cpu() -> bool:
        """The model runs (or will load) on the CPU: no slot to wait for."""
        return dec.backend.device == "cpu" if dec.loaded else settings.device == "cpu"

    def resolve(name: str | None) -> tuple[str | None, JSONResponse | None]:
        """A model id that may be loaded, or the error to answer with: unknown, another revision, changed code."""
        mid, _, rev = (name or settings.default_model).partition("@")
        cls = adapters.get(mid)
        if cls is None:
            return None, _err(404, f"no decision model {mid!r}", "unknown_model",
                              fix=f"use one of {sorted(adapters)} (GET /v1/models)")
        if rev and rev != cls.REVISION and not cls.REVISION.startswith(rev):
            return None, _err(409, f"{mid} revision {rev} isn't allowed: only {cls.REVISION[:12]}, whose code was "
                              "read, is", "unpinned_revision", fix=f"omit the revision, or pass {mid}@{cls.REVISION}")
        problems = cls.check(settings.models_dir / cls.FOLDER)
        if problems:
            missing = any(p.startswith("no weights") for p in problems)
            return None, _err(503 if missing else 409, f"{mid}: " + "; ".join(problems),
                              "no_weights" if missing else "unpinned_revision",
                              fix="run services/decide/install.sh" if missing else
                              "re-download the pinned revision with services/decide/install.sh --force "
                              "(see setup/decide.md: a new revision's code is read before it's allowed)")
        return mid, None

    async def idle_unloader() -> None:
        while True:
            await asyncio.sleep(10)
            if dec.idle_due(settings.idle_unload_s):
                log.info("idle for %.0f s: unloading", time.time() - dec.last_used)
                await asyncio.to_thread(dec.unload)

    async def register() -> None:
        for cls in adapters.values():
            folder = settings.models_dir / cls.FOLDER
            if (folder / cls.WEIGHTS).is_file():
                res = await hub.register_model({
                    "path": f"decide/{cls.FOLDER}", "name": cls.NAME, "kind": "other",
                    "tags": ["decision-model", "classification"],
                    "source": {"type": "huggingface", "repo": cls.REPO, "revision": cls.REVISION}})
                log.info("models registry: decide/%s %s", cls.FOLDER, res)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(idle_unloader()), asyncio.create_task(register())]
        yield
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(dec.unload)

    app = FastAPI(title="Decisions", version="0.1.0", lifespan=lifespan,
                  description="Decision models: questions about an input answered with probabilities, no text")

    async def make_room(mid: str) -> None:
        """Switching models while one is loaded needs the difference (a load from unloaded is covered by
        [memory] triggers, which make room before the call reaches us)."""
        if dec.loaded and dec.model != mid:
            await hub.acquire(dec.estimate_gb(mid) - dec.estimate_gb(dec.model), f"decision model {mid}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models", summary="The decision models: revision, inputs, weights present, loaded")
    def models() -> dict:
        out = []
        for mid, cls in adapters.items():
            problems = cls.check(settings.models_dir / cls.FOLDER)
            out.append({"id": mid, "name": cls.NAME, "repo": cls.REPO, "revision": cls.REVISION,
                        "license": cls.LICENSE, "params": cls.PARAMS, "inputs": list(cls.INPUTS),
                        "path": f"decide/{cls.FOLDER}", "usable": not problems, "problems": problems,
                        "loaded": dec.model == mid, "default": mid == settings.default_model,
                        "memory_estimate_gb": dec.estimate_gb(mid)})
        return {"models": out, "question_types": ["yesno", "choice", "score"]}

    @app.get("/v1/status", summary="Load state, busy, stats (architecture §4.6)")
    def status() -> dict:
        if day["date"] != date.today():
            day.update(date=date.today(), calls=0)
        avg = round(sum(dec.recent_ms) / len(dec.recent_ms), 1) if dec.recent_ms else 0
        stats: list[dict] = [{"label": "Calls today", "value": day["calls"], "reset": "daily"},
                             {"label": "Questions", "value": dec.questions},
                             {"label": "Latency", "value": avg, "unit": "ms"}]
        if dec.loaded:
            stats.append({"label": "Loaded", "value": f"{dec.model} ({'GPU' if dec.backend.device == 'cuda' else 'CPU'})"})
        return {"loaded": dec.loaded, "busy": dec.busy or dec.loading, "idle_s": round(time.time() - dec.last_used, 1),
                "memory_estimate_gb": dec.estimate_gb(dec.model or settings.default_model), "stats": stats, "jobs": []}

    def backend_error(e: Exception) -> JSONResponse:
        if isinstance(e, PermissionError):
            return _err(409, str(e), "unpinned_revision", fix="see setup/decide.md, The remote code")
        if isinstance(e, FileNotFoundError):
            return _err(503, str(e), "no_weights", fix="run services/decide/install.sh")
        log.error("%s", e)
        if isinstance(e, WorkerDied):
            return _err(503, str(e), "worker_died",
                        fix="call again (it starts a new worker); if it repeats, read `gaifa logs decide`")
        return _err(503, str(e), "model_error", fix="the model failed on this input; read `gaifa logs decide`")

    @app.post("/v1/load", summary="Load a decision model")
    async def load(body: LoadRequest | None = None) -> Any:
        mid, err = resolve(body.model if body else None)
        if err:
            return err
        try:
            await make_room(mid)
            await asyncio.to_thread(dec.load, mid)
        except HubError as e:
            return JSONResponse(e.body(), status_code=e.status)
        except (PermissionError, FileNotFoundError, WorkerDied, RuntimeError) as e:
            return backend_error(e)
        return {"loaded": mid, "device": dec.backend.device, "dtype": dec.backend.dtype,
                "memory_gb": dec.estimate_gb(mid)}

    @app.post("/v1/unload", summary="Free the model's memory")
    async def unload() -> dict:
        return {"unloaded": await asyncio.to_thread(dec.unload)}

    async def media(refs: list[str], kind: str) -> list[Any]:
        out = []
        for ref in refs:
            rec, data = await hub.output(ref, MAX_BYTES[kind])
            if rec.get("kind") != kind:
                raise HubError(422, f"output {rec.get('id')} is {rec.get('kind') or 'of no kind'}, not {kind}",
                               "wrong_kind", fix=f"pass {kind} outputs in `{kind}s`")
            if kind == "image":
                out.append(data)
            else:
                name = str(rec.get("path") or rec.get("name") or "")
                ext = name[name.rfind("."):].lower() if "." in name else ".mp4"
                out.append((VIDEO_MIME.get(ext, "video/mp4"), data))
        return out

    @app.post("/v1/decide", summary="Ask questions about an input: a probability per answer, no generated text")
    async def decide(body: DecideRequest, request: Request) -> Any:
        """yesno answers `{probs: {yes, no}, top, p}`; choice one probability per option; score one per level plus
        `value` (the expected level, 0 = the first). `p` is the top answer's probability: compare it with your own
        threshold. A question the model couldn't answer gets `{error, message}`; the others are still answered."""
        if len(body.questions) > settings.max_questions:
            return _err(413, f"{len(body.questions)} questions; at most {settings.max_questions} per call",
                        "too_many", fix="split the questions over several calls")
        size = len(body.input) if isinstance(body.input, str) else len(str(body.input))
        if size > settings.max_input_chars:
            return _err(413, f"the input has {size} characters; at most {settings.max_input_chars}", "too_large",
                        fix="pass the part the questions are about")
        mid, err = resolve(body.model)
        if err:
            return err
        cls = adapters[mid]
        for kind, refs in (("image", body.images), ("video", body.videos)):
            if refs and kind not in cls.INPUTS:
                return _err(422, f"{mid} doesn't read {kind}s", "unsupported_input", fix="ask about text only")
        t0 = time.perf_counter()
        try:
            images = await media(body.images, "image")
            videos = await media(body.videos, "video")
        except HubError as e:
            return JSONResponse(e.body(), status_code=e.status)
        questions = [q.model_dump(exclude_none=True) for q in body.questions]
        label = f"{mid}: {len(questions)} question{'s' if len(questions) != 1 else ''}"
        within, started = answer_within(request.headers), asyncio.Event()

        async def work() -> tuple[dict, float]:
            async with (contextlib.nullcontext() if on_cpu() else gpu.slot(label, est_s=1)):   # slot first, then memory
                started.set()
                await make_room(mid)
                return await asyncio.to_thread(dec.ask, mid, body.input, questions, images or None, videos or None)

        task = asyncio.create_task(work())
        try:
            if within is not None:                  # the caller's budget starts once the slot is held
                waiter = asyncio.ensure_future(started.wait())
                await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()
                done, _ = await asyncio.wait({task}, timeout=within)
                if not done:                        # it finishes in the background, holding the slot until then
                    task.add_done_callback(_quiet)
                    return _err(504, f"no answer within {within:g} s (after the GPU slot)", "answer_timeout",
                                fix="give it more time, or ask again")
            answers, ms = await task
        except GpuCancelled as e:
            return _err(409, str(e), "gpu_cancelled", fix="ask again")
        except HubError as e:
            return JSONResponse(e.body(), status_code=e.status)
        except (PermissionError, FileNotFoundError, WorkerDied, RuntimeError) as e:
            return backend_error(e)
        except ValueError as e:
            return _err(422, str(e), "invalid_input")
        day["calls"] += 1
        return {"model": mid, "revision": cls.REVISION, "answers": answers, "device": dec.backend.device,
                "ms": round((time.perf_counter() - t0) * 1000, 1), "model_ms": round(ms, 1)}

    return app
