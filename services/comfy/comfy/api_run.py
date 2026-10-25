"""Running packs: /v1/run, /v1/jobs, /v1/queue, /v1/defaults, /v1/uploads, /v1/files (plan 11.7)."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()
HEADER = "x-gaifa-make-room"
GPU_LEASE = "x-gaifa-gpu-lease"     # a caller holding the GPU slot (gen3d) hands its lease down: run under it


class RunRequest(BaseModel):
    workflow: str = Field(description="A pack id (GET /v1/workflows)")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Values for the pack's inputs (its schema)")
    preset: str | None = Field(None, description="A preset from the pack's workflow.toml, applied before `inputs`")


class DefaultsBody(BaseModel):
    defaults: dict[str, str | None] = Field(description="task → pack id (null clears it)")


def _job(run: dict, runner=None) -> dict:
    run = runner.annotate(run) if runner is not None else run
    out = {k: run.get(k) for k in ("id", "workflow", "label", "state", "progress", "inputs", "outputs", "error",
                                   "created", "started", "finished", "peak_gb", "prompt_id")}
    if run.get("stage"):                          # "waiting_gpu", with what runs before it (plan 31.3)
        out.update(stage=run["stage"], ahead=run.get("ahead") or [], eta_s=run.get("eta_s"))
    if run.get("live"):                           # plan 45.1: steps and the newest preview frame
        out["live"] = run["live"]
    return out


def _parent(request: Request) -> str | None:
    return (request.headers.get(GPU_LEASE) or "").strip() or None


@router.post("/v1/run", status_code=202, summary="Run a workflow pack; returns its job (poll /v1/jobs/{id}?wait=…)")
async def run(request: Request, body: RunRequest) -> dict:
    make_room = request.headers.get(HEADER, "").lower() in ("1", "true", "yes")
    runner = request.app.state.runner
    r = await runner.submit(body.workflow, body.inputs, body.preset, make_room, parent=_parent(request))
    return _job(r, runner)


@router.get("/v1/jobs", summary="Recent runs, newest first")
def jobs(request: Request, limit: int = Query(50, ge=1, le=500), workflow: str | None = None) -> dict:
    return {"jobs": [_job(r, request.app.state.runner) for r in request.app.state.db.runs(workflow=workflow, limit=limit)]}


@router.get("/v1/jobs/{job_id}", summary="One run; ?wait=<seconds> waits until it finishes (up to that long)")
async def job(request: Request, job_id: str, wait: float = Query(0, ge=0, le=1800),
              live: bool = Query(False, description="With wait: also answer at the run's next step or preview frame (plan 45.5)")) -> dict:
    r = await request.app.state.runner.wait(job_id, wait, live)
    if r is None:
        raise HTTPException(404, f"no job {job_id!r}")
    return _job(r, request.app.state.runner)


@router.get("/v1/runs/{run_id}/preview", summary="A running run's newest preview frame; ?after=<seq> waits up to 5 s for a newer one (204: none)",
            responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}, 204: {"description": "No newer frame"}})
async def preview(request: Request, run_id: str, after: int = Query(0, ge=0), wait: float = Query(5, ge=0, le=20)) -> Response:
    fr = await request.app.state.runner.previews.wait(run_id, after, wait)
    if fr is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return Response(fr["data"], media_type=fr["mime"], headers={"X-Seq": str(fr["seq"]), "Cache-Control": "no-store"})


@router.get("/v1/queue", summary="Runs waiting or running, and ComfyUI's own queue")
async def queue(request: Request) -> dict:
    st = request.app.state
    ctl = st.control
    return {"jobs": [_job(r, st.runner) for r in st.db.runs(states=("queued", "running"), limit=100)],
            "comfyui": {"running": len(ctl.running), "pending": len(ctl.pending), "up": ctl.up}}


@router.post("/v1/queue/{job_id}/cancel", summary="Cancel a waiting or running run")
async def cancel(request: Request, job_id: str) -> dict:
    try:
        return _job(await request.app.state.runner.cancel(job_id), request.app.state.runner)
    except KeyError:
        raise HTTPException(404, f"no job {job_id!r}") from None


@router.get("/v1/defaults", summary="The default pack for each task")
def get_defaults(request: Request) -> dict:
    return {"defaults": request.app.state.db.defaults()}


@router.put("/v1/defaults", summary="Set (or clear, with null) the default pack per task")
def put_defaults(request: Request, body: DefaultsBody) -> dict:
    st = request.app.state
    for task, wid in body.defaults.items():
        if task not in st.library.tasks.tasks:
            raise HTTPException(422, f"no task {task!r}")
        if wid is not None:
            p = st.library.packs.get(wid)
            if p is None or p.draft or p.task != task:
                raise HTTPException(422, f"{wid!r} isn't a ready pack for {task}")
        st.db.set_default(task, wid)
    return {"defaults": st.db.defaults()}


@router.post("/v1/uploads", summary="Upload an input file; use the returned value (upload:<name>) as a file input")
async def upload(request: Request, file: UploadFile) -> dict:
    s = request.app.state.settings
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "upload").name)[-80:] or "upload"
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{stem}"
    d = s.input / "gaifa"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(await file.read())
    return {"value": f"upload:{name}", "name": name}


@router.get("/v1/files/{path:path}", summary="A result file (a path from a job's outputs)")
def files(request: Request, path: str):
    root = request.app.state.settings.outputs.parent.resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(request.app.state.settings.outputs.resolve()) or not p.is_file():
        raise HTTPException(404, "no such result file")
    return FileResponse(p)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")   # arguments sent flat by mistake must fail, not run the defaults
    arguments: dict[str, Any] = Field(default_factory=dict, description="The tool's arguments (its parameters schema)")


@router.get("/v1/tools", summary="Agent tools: one per task with a ready workflow, plus list_workflows and run_workflow")
def tools(request: Request) -> dict:
    from .tools import catalog
    st = request.app.state
    return {"tools": catalog(st.library, st.db.defaults())}


def fill_references(required: list[str], args: dict[str, Any]) -> dict[str, Any]:
    """Required extra reference images (`image_2`, …) the caller didn't give → the main image."""
    return {k: args["image"] for k in required if k not in args and args.get("image") and re.fullmatch(r"image_\d+", k)}


