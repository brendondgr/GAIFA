"""Importing another assistant's memory (plan memory-import 1.4), for the Memory tab's Import sheet.

    GET    /v1/memory/imports/prompt            the prompt to paste into the other assistant
    POST   /v1/memory/imports                   {text, source}: read it into a preview in the background → 202 {id, state}
    POST   /v1/memory/imports/file              {name, data (base64)}: the same for Claude's export zip or memories.json (3.1)
    GET    /v1/memory/imports                   the imports, newest first, with their counts
    GET    /v1/memory/imports/{id}              one, with each entry's facts, what they would do and the default choices
    POST   /v1/memory/imports/{id}/save         {choices: {"<n>.<k>": "save|review|skip"}}: save it
    DELETE /v1/memory/imports/{id}              undo a saved import
    GET    /v1/memory/export                    GAIFA's memory in the same format, to paste elsewhere (3.2)

Facts an import saved: `GET /v1/memory/facts?import=<id>`. Errors are MemoryError's envelope (api_memory.py).
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from .memory.imports import Importer
from .memory.model import MemoryError
from .memory.sources import EXPORT_PROMPT, MAX_BYTES, MAX_FILE


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_BYTES * 2, description="The other assistant's answer, pasted as it is")
    source: Literal["chatgpt", "claude", "gemini", "other"] = "other"


class FileIn(BaseModel):
    name: str = Field("", max_length=300)
    data: str = Field(min_length=1, max_length=MAX_FILE * 4 // 3 + 8, description="The file, base64")
    source: Literal["chatgpt", "claude", "gemini", "other"] = "claude"


class SaveIn(BaseModel):
    choices: dict[str, Literal["save", "review", "skip"]] = Field(default_factory=dict, max_length=5000,
                                                                  description='"<entry>.<fact>" → save|review|skip; the preview\'s choice otherwise')


def importer(request: Request) -> Importer:
    agent = request.app.state.agent
    if getattr(agent, "memory_importer", None) is None:
        agent.memory_importer = Importer(agent)
    return agent.memory_importer


def add_routes(app: FastAPI) -> None:
    @app.get("/v1/memory/imports/prompt", summary="The prompt that asks another assistant to write out its memory of the user")
    def prompt() -> dict:
        return {"prompt": EXPORT_PROMPT}

    @app.post("/v1/memory/imports", status_code=202, summary="Read another assistant's memory export into a preview (nothing is saved yet)")
    async def start(body: ImportIn, request: Request) -> dict:
        return importer(request).start(body.text, body.source)

    @app.post("/v1/memory/imports/file", status_code=202, summary="Read Claude's export (the zip, or its memories.json) into a preview")
    async def start_file(body: FileIn, request: Request) -> dict:
        try:
            data = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError):
            raise MemoryError(422, "bad_file", "the file isn't base64") from None
        return importer(request).start_file(body.name, data, body.source)

    @app.get("/v1/memory/export", summary="Your memory as text in the import prompt's format, to paste into another assistant")
    def export(request: Request) -> dict:
        return importer(request).export()

    @app.get("/v1/memory/imports", summary="Imports, newest first, with their counts")
    def imports(request: Request, limit: int = 50) -> list:
        return importer(request).list(limit)

    @app.get("/v1/memory/imports/{iid}", summary="An import: each entry, the facts it becomes, what they would do, the choices")
    def one(iid: str, request: Request) -> dict[str, Any]:
        return importer(request).get(iid)

    @app.post("/v1/memory/imports/{iid}/save", summary="Save an import with your choices (save, review or skip per fact)")
    def save(iid: str, body: SaveIn, request: Request) -> dict[str, Any]:
        return importer(request).save(iid, body.choices)

    @app.delete("/v1/memory/imports/{iid}", summary="Undo a saved import: what it added goes, what it replaced comes back")
    def undo(iid: str, request: Request) -> dict[str, Any]:
        return importer(request).undo(iid)
