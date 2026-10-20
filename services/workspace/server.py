"""Workspace: folders on this machine the agent reads, edits in place and runs code in (plan Phase 27).

AIHub runs this as `.venv/bin/python server.py` with AIHUB_PORT, AIHUB_ROOT, AIHUB_MODELS,
AIHUB_OUTPUTS and AIHUB_URL set (architecture §4.4). WORKSPACE_STATE (default
`$AIHUB_ROOT/data/state/workspace`) holds folders.json, checkpoints and run records.

Folders and levels: folders.py.
"""

from __future__ import annotations

import collections
import json
import os
import time
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api_edit
import reading
from checkpoints import Checkpoints
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


class TreeIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id (from workspace_folders), name or path")
    path: str | None = Field(None, description="A subfolder, relative to the folder (default: the whole folder)")
    depth: int = Field(3, ge=1, le=8, description="How many levels down to list")
    limit: int = Field(300, ge=1, le=2000, description="At most this many entries")


class ReadIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    path: str = Field(min_length=1, description="The file, relative to the folder")
    offset: int = Field(1, ge=1, description="The first line to return (1-based)")
    limit: int = Field(400, ge=1, le=2000, description="How many lines")


class SearchIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    query: str = Field(min_length=1, max_length=500, description="Text to find (or a regular expression with regex=true)")
    regex: bool = Field(False, description="Treat query as a regular expression")
    glob: str | None = Field(None, max_length=200, description="Only files matching this glob, e.g. *.py or src/**/*.ts")
    path: str | None = Field(None, description="Only under this subfolder")
    limit: int = Field(100, ge=1, le=500, description="At most this many matching lines")


class GitIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    command: Literal["status", "log", "diff", "show", "branch"] = Field(description="A read-only git command")
    rev: str | None = Field(None, max_length=200, description="log/diff/show: a commit, branch or range (HEAD~3..HEAD); diff without it: the working tree")
    path: str | None = Field(None, max_length=1000, description="Only this file or folder")
    limit: int = Field(20, ge=1, le=200, description="log: how many commits")


def named_of(request: Request) -> list[str]:
    """The secret-looking files the user named in their message (the agent puts them in the origin)."""
    m = reading.origin_of(request.headers.get("x-aihub-origin")).get("named")
    return [str(x) for x in m][:20] if isinstance(m, list) else []


class Ctx:
    """What the routes share: the folders and the places this mod writes."""

    def __init__(self, state: Path, aihub_root: Path | None, models: Path | None, outputs: Path, hub_url: str) -> None:
        self.state, self.outputs, self.hub_url = state, outputs, hub_url
        self.aihub_root = aihub_root
        self.folders = Folders(state, Caps(aihub_root, models))
        self.checkpoints = Checkpoints(state)
        self.started = time.time()
        self.counts = {"reads": 0, "edits": 0, "runs": 0}
        self.activity: collections.deque[dict[str, Any]] = collections.deque(self._load_recent(), maxlen=500)

    def _load_recent(self) -> list[dict[str, Any]]:
        try:
            lines = (self.state / "recent.jsonl").read_text().splitlines()[-500:]
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out

    def recent(self, kind: str, item: dict[str, Any]) -> None:
        """Recent edits, runs and undos, for the Workspace page (kept in recent.jsonl, the last 2000)."""
        row = {"kind": kind, "ts": time.time(), **item}
        self.activity.append(row)
        f = self.state / "recent.jsonl"
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            if f.stat().st_size > 2_000_000:
                f.write_text("\n".join(f.read_text().splitlines()[-2000:]) + "\n")
        except OSError:
            pass


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

    @app.get("/v1/recent", summary="Recent edits, runs and undos, newest first; ?thread= for one chat")
    def recent(thread: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = [r for r in reversed(ctx.activity) if not thread or r.get("thread") == thread]
        return {"items": rows[:limit]}

    api_edit.mount(app, ctx)

    @app.post("/v1/tree", summary="List a folder's files")
    def tree(body: TreeIn, request: Request) -> str:
        f = ctx.folders.get(body.folder)
        ctx.counts["reads"] += 1
        return reading.tree(ctx.folders, f, body.path, body.depth, body.limit, named_of(request))

    @app.post("/v1/read", summary="Read a file with line numbers")
    def read(body: ReadIn, request: Request) -> str:
        f = ctx.folders.get(body.folder)
        ctx.counts["reads"] += 1
        return reading.read(ctx.folders, f, body.path, body.offset, body.limit, named_of(request))

    @app.post("/v1/search", summary="Search a folder's files")
    def search(body: SearchIn, request: Request) -> str:
        f = ctx.folders.get(body.folder)
        ctx.counts["reads"] += 1
        return reading.search(ctx.folders, f, body.query, body.regex, body.glob, body.path, body.limit, named_of(request))

    @app.post("/v1/git", summary="Read-only git: status, log, diff, show, branch")
    def git(body: GitIn, request: Request) -> str:
        f = ctx.folders.get(body.folder)
        if body.path:
            ctx.folders.resolve(f, body.path, named=named_of(request))
        root, _ = ctx.folders.resolve(f, ".")
        ctx.counts["reads"] += 1
        return reading.git_read(f, root, body.command, body.rev, body.path, body.limit)

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("AIHUB_PORT", "5103")), log_level="warning")