@router.post("/v1/tools/{name}/call", summary="Call an agent tool; image and video tools return a job")
async def call_tool(request: Request, name: str, body: ToolCall) -> dict:
    from .resolve import InputError
    from .tools import list_workflows, pick
    st = request.app.state
    lib, args = st.library, dict(body.arguments)
    make_room = request.headers.get(HEADER, "").lower() in ("1", "true", "yes")
    if name == "list_workflows":
        return {"workflows": list_workflows(lib)}
    if name == "run_workflow":
        lib.packs.scan()
        hidden = lib.packs.get(args.get("workflow", ""))
        if hidden is not None and hidden.manifest and not hidden.manifest.agent:
            raise InputError(f"{hidden.id} isn't offered to the agent")
        covered = lib.tasks.get(hidden.task) if hidden is not None and hidden.manifest else None
        if covered is not None and covered.tool:          # plan 20.5: a task tool runs it, with its checks and card
            raise InputError(f"{hidden.id} is {'an' if hidden.task[0] in 'aeiou' else 'a'} {hidden.task} workflow: call {covered.tool} "
                             f"with workflow={hidden.id!r} instead of run_workflow")
        r = await st.runner.submit(args.get("workflow", ""), args.get("inputs") or {}, args.get("preset"), make_room,
                                   parent=_parent(request))
        return {"status": "running", "job_id": r["id"], "workflow": r["workflow"]}
    task = next((t for t in lib.tasks.tasks.values() if t.tool == name), None)
    if task is None:
        raise HTTPException(404, f"no tool {name!r}")
    preset = args.pop("preset", None)
    refs = args.pop("references", None) or []
    try:
        pack = pick(lib, task.id, args.pop("workflow", None), st.db.defaults(), args.pop("edit", None))
    except ValueError as e:
        raise InputError(str(e)) from None
    if preset and preset not in pack.manifest.presets:
        raise InputError(f"{pack.id} has no preset {preset!r} (it has: {', '.join(pack.manifest.presets) or 'none'})")
    conv, _ = lib.analysed(pack)
    from .schema import input_schema
    sch = input_schema(pack, conv, lib.catalog, lib.tasks)
    takes = set(sch["properties"])
    ignored = sorted(set(args) - takes)
    # A workflow that wants more reference images than the task tool offers (qwen21-edit-multi's
    # image_2): the main image stands in, so a plain edit still runs.
    slots = sorted((k for k in takes if re.fullmatch(r"image_\d+", k)), key=lambda k: int(k.split("_")[1]))
    if len(refs) > len(slots):
        raise InputError(f"{pack.id} takes {len(slots)} reference picture(s), not {len(refs)}")
    args.update(dict(zip(slots, refs)))         # references → image_2, image_3, … (plan 20.3)
    filled = fill_references(sch.get("required", []), args)
    r = await st.runner.submit(pack.id, {**{k: v for k, v in args.items() if k in takes}, **filled}, preset or None, make_room,
                               parent=_parent(request))
    out = {"status": "running", "job_id": r["id"], "workflow": pack.id, **({"preset": preset} if preset else {})}
    if filled:
        out["filled"] = {k: "the main image" for k in filled}
    if ignored:
        out["ignored"] = ignored                  # shared inputs this workflow doesn't have
    return out
