"""Routes for environments (plan 34): named sets of folders, each with its own levels.

`GET/POST /v1/environments`, `GET/PUT/DELETE /v1/environments/{id}`, and a folder in one:
`POST /v1/environments/{id}/folders`, `PATCH/DELETE /v1/environments/{id}/folders/{fid}`.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from folders import LEVELS

Level = Literal["read", "edit", "run", "run_net"]


class EnvIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="The environment's name, e.g. Grants")
    id: str | None = Field(None, description="A short id (default: from the name)")


class EnvPatch(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="The new name")


class EnvFolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="The folder's full path on this machine")
    level: Level = Field("read", description="read · edit · run · run_net (Run + network), in this environment")
    allow_bypass: bool = Field(False, description="Offer the Bypass chat mode for this folder")
    id: str | None = Field(None, description="A short id (default: from the folder's name, or its id in another environment)")
    name: str = Field("", max_length=64, description="A display name")


class EnvFolderPatch(BaseModel):
    level: Level | None = None
    allow_bypass: bool | None = None
    name: str | None = Field(None, max_length=64)


def mount(app: FastAPI, ctx: Any) -> None:
    envs = ctx.folders.envs
    caps = ctx.folders.caps

    @app.get("/v1/environments", summary="The environments, each with its folders and their levels")
    def list_envs() -> dict[str, Any]:
        return {"environments": [e.public(caps) for e in envs.all()], "default": "default", "levels": list(LEVELS)}

    @app.post("/v1/environments", summary="Create an environment (no folders yet)")
    def create(body: EnvIn) -> dict[str, Any]:
        return envs.create(body.name, body.id).public(caps)

    @app.get("/v1/environments/{eid}", summary="One environment and its folders")
    def one(eid: str) -> dict[str, Any]:
        return envs.get(eid).public(caps)

    @app.put("/v1/environments/{eid}", summary="Rename an environment")
    def rename(eid: str, body: EnvPatch) -> dict[str, Any]:
        return envs.rename(eid, body.name).public(caps)

    @app.delete("/v1/environments/{eid}", summary="Delete an environment (not Default); its chats use Default")
    def delete(eid: str) -> dict[str, Any]:
        envs.delete(eid)
        return {"deleted": eid}

    @app.post("/v1/environments/{eid}/folders", summary="Add a folder to an environment (Read unless you say otherwise)")
    def add(eid: str, body: EnvFolderIn) -> dict[str, Any]:
        return envs.add_folder(eid, body.path, body.level, body.allow_bypass, body.id, body.name).public(caps)

    @app.patch("/v1/environments/{eid}/folders/{fid}", summary="Change a folder's level, Bypass or name in an environment")
    def update(eid: str, fid: str, body: EnvFolderPatch) -> dict[str, Any]:
        return envs.update_folder(eid, fid, body.level, body.allow_bypass, body.name).public(caps)

    @app.delete("/v1/environments/{eid}/folders/{fid}", summary="Remove a folder from an environment (its files are left alone)")
    def remove(eid: str, fid: str) -> dict[str, Any]:
        from folders import Refused
        if not envs.remove_folder(eid, fid):
            raise Refused("unknown_folder", f"there is no folder {fid!r} in {eid!r}", "", 404)
        return {"removed": fid}
