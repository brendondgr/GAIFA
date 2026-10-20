"""The library's routes (plan 28.2): its state, re-indexing, and collections."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .library import Library


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="Unique")
    outputs: list[str] = Field(default_factory=list, description="Output ids (`output:<id>` or bare)")


class ReindexBody(BaseModel):
    output_id: str | None = Field(None, description="One output; leave out for all of them")


def _ids(refs: list[str]) -> list[str]:
    return [r.removeprefix("output:") for r in refs]


def _missing(cid: str) -> JSONResponse:
    return JSONResponse({"detail": f"no collection {cid!r}", "code": "not_found",
                         "fix": "GET /v1/collections lists them"}, 404)


def add_library_routes(app: FastAPI, lib: Library) -> None:
    store = lib.store

    @app.get("/v1/library", summary="The index: state (idle, waiting_for_gpu, indexing, no_room), counts, the GPU's idleness")
    def library() -> dict:
        return lib.status()

    @app.get("/v1/library/outputs/{output_id}", summary="One output's index entry and its chunks (positions and snippets)")
    def library_output(output_id: str) -> Any:
        oid = output_id.removeprefix("output:")
        row = store.get(oid)
        if row is None:
            return JSONResponse({"detail": f"output {oid} isn't in the index", "code": "not_found"}, 404)
        return {**row, "chunk_list": store.chunks_of(oid)}

    @app.post("/v1/library/reindex", summary="Queue one output, or every output, to be indexed again")
    def reindex(body: ReindexBody | None = None) -> dict:
        oid = (body.output_id or "").removeprefix("output:") if body else ""
        return {"queued": lib.reindex(oid or None)}

    @app.get("/v1/collections", summary="Named sets of outputs to search within")
    def collections() -> dict:
        return {"collections": store.collections()}

    @app.post("/v1/collections", status_code=201, summary="Make a collection")
    def make(body: CollectionBody) -> Any:
        if store.collection(body.name):
            return JSONResponse({"detail": f"a collection named {body.name!r} exists", "code": "exists",
                                 "fix": "pick another name, or PUT /v1/collections/{id} to change it"}, 409)
        return store.save_collection(body.name, _ids(body.outputs))

    @app.put("/v1/collections/{cid}", summary="Rename a collection or replace its outputs")
    def change(cid: str, body: CollectionBody) -> Any:
        c = store.collection(cid)
        if c is None:
            return _missing(cid)
        other = store.collection(body.name)
        if other and other["id"] != c["id"]:
            return JSONResponse({"detail": f"a collection named {body.name!r} exists", "code": "exists"}, 409)
        return store.save_collection(body.name, _ids(body.outputs), c["id"])

    @app.delete("/v1/collections/{cid}", summary="Delete a collection (its outputs stay)")
    def remove(cid: str) -> Any:
        c = store.collection(cid)
        if c is None or not store.delete_collection(c["id"]):
            return _missing(cid)
        return {"deleted": c["id"]}
