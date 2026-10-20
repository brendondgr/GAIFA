"""Routes for the sandbox and run records (plan 27.5), and the running tools (27.6)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from folders import Refused


def mount(app: FastAPI, ctx: Any) -> None:
    sb = ctx.sandbox

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
