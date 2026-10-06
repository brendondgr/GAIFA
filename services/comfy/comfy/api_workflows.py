"""/v1/workflows and /v1/tasks: the packs, their schemas and their check results."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

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


@router.get("/v1/workflows", summary="Every workflow pack and draft, with its task and check state")
def list_workflows(request: Request) -> dict:
    lib = _lib(request)
    items = [lib.brief(p) for p in lib.packs.all()]
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


@router.get("/v1/workflows/{wid}/preview", summary="The workflow's card image")
def preview(request: Request, wid: str):
    _, p = _pack(request, wid)
    if not p.preview:
        raise HTTPException(404, "no preview")
    return FileResponse(p.preview)


@router.get("/v1/tasks", summary="The tasks packs implement, and the shared input names")
def tasks(request: Request) -> dict:
    t = request.app.state.library.tasks
    return {"tasks": {k: {"name": v.name, "description": v.description, "required": list(v.required), "output": v.output,
                          "tool": v.tool} for k, v in t.tasks.items()},
            "inputs": t.inputs}
