"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import api_profiles
from .downloads import Downloads
from .engine import STAGE_ORDER, Engine, EngineError
from .hubclient import Hub, NeedsRoom
from .metrics import Sampler
from .profiles import load_profiles
from .relay import Relay
from .settings import Settings

log = logging.getLogger("vllm")
YES = {"1", "true", "yes"}


class LoadRequest(BaseModel):
    profile: str | None = Field(None, description="A profile id (default: the loaded one, else the last loaded)")


class DownloadRequest(BaseModel):
    profile: str = Field(description="The profile whose model to download")


def create_app(settings: Settings | None = None, engine: Engine | None = None,
               downloads: Downloads | None = None, relay: Relay | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        st = app.state
        st.settings = settings
        hub = Hub(settings.hub_url)
        st.engine = eng = engine or Engine(settings, hub)
        st.downloads = dl = downloads or Downloads(settings, eng.hub)

        async def ensure_files(p):
            if not dl.local_commit(p):
                eng.stage = "downloading"
                await dl.ensure(p)
        eng.before_start.append(ensure_files)
        st.relay = rel = relay or (Relay(settings) if settings.relay_url else None)
        if rel:
            eng.on_ready.append(rel.publish)
            eng.on_stopping.append(rel.withdraw)
        st.sampler = sampler = Sampler(eng.http)

        async def sample_on(p):
            sampler.start()

        async def sample_off(p):
            sampler.stop()
        eng.on_ready.append(sample_on)
        eng.on_stopping.append(sample_off)
        await eng.adopt()
        if rel:
            await rel.reconcile(eng.profile)
        try:
            yield
        finally:
            await eng.shutdown(stop_engine=getattr(st, "stop_engine_on_exit", True))
            if rel:
                await rel.close()

    app = FastAPI(title="vLLM", version="0.1.0", lifespan=lifespan,
                  description="Runs vLLM in kyuz0's gfx1151 image, one model profile at a time.")

    app.include_router(api_profiles.router)

    @app.exception_handler(EngineError)
    async def _engine_error(_: Request, e: EngineError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, "data": e.data}, e.status)

    @app.exception_handler(NeedsRoom)
    async def _needs_room(_: Request, e: NeedsRoom) -> JSONResponse:
        return JSONResponse(e.body, 409)          # the hub's body: {detail, code: needs_room, data: {plan}}

    @app.get("/health")
    def health() -> dict:
        """GAIFA polls this: the adapter is up (the engine's own state is in /v1/status)."""
        return {"status": "ok"}

    @app.get("/v1/profiles", summary="The model profiles")
    def profiles(request: Request) -> dict:
        found, problems = load_profiles(request.app.state.settings.profiles_dir)
        eng: Engine = request.app.state.engine
        dl: Downloads = request.app.state.downloads
        rows = [{**p.model_dump(), "downloaded": dl.local_commit(p), "local_bytes": dl.local_bytes(p),
                 "download": dl.jobs[p.id].view() if p.id in dl.jobs else None} for p in found.values()]
        return {"profiles": rows, "problems": problems,
                "loaded": eng.profile.id if eng.profile else None, "last": eng.last_profile()}

    @app.post("/v1/downloads", summary="Download a profile's model (without loading it)", status_code=202)
    async def download(request: Request, body: DownloadRequest) -> dict:
        found, _ = load_profiles(request.app.state.settings.profiles_dir)
        if body.profile not in found:
            raise EngineError(404, "not_found", f"no profile {body.profile!r}", {"profiles": list(found)})
        return (await request.app.state.downloads.start(found[body.profile])).view()

    @app.get("/v1/downloads", summary="Downloads in this run of the adapter")
    def downloads_list(request: Request) -> dict:
        return {"downloads": request.app.state.downloads.views()}

    @app.post("/v1/load", summary="Start vLLM with a profile (stops the running one first)")
    async def load(request: Request, body: LoadRequest | None = None,
                   wait: bool = Query(True, description="Answer once vLLM is ready (else at once)"),
                   make_room: bool = Query(False, description="Let GAIFA unload idle mods for the memory")) -> dict:
        room = make_room or request.headers.get("x-gaifa-make-room", "").strip().lower() in YES
        return await request.app.state.engine.load(body.profile if body else None, make_room=room, wait=wait)

    @app.post("/v1/unload", summary="Stop vLLM")
    async def unload(request: Request) -> dict:
        return await request.app.state.engine.unload()

    @app.get("/v1/engine", summary="The engine: state, stage, profile, command line")
    def engine_view(request: Request) -> dict:
        rel = request.app.state.relay
        return {**request.app.state.engine.view(), "relay": rel.view() if rel else None}

    @app.get("/v1/engine/logs", summary="The engine's last log lines")
    def engine_logs(request: Request, tail: int = Query(200, ge=1, le=500)) -> dict:
        return {"lines": list(request.app.state.engine.lines)[-tail:]}

    @app.get("/v1/status", summary="Load state, stats and jobs (architecture §4.6)")
    def status(request: Request) -> dict:
        st = request.app.state
        eng: Engine = st.engine
        p = eng.default_profile()
        ready = eng.state == "ready"
        m = st.sampler.view() if ready else {}
        kv = m.get("kv_cache")
        stats = [
            {"label": "Model", "value": eng.profile.served if eng.profile and eng.state != "failed" else "none"},
            {"label": "Tokens/s", "value": m.get("tokens_per_s", 0.0), "unit": "tok/s"},
            {"label": "Requests", "value": int(m.get("running") or 0), "hint": f"{int(m.get('waiting') or 0)} waiting"},
            {"label": "KV cache", "value": round(100 * kv, 1) if kv is not None else 0.0, "unit": "%"},
        ]
        return {"loaded": ready, "busy": st.sampler.busy if ready else False,
                "idle_s": m.get("idle_s") if ready else None,
                "memory_estimate_gb": eng.needs_gb(p) if p else None, "stats": stats,
                "jobs": _jobs(eng, st.downloads)}

    return app


RECENT_S = 600       # finished jobs stay in the header's jobs chip this long


def _jobs(eng: Engine, dl: Downloads) -> list[dict]:
    now, route = time.time(), "#/s/vllm/profiles"
    jobs = []
    for d in dl.jobs.values():
        if d.state == "running" or (d.finished and now - d.finished < RECENT_S):
            jobs.append({"id": f"download-{d.profile}-{int(d.started)}", "label": f"Download {d.repo}",
                         "progress": d.progress, "state": {"running": "running", "done": "done"}.get(d.state, "failed"),
                         "route": route})
    if eng.started_at and eng.profile:
        jid, name = f"start-{eng.profile.id}-{int(eng.started_at)}", eng.profile.name
        if eng.state == "starting":
            order = ["preparing", "downloading", "waiting for memory", *STAGE_ORDER]
            i = order.index(eng.stage) if eng.stage in order else 0
            jobs.append({"id": jid, "label": f"Start {name}: {eng.stage}", "progress": round(i / len(order), 2),
                         "state": "running", "route": route})
        elif eng.state == "ready" and eng.ready_at and now - eng.ready_at < RECENT_S:
            jobs.append({"id": jid, "label": f"Start {name}", "progress": 1.0, "state": "done", "route": route})
        elif eng.state == "failed" and eng.failed_at and now - eng.failed_at < RECENT_S:
            jobs.append({"id": jid, "label": f"Start {name}: {eng.error}", "progress": None, "state": "failed",
                         "route": route})
    return jobs
