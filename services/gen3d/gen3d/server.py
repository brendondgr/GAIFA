"""3DGenerate HTTP API. See README.md for the endpoint reference and curl examples."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from .config import settings
from .engines import ENGINES
from .events import Broadcaster
from .images import MAX_BYTES as MAX_IMAGE, ImageError, fetch_output, prepare as prepare_image
from .options import PRESETS, JobRequest, catalogue, parse_request
from .queue import Runner
from .store import TERMINAL, Store, job_folder, new_id

log = logging.getLogger("gen3d")
MESH_TYPES = {".glb", ".gltf", ".obj", ".ply", ".stl", ".off"}
MAX_UPLOAD = 300 * 1024 * 1024


def _make_worker():
    from .worker import WorkerPool
    if settings.fake_worker:
        from .worker_fake import SPEED, FakeWorker, fake_preview
        return WorkerPool(make=FakeWorker), fake_preview, 1.0 / SPEED
    from .preview import render_preview
    from .worker import CubeWorker
    return WorkerPool(make=CubeWorker), render_preview, 1.0


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store()
    worker, previewer, scale = _make_worker()
    events = Broadcaster()
    if settings.fake_worker:
        from .worker_fake import FakeComfyEngine
        comfy = FakeComfyEngine()
    else:
        from .comfy_engine import from_env
        comfy = from_env()                  # TRELLIS.2 and SAM 3D Body: through the hub to the comfy mod
    runner = Runner(store, worker, previewer, events, eta_scale=scale, comfy=comfy)
    app.state.store, app.state.runner, app.state.events = store, runner, events
    runner.start()
    if settings.preload:
        import asyncio
        asyncio.create_task(worker.load(["shape", "parts"]))
    yield
    await runner.stop()
    store.close()


app = FastAPI(title="3DGenerate", version=__version__, lifespan=lifespan,
              description="Text → 3D mesh (Cube3D v0.5) → named parts (CubePart) → game rig, with a job "
                          "queue, live progress and ETAs. Web UI at /ui/.")

app.add_middleware(  # loopback origins only, so arbitrary websites cannot drive the API
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_methods=["*"], allow_headers=["*"],
)
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="ui")


@app.middleware("http")
async def _revalidate_ui(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(ValidationError)
async def _validation(_, exc: ValidationError):
    return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)


def _store(request: Request) -> Store:
    return request.app.state.store


def _runner(request: Request) -> Runner:
    return request.app.state.runner


def _job_or_404(request: Request, jid: str) -> dict:
    job = _store(request).get_job(jid)
    if not job:
        raise HTTPException(404, f"no job {jid!r}")
    return job


# ---- info --------------------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/v1")
def info():
    return {"service": "3dgenerate", "version": __version__, "ui": "/ui/", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health(request: Request):
    r = _runner(request)
    w = r.worker.status()
    if r.worker.up and not r.current:
        idle = time.monotonic() - r.last_activity
        w.update(idle_s=round(idle, 1), unloads_in_s=round(max(0.0, settings.idle_unload_s - idle), 1)
                 if settings.idle_unload_s > 0 else None)
    return {"status": "ok", "version": __version__, "worker": w, "queue": r.health(),
            "idle_unload_s": settings.idle_unload_s, "data": str(settings.data),
            "cubeart": str(settings.cubeart), "fake_worker": settings.fake_worker}


@app.get("/v1/options")
def options():
    """Every setting with type, default, range and help; drives the UI's settings menu."""
    return catalogue()


@app.get("/v1/presets")
def presets():
    return PRESETS


@app.post("/v1/estimate")
async def estimate(request: Request):
    """How long a request would take if queued now (queue wait + its own stages), without queueing."""
    raw = await request.json()
    try:
        return _runner(request).estimate(raw)
    except ValidationError as exc:
        raise HTTPException(422, [e["msg"] for e in exc.errors()]) from exc


# ---- worker ------------------------------------------------------------------------------------

