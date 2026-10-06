"""/v1/workflows and /v1/tasks: the packs, their schemas and their check results."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
import shutil
import subprocess
from pathlib import Path

router = APIRouter()


def _lib(request: Request):
    lib = request.app.state.library
    lib.packs.scan()
    return lib


def _pack(request: Request, wid: str):
    lib = _lib(request)
    p = lib.packs.get(wid)
    if p is None:
        raise HTTPException(404, f"no workflow {wid!r}")
    return lib, p


def _newest_image(request: Request, wid: str) -> Path | None:
    """The newest image a pack made (or a frame of its newest video), as its card picture when it
    has no preview of its own. Video frames are cached in data/previews/."""
    s = request.app.state.settings
    for r in request.app.state.db.runs(states=("done",), workflow=wid, limit=10):
        for o in r.get("outputs") or []:
            p = s.outputs.parent / o["path"]
            if not p.is_file():
                continue
            if o.get("kind") == "image":
                return p
            if o.get("kind") == "video":
                poster = s.data / "previews" / f"{r['id']}.jpg"
                if not poster.exists() and shutil.which("ffmpeg"):
                    poster.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", "0.5", "-i", str(p), "-frames:v", "1",
                                    "-vf", "scale=480:-2", str(poster)], timeout=30, check=False)
                if poster.exists():
                    return poster
    return None


def _brief(request: Request, lib, p) -> dict:
    b = lib.brief(p)
    if not b["preview"] and _newest_image(request, p.id):
        b["preview"] = f"/v1/workflows/{p.id}/preview"
    return b


@router.get("/v1/workflows", summary="Every workflow pack and draft, with its task and check state")
def list_workflows(request: Request) -> dict:
    lib = _lib(request)
    items = [_brief(request, lib, p) for p in lib.packs.all()]
    order = {"ready": 0, "broken": 1, "draft": 2}
    items.sort(key=lambda w: (order[w["state"]], w["task"], w["name"].lower()))
    return {"workflows": items, "defaults": request.app.state.db.defaults()}


@router.get("/v1/workflows/{wid}", summary="One workflow: its input schema, mapping, presets, issues and nodes")
def get_workflow(request: Request, wid: str) -> dict:
    lib, p = _pack(request, wid)
    return lib.detail(p)


@router.get("/v1/workflows/{wid}/check", summary="Check one workflow against the installed nodes and models")
async def check_workflow(request: Request, wid: str) -> dict:
    lib, p = _pack(request, wid)
    await lib.refresh_models(force=True)
    _, issues = lib.analysed(p)
    return {"id": p.id, "state": lib.state(p, issues), "issues": [i.json() for i in issues]}


@router.get("/v1/workflows/{wid}/suggest", summary="A drafted workflow.toml: detected inputs, outputs, task and memory")
def suggest(request: Request, wid: str) -> dict:
    lib, p = _pack(request, wid)
    s, toml = lib.suggest(p)
    if s is None:
        _, issues = lib.analysed(p)
        raise HTTPException(422, "the workflow can't be converted: " + "; ".join(i.detail for i in issues if i.level == "error"))
    return {"id": p.id, "manifest": s.manifest, "toml": toml, "notes": s.notes, "why": s.why}


@router.get("/v1/workflows/{wid}/preview", summary="The workflow's card image (its preview, else its newest image)")
def preview(request: Request, wid: str):
    _, p = _pack(request, wid)
    f = p.preview or _newest_image(request, wid)
    if not f:
        raise HTTPException(404, "no preview")
    return FileResponse(f, headers={"Cache-Control": "max-age=60"})


@router.get("/v1/tasks", summary="The tasks packs implement, and the shared input names")
def tasks(request: Request) -> dict:
    t = request.app.state.library.tasks
    return {"tasks": {k: {"name": v.name, "description": v.description, "required": list(v.required), "output": v.output,
                          "tool": v.tool} for k, v in t.tasks.items()},
            "inputs": t.inputs}
