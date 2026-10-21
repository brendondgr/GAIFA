"""Routes for the sandbox and run records (plan 27.5), and the running tools (27.6)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

import reading
import running
from folders import Refused
from sandbox import DEFAULT_TIMEOUT, MAX_TIMEOUT

OutputRef = Annotated[str, Field(json_schema_extra={"format": "aihub-file"})]


class RunIn(BaseModel):
    folder: str = Field(description="The workspace folder: its id, name or path (at Run, or Run + network for network=true)")
    command: str = Field(min_length=1, max_length=20000, description="A shell command (bash -c), run in the folder")
    where: Literal["sandbox", "host"] = Field("sandbox", description="sandbox (default): the container. host: on the user's machine, outside the sandbox; always asks them")
    network: bool = Field(False, description="Give the sandbox the internet (the folder must be at Run + network), e.g. to install packages")
    cwd: str | None = Field(None, description="A subfolder to run in, relative to the folder")
    timeout_s: int = Field(DEFAULT_TIMEOUT, ge=1, le=MAX_TIMEOUT, description=f"Stop it after this many seconds (default {DEFAULT_TIMEOUT}, at most {MAX_TIMEOUT})")


class PythonIn(BaseModel):
    code: str = Field(min_length=1, max_length=100000, description="Python 3.12 to run (numpy, pandas, matplotlib, openpyxl, python-pptx, python-docx, pypdfium2 are there)")
    inputs: list[OutputRef] = Field(default_factory=list, description="Outputs to read (output:<id> or #n): copied into $AIHUB_INPUTS (inputs/ in the working directory)")
    folder: str | None = Field(None, description="A workspace folder at Run to work in (the working directory); without one, files you write become outputs")
    network: bool = Field(False, description="Internet (needs a folder at Run + network)")
    timeout_s: int = Field(DEFAULT_TIMEOUT, ge=1, le=MAX_TIMEOUT, description="Stop it after this many seconds")


def _origin(request: Request) -> dict[str, Any]:
    return reading.origin_of(request.headers.get("x-aihub-origin"))


def mount(app: FastAPI, ctx: Any) -> None:
    sb = ctx.sandbox

    @app.post("/v1/run", summary="Run a command in a workspace folder (the sandbox, or this machine)")
    async def run(body: RunIn, request: Request) -> dict[str, Any]:
        o = _origin(request)
        out = await running.run_command(ctx.folders, sb, body.model_dump(), o, request.is_disconnected)
        ctx.counts["runs"] += 1
        ctx.recent("run", {"folder": body.folder, "summary": f"{body.where}: {body.command[:120]} → {out.get('exit_code')}",
                           "thread": o.get("thread"), "run": out["run"]})
        return out

    @app.post("/v1/python", summary="Run Python in the sandbox; files it writes become outputs")
    async def python(body: PythonIn, request: Request) -> dict[str, Any]:
        o = _origin(request)
        out = await running.run_python(ctx.folders, sb, ctx.state, ctx.outputs, ctx.hub_url, body.model_dump(), o,
                                       request.is_disconnected)
        ctx.counts["runs"] += 1
        ctx.recent("run", {"folder": body.folder, "summary": f"python → {out.get('exit_code')}, {len(out.get('files') or [])} file(s)",
                           "thread": o.get("thread"), "run": out["run"]})
        return out

    @app.get("/v1/sandbox", summary="The sandbox image: built or not, its id and size, a build in progress")
    async def sandbox_state() -> dict[str, Any]:
        return await sb.image()

    @app.post("/v1/sandbox/build", summary="Build the sandbox image (minutes: it downloads the base images and libraries)")
    async def build() -> dict[str, Any]:
        if not sb.available():
            raise Refused("no_podman", "podman isn't installed", "install podman (setup/workspace.md)", 503)
        return await sb.build()

    @app.get("/v1/runs", summary="Recent runs, newest first; ?thread= for one chat")
    def runs(thread: str | None = None, limit: int = 50) -> dict[str, Any]:
        return {"runs": sb.records.list(thread, limit)}

    @app.get("/v1/runs/{rid}", summary="One run: its command, where, exit code and output")
    def one(rid: str) -> dict[str, Any]:
        r = sb.records.get(rid)
        if r is None:
            raise Refused("not_found", f"no run {rid!r}", "", 404)
        return r

    @app.post("/v1/runs/{rid}/cancel", summary="Stop a run")
    async def cancel(rid: str) -> dict[str, Any]:
        return {"cancelled": await sb.cancel(rid)}