@app.post("/v1/load")
async def load(request: Request, models: str = Query("shape,parts", description="shape, parts or both")):
    r = _runner(request)
    wanted = [m for m in models.split(",") if m in ("shape", "parts")]
    r.last_activity = time.monotonic()      # before the worker starts: the idle unloader mustn't stop it mid-load
    await r.worker.load(wanted)
    r.last_activity = time.monotonic()
    r.events.publish("worker", r.worker.status())
    return r.worker.status()


@app.post("/v1/unload")
async def unload(request: Request, force: bool = Query(False, description="also cancel a running job")):
    r = _runner(request)
    if r.current:
        if not force:
            raise HTTPException(409, f"job {r.current} is running; pass force=true to cancel it and unload")
        await r.cancel(r.current)
    stopped = await r.worker.stop(reason="requested")
    r.events.publish("worker", r.worker.status())
    return {"stopped": stopped, **r.worker.status()}


# ---- jobs --------------------------------------------------------------------------------------

def _title(req, parent: dict | None = None, image_name: str | None = None) -> str:
    if req.title:
        return req.title
    if req.prompt.strip():
        return req.prompt.strip()[:80]
    if req.engine != "cube3d" and "shape" in req.stages:
        return f"{ENGINES[req.engine].label} · {Path(image_name or req.image or 'picture').stem}"[:80]
    base = " + ".join(req.stages)
    return f"{base} · {parent['title']}"[:80] if parent and parent.get("title") else base


def _resolve_chat(store: Store, chat_id: str | None, title: str) -> str | None:
    if chat_id == "new":
        return store.create_chat(title[:60])["id"]
    if chat_id and not store.get_chat(chat_id):
        raise HTTPException(404, f"no chat {chat_id!r}")
    return chat_id


def _queue(request: Request, raw: dict, jid: str | None = None, input_mesh: str | None = None,
           folder: str | None = None, image: bytes | None = None, image_name: str | None = None) -> dict:
    store, runner = _store(request), _runner(request)
    req = parse_request(raw)
    parent = store.get_job(req.parent_id) if req.parent_id else None
    if req.parent_id and not parent:
        raise HTTPException(404, f"no parent job {req.parent_id!r}")
    if req.image == "upload" and image is None and "shape" in req.stages and not parent:
        raise HTTPException(422, "image \"upload\" needs the picture: send it to POST /v1/jobs/image")
    title = _title(req, parent, image_name)
    chat_id = _resolve_chat(store, req.chat_id, title)
    req.chat_id = chat_id
    job = store.create_job(req.model_dump(), chat_id=chat_id, parent_id=req.parent_id, title=title,
                           stages=req.stages, jid=jid, folder=folder)
    if input_mesh:
        job = store.update_job(job["id"], input_mesh=input_mesh)
    if image is not None:
        try:
            prepare_image(image, store.job_dir(job["id"]))
        except ImageError as exc:
            store.delete_job(job["id"])
            raise HTTPException(422, str(exc)) from exc
    if chat_id and raw.get("chat_id") == "new":
        runner.events.publish("chat", store.get_chat(chat_id))
    runner.kick()
    runner.publish_job(job["id"])
    return runner.public(store.get_job(job["id"]))


@app.post("/v1/jobs", status_code=201)
async def create_job(request: Request, body: JobRequest):
    """Queue a job. Body = JobRequest (see /v1/options for every field). `chat_id: "new"` starts a chat
    titled from the prompt; `parent_id` continues from an earlier job's mesh or parts."""
    # `body` documents and validates the request; the raw JSON is queued, so a preset still applies
    # only under the options the caller left out (options.apply_preset).
    raw = await request.json()
    if not isinstance(raw, dict):
        raise HTTPException(422, "body must be a JSON object")
    req = parse_request(raw)
    image = None
    if req.engine != "cube3d" and "shape" in req.stages and (req.image or "").startswith("output:"):
        try:
            image = await fetch_output(req.image)
        except ImageError as exc:
            raise HTTPException(422, str(exc)) from exc
    return _queue(request, raw, image=image)


