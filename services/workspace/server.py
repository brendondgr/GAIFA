"""Workspace: folders on this machine the agent reads, edits in place and runs code in (plan Phase 27).

AIHub runs this as `.venv/bin/python server.py` with AIHUB_PORT, AIHUB_ROOT, AIHUB_MODELS,
AIHUB_OUTPUTS and AIHUB_URL set (architecture §4.4). WORKSPACE_STATE (default
`$AIHUB_ROOT/data/state/workspace`) holds folders.json, checkpoints and run records.

Folders and levels: folders.py.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from folders import LEVELS, Caps, Folders, Refused

Level = Literal["read", "edit", "run", "run_net"]


class FolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="The folder's full path on this machine")
    level: Level = Field("read", description="read · edit · run · run_net (Run + network); new folders start at read")
    allow_bypass: bool = Field(False, description="Offer the Bypass chat mode for this folder")
    id: str | None = Field(None, description="A short id (default: from the folder's name)")
    name: str = Field("", max_length=64, description="A display name")


class FolderPatch(BaseModel):
    level: Level | None = None
    allow_bypass: bool | None = None
    name: str | None = Field(None, max_length=64)


class Ctx:
    """What the routes share: the folders and the places this mod writes."""

    def __init__(self, state: Path, aihub_root: Path | None, models: Path | None, outputs: Path, hub_url: str) -> None:
        self.state, self.outputs, self.hub_url = state, outputs, hub_url
        self.aihub_root = aihub_root
        self.folders = Folders(state, Caps(aihub_root, models))
        self.started = time.time()
        self.counts = {"reads": 0, "edits": 0, "runs": 0}


def create_app(state: Path | None = None, aihub_root: Path | None = None, models: Path | None = None,
               outputs: Path | None = None, hub_url: str | None = None) -> FastAPI:
    root = aihub_root or (Path(os.environ["AIHUB_ROOT"]) if os.environ.get("AIHUB_ROOT") else None)
    ctx = Ctx(state or Path(os.environ.get("WORKSPACE_STATE") or (root or Path(".")) / "data" / "state" / "workspace"),
              root, models or (Path(os.environ["AIHUB_MODELS"]) if os.environ.get("AIHUB_MODELS") else (root / "data" / "models" if root else None)),
              outputs or Path(os.environ.get("AIHUB_OUTPUTS", "outputs")),
              hub_url or os.environ.get("AIHUB_URL", "http://127.0.0.1:7000"))
    app = FastAPI(title="Workspace", version="0.1.0")
    app.state.ctx = ctx

    @app.exception_handler(Refused)
    async def refused(_: Request, e: Refused) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, "fix": e.fix}, status_code=e.status)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/status")
    def status() -> dict[str, Any]:
        folders = ctx.folders.public()
        return {"loaded": None, "busy": False, "idle_s": round(time.time() - ctx.started, 1),
                "stats": [{"label": "Folders", "value": len(folders)},
                          {"label": "Edits", "value": ctx.counts["edits"]},
                          {"label": "Runs", "value": ctx.counts["runs"]}],
                "jobs": []}

    @app.get("/v1/folders", summary="List the workspace folders and their levels")
    def folders() -> dict[str, Any]:
        return {"folders": ctx.folders.public(), "levels": list(LEVELS)}

    @app.post("/v1/folders", summary="Add a folder (starts at Read)")
    def add(body: FolderIn) -> dict[str, Any]:
        f = ctx.folders.add(body.path, body.level, body.allow_bypass, body.id, body.name)
        return f.public(ctx.folders.caps)

    @app.patch("/v1/folders/{fid}", summary="Change a folder's level, Bypass or name")
    def update(fid: str, body: FolderPatch) -> dict[str, Any]:
        f = ctx.folders.update(fid, body.level, body.allow_bypass, body.name)
        return f.public(ctx.folders.caps)

    @app.delete("/v1/folders/{fid}", summary="Remove a folder (its files are left alone)")
    def remove(fid: str) -> dict[str, Any]:
        if not ctx.folders.remove(fid):
            raise Refused("unknown_folder", f"there is no workspace folder {fid!r}", "", 404)
        return {"removed": fid}

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("AIHUB_PORT", "5103")), log_level="warning")
