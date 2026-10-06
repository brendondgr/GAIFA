"""Importing, saving and deleting packs, and model downloads (plan 11.8)."""

from __future__ import annotations

import os
import shutil
import time
import tomllib
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from . import importer
from .client import ComfyError
from .detect import Suggestion, to_toml
from .packs import MANIFEST, Manifest

router = APIRouter()
MAX_UPLOAD = 600 * 1024 * 1024


class SaveBody(BaseModel):
    toml: str | None = Field(None, description="workflow.toml text, saved as written (comments kept)")
    manifest: dict[str, Any] | None = Field(None, description="…or the manifest as JSON (written as TOML)")


class HistoryImport(BaseModel):
    id: str | None = Field(None, description="The new pack's id (default: from the workflow)")


class DownloadBody(BaseModel):
    url: str = Field(description="An https URL of the model file")
    folder: str = Field(description="The models/ folder it goes in: diffusion_models, text_encoders, vae, loras, …")
    name: str | None = Field(None, description="The file name (default: from the URL)")


def _imported(request: Request, pid: str) -> dict:
    lib = request.app.state.library
    p = lib.packs.get(pid)
    s, toml = lib.suggest(p)
    return {"id": pid, "workflow": lib.detail(p), "suggestion": {"manifest": s.manifest, "toml": toml, "notes": s.notes} if s else None}


@router.post("/v1/import", status_code=201, summary="Import a workflow file (JSON, PNG, WebP, MP4/WebM, or a zip) as a draft pack")
async def import_file(request: Request, file: UploadFile, id: str | None = Form(None)) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    lib = request.app.state.library
    try:
        found = importer.read_file(file.filename or "workflow.json", data)
        pid = importer.create(lib.packs, lib.catalog, found, id, file.filename or "workflow")
    except importer.ImportError_ as e:
        raise HTTPException(422, e.detail) from None
    return _imported(request, pid)


@router.get("/v1/import/history", summary="ComfyUI's recent runs, to import one (exact graphs)")
async def history(request: Request) -> dict:
    try:
        h = await request.app.state.client.history(max_items=40)
    except ComfyError as e:
        raise HTTPException(503, "ComfyUI isn't running: load comfy to see its history") from e
    return {"items": importer.history_list(h)}


@router.post("/v1/import/history/{prompt_id}", status_code=201, summary="Import one of ComfyUI's past runs as a draft pack")
async def import_history(request: Request, prompt_id: str, body: HistoryImport) -> dict:
    st = request.app.state
    try:
        h = await st.client.history(prompt_id)
    except ComfyError as e:
        raise HTTPException(503, "ComfyUI isn't running") from e
    if not h or prompt_id not in h:
        raise HTTPException(404, f"no history entry {prompt_id}")
    try:
        found = importer.from_history(h[prompt_id])
        pid = importer.create(st.library.packs, st.library.catalog, found, body.id, body.id or f"comfy-{prompt_id[:8]}")
    except importer.ImportError_ as e:
        raise HTTPException(422, e.detail) from None
    return _imported(request, pid)


@router.put("/v1/workflows/{wid}", summary="Save a pack's workflow.toml (a draft becomes a pack)")
def save(request: Request, wid: str, body: SaveBody) -> dict:
    lib = request.app.state.library
    lib.packs.scan()
    p = lib.packs.get(wid)
    if p is None:
        raise HTTPException(404, f"no workflow {wid!r}")
    if (body.toml is None) == (body.manifest is None):
        raise HTTPException(422, "send either toml or manifest")
    text = body.toml if body.toml is not None else to_toml(Suggestion(body.manifest), estimate=False)
    try:
        Manifest.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(422, f"workflow.toml: {e}") from None
    except ValidationError as e:
        raise HTTPException(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from None
    if p.dir is None:
        p = lib.packs.adopt(p.id)
    tmp = p.dir / (MANIFEST + ".part")
    tmp.write_text(text)
    os.replace(tmp, p.dir / MANIFEST)
    lib.packs.scan()
    return lib.detail(lib.packs.get(p.id))


@router.delete("/v1/workflows/{wid}", summary="Remove a pack (moved to workflows/.trash/)")
def delete(request: Request, wid: str) -> dict:
    lib = request.app.state.library
    p = lib.packs.get(wid)
    if p is None:
        raise HTTPException(404, f"no workflow {wid!r}")
    trash = lib.packs.root / ".trash"
    trash.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if p.dir is not None:
        shutil.move(str(p.dir), trash / f"{p.id}-{stamp}")
    else:
        shutil.move(str(p.source), trash / f"{p.id}-{stamp}.json")
    lib.packs.scan()
    db = request.app.state.db
    if db.defaults().get(p.task) == p.id:
        db.set_default(p.task, None)
    return {"removed": p.id}


@router.post("/v1/downloads", status_code=202, summary="Download a missing model file into data/models/comfyui/<folder>/")
def download(request: Request, body: DownloadBody) -> dict:
    try:
        return request.app.state.downloads.start(body.url, body.folder, body.name).json()
    except (ValueError, FileExistsError) as e:
        raise HTTPException(409 if isinstance(e, FileExistsError) else 422, str(e)) from None


@router.get("/v1/downloads", summary="Model downloads and their progress")
def downloads(request: Request) -> dict:
    return {"downloads": [d.json() for d in sorted(request.app.state.downloads.items.values(), key=lambda d: -d.created)]}