@app.post("/v1/jobs/image", status_code=201)
async def create_job_image(
    request: Request,
    image: UploadFile = File(..., description="the picture (PNG, JPEG, WebP; a transparent background is best)"),
    job: str = Form('{"engine": "hunyuan21"}', description="JobRequest JSON for an image engine (image is set to the upload)"),
):
    """Queue an image-engine job with the picture in the request (multipart). The job folder keeps it as
    input.png, and the cut-out every engine reads as input_rgba.png."""
    try:
        raw = json.loads(job)
    except ValueError as exc:
        raise HTTPException(422, f"job is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or (raw.get("engine") or "cube3d") == "cube3d":
        raise HTTPException(422, "pick an image engine: hunyuan21, trellis2, sam3d_objects or sam3d_body")
    raw["image"] = "upload"
    raw.setdefault("stages", ["shape", "preview"])
    data = await image.read()
    if not data or len(data) > MAX_IMAGE:
        raise HTTPException(400, "the picture is empty or larger than 64 MB")
    return _queue(request, raw, image=data, image_name=image.filename)


@app.post("/v1/jobs/upload", status_code=201)
async def create_job_upload(
    request: Request,
    mesh: UploadFile = File(..., description="mesh to split / rig: .glb .gltf .obj .ply .stl .off"),
    job: str = Form('{"stages": ["parts", "preview"]}', description="JobRequest JSON (without the shape stage)"),
):
    ext = Path(mesh.filename or "").suffix.lower()
    if ext not in MESH_TYPES:
        raise HTTPException(400, f"unsupported mesh type {ext or '(none)'}; use one of {sorted(MESH_TYPES)}")
    try:
        raw = json.loads(job)
    except ValueError as exc:
        raise HTTPException(422, f"job is not valid JSON: {exc}") from exc
    if "shape" in raw.get("stages", []):
        raise HTTPException(422, "an uploaded mesh replaces the shape stage; drop 'shape' from stages")
    raw.setdefault("title", Path(mesh.filename or "upload").stem)
    parse_request(raw)  # validate before writing anything
    jid = new_id("j_")
    folder = job_folder(jid, raw["title"])
    jdir = _store(request).jobs_dir / folder
    jdir.mkdir(parents=True, exist_ok=True)
    data = await mesh.read()
    if not data or len(data) > MAX_UPLOAD:
        shutil.rmtree(jdir, ignore_errors=True)
        raise HTTPException(400, "the mesh upload is empty or larger than 300 MB")
    (jdir / f"input{ext}").write_bytes(data)
    return _queue(request, raw, jid=jid, input_mesh=f"input{ext}", folder=folder)


@app.get("/v1/jobs")
def list_jobs(request: Request, chat_id: str | None = None,
              status: str | None = Query(None, description="e.g. queued,running"),
              limit: int = Query(100, ge=1, le=1000)):
    r = _runner(request)
    sched = r.schedule()
    return {"jobs": [r.public(j, sched) for j in _store(request).list_jobs(chat_id, status, limit)]}


@app.get("/v1/jobs/{jid}")
def get_job(request: Request, jid: str):
    return _runner(request).public(_job_or_404(request, jid))


@app.post("/v1/jobs/{jid}/cancel")
async def cancel_job(request: Request, jid: str):
    _job_or_404(request, jid)
    job = await _runner(request).cancel(jid)
    return _runner(request).public(job)


class RetryBody(BaseModel):
    new_seed: bool = True


@app.post("/v1/jobs/{jid}/retry", status_code=201)
async def retry_job(request: Request, jid: str, body: RetryBody | None = None):
    """Queue the same request again (same chat and parent); new_seed bumps the shape and parts seeds."""
    job = _job_or_404(request, jid)
    raw = dict(job["request"])
    if body is None or body.new_seed:
        raw["shape"] = {**raw.get("shape", {}), "seed": int(raw.get("shape", {}).get("seed", 0)) + 1}
        raw["parts"] = {**raw.get("parts", {}), "seed": int(raw.get("parts", {}).get("seed", 0)) + 1}
        eng = raw.get("engine") or "cube3d"
        if eng != "cube3d" and "seed" in (raw.get(eng) or {}):
            raw[eng] = {**raw[eng], "seed": int(raw[eng]["seed"]) + 1}
    raw["preset"] = None if (raw.get("engine") or "cube3d") == "cube3d" else raw.get("preset")
    if job.get("input_mesh") or raw.get("image") == "upload":  # an upload: the retry reads the original job's file
        raw["parent_id"] = jid
    if (raw.get("image") or "").startswith("output:") and "shape" in (raw.get("stages") or []):
        try:
            return _queue(request, raw, image=await fetch_output(raw["image"]))
        except ImageError as exc:
            raise HTTPException(422, str(exc)) from exc
    return _queue(request, raw)


@app.delete("/v1/jobs/{jid}")
async def delete_job(request: Request, jid: str):
    job = _job_or_404(request, jid)
    if job["status"] not in TERMINAL:
        await _runner(request).cancel(jid)
    _store(request).delete_job(jid)
    _runner(request).events.publish("deleted", {"id": jid, "chat_id": job.get("chat_id")})
    return {"deleted": jid}


@app.get("/v1/jobs/{jid}/files/{path:path}")
def job_file(request: Request, jid: str, path: str):
    _job_or_404(request, jid)
    root = _store(request).job_dir(jid).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, f"no file {path!r} in job {jid}")
    return FileResponse(target, filename=target.name)


