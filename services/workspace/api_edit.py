"""Routes for the editing tools and checkpoints (plan 27.3)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import editing
import reading


class EditIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    path: str = Field(min_length=1, description="The file, relative to the folder")
    old: str = Field(min_length=1, description="The exact text to replace, whitespace included; it must appear once (or pass replace_all)")
    new: str = Field(description="What replaces it")
    replace_all: bool = Field(False, description="Replace every occurrence of old")


class WriteIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    path: str = Field(min_length=1, description="The file, relative to the folder (made with its folders if new)")
    content: str = Field(description="The whole new content of the file")


class MoveIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    source: str = Field(min_length=1, description="The file to move or rename, relative to the folder")
    destination: str = Field(min_length=1, description="Its new path, relative to the folder (must not exist)")


class DeleteIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path")
    path: str = Field(min_length=1, description="The file to delete, relative to the folder")


class CommitIn(BaseModel):
    folder: str = Field(description="The workspace folder (a git repository)")
    message: str = Field(min_length=1, max_length=5000, description="The commit message")
    paths: list[str] | None = Field(None, description="Only these files (default: every change, new files included)")


def origin(request: Request) -> dict[str, Any]:
    return reading.origin_of(request.headers.get("x-aihub-origin"))


def named(o: dict[str, Any]) -> list[str]:
    m = o.get("named")
    return [str(x) for x in m][:20] if isinstance(m, list) else []


def mount(app: FastAPI, ctx: Any) -> None:
    def run(tool: str, body: BaseModel, request: Request) -> dict[str, Any]:
        o = origin(request)
        args = body.model_dump()
        ch = editing.plan(ctx.folders, tool, args, named(o))
        out = editing.apply(ctx.folders, ctx.checkpoints, ch, o)
        ctx.counts["edits"] += 1
        ctx.recent("edit", {"tool": tool, "folder": ch.folder.id, "summary": ch.summary, "thread": o.get("thread"),
                            "undo": out.get("undo")})
        return out

    @app.post("/v1/edit", summary="Replace exact text in a file")
    def edit(body: EditIn, request: Request) -> dict[str, Any]:
        return run("edit", body, request)

    @app.post("/v1/write", summary="Write a whole file (new or replaced)")
    def write(body: WriteIn, request: Request) -> dict[str, Any]:
        return run("write", body, request)

    @app.post("/v1/move", summary="Move or rename a file")
    def move(body: MoveIn, request: Request) -> dict[str, Any]:
        return run("move", body, request)

    @app.post("/v1/delete", summary="Delete a file")
    def delete(body: DeleteIn, request: Request) -> dict[str, Any]:
        return run("delete", body, request)

    @app.post("/v1/git/commit", summary="Commit changes (git hooks don't run)")
    def commit(body: CommitIn, request: Request) -> dict[str, Any]:
        return run("git_commit", body, request)

    @app.get("/v1/checkpoints", summary="Turns with saved checkpoints, newest first; ?thread= for one chat")
    def checkpoints(thread: str | None = None, limit: int = 50) -> dict[str, Any]:
        return {"turns": ctx.checkpoints.turns(thread, limit), "usage": ctx.checkpoints.usage()}

    @app.get("/v1/checkpoints/{thread}/{turn}", summary="One turn's changes")
    def turn(thread: str, turn: str) -> dict[str, Any]:
        meta = ctx.checkpoints.meta(thread, turn)
        return {"thread": thread, "turn": turn, "undone_ts": meta.get("undone_ts"),
                "entries": [{k: e.get(k) for k in ("n", "folder", "rel", "tool", "ts", "existed", "size")} for e in meta.get("entries") or []]}

    @app.post("/v1/checkpoints/{thread}/{turn}/undo", summary="Undo a turn: every file back as it was before it")
    def undo(thread: str, turn: str) -> Any:
        out = ctx.checkpoints.undo(thread, turn)
        if out["status"] == "conflict":
            return JSONResponse({"detail": out["detail"], "code": "changed_since", "data": out,
                                 "fix": "look at the diffs; change the files back by hand, or keep them"}, status_code=409)
        if out["status"] == "undone":
            ctx.recent("undo", {"thread": thread, "turn": turn, "summary": out["detail"]})
        return out