@app.get("/v1/jobs/{jid}/download")
def job_zip(request: Request, jid: str, background: BackgroundTasks):
    job = _job_or_404(request, jid)
    root = _store(request).job_dir(jid)
    tmp = tempfile.NamedTemporaryFile(prefix=f"{jid}-", suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root))
        z.writestr("job.json", json.dumps({k: job[k] for k in ("id", "title", "request", "result", "stages",
                                                              "created", "finished")}, indent=2))
    tmp.close()
    background.add_task(Path(tmp.name).unlink, missing_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (job.get("title") or jid))[:50]
    return FileResponse(tmp.name, filename=f"{safe}-{jid}.zip", media_type="application/zip")


# ---- live updates ------------------------------------------------------------------------------

def _sse(stream) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/events")
def events(request: Request):
    """SSE: `job` (full job object on every change), `worker` (state), `deleted`, `chat`."""
    return _sse(request.app.state.events.stream())


@app.get("/v1/jobs/{jid}/events")
def job_events(request: Request, jid: str):
    _job_or_404(request, jid)
    return _sse(request.app.state.events.stream(lambda kind, d: kind == "job" and d.get("id") == jid))


# ---- chats -------------------------------------------------------------------------------------

class ChatBody(BaseModel):
    title: str = "New chat"


@app.get("/v1/chats")
def list_chats(request: Request):
    return {"chats": _store(request).list_chats()}


@app.post("/v1/chats", status_code=201)
def create_chat(request: Request, body: ChatBody | None = None):
    chat = _store(request).create_chat((body or ChatBody()).title)
    request.app.state.events.publish("chat", chat)
    return chat


@app.get("/v1/chats/{cid}")
def get_chat(request: Request, cid: str):
    chat = _store(request).get_chat(cid)
    if not chat:
        raise HTTPException(404, f"no chat {cid!r}")
    r = _runner(request)
    sched = r.schedule()
    jobs = sorted(_store(request).list_jobs(chat_id=cid, limit=1000), key=lambda j: j["created"])
    return {**chat, "jobs": [r.public(j, sched) for j in jobs]}


@app.patch("/v1/chats/{cid}")
def rename_chat(request: Request, cid: str, body: ChatBody):
    chat = _store(request).update_chat(cid, body.title)
    if not chat:
        raise HTTPException(404, f"no chat {cid!r}")
    request.app.state.events.publish("chat", chat)
    return chat


@app.delete("/v1/chats/{cid}")
async def delete_chat(request: Request, cid: str):
    store, r = _store(request), _runner(request)
    if not store.get_chat(cid):
        raise HTTPException(404, f"no chat {cid!r}")
    for j in store.list_jobs(chat_id=cid, status="queued,running"):
        await r.cancel(j["id"])
    deleted = store.delete_chat(cid)
    r.events.publish("deleted", {"chat_id": cid, "jobs": deleted})
    return {"deleted": cid, "jobs": deleted}


from . import hub  # noqa: E402  (the AIHub routes: status and the dashboard widget)

app.include_router(hub.router)
