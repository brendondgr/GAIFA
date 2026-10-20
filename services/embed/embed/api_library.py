"""The library's routes: its state, re-indexing and collections (plan 28.2), and search (28.3)."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .encoder import Encoder
from .hubclient import HubError
from .library import Library
from .search import index_recent, index_scope, origin_thread, scope, search

OutputKind = Literal["text", "document", "image", "audio", "video", "model3d", "archive", "other"]


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="What to find, in words: a question, a description "
                       "of a picture or a sound, a topic")
    kind: OutputKind | None = Field(None, description="Only outputs of this kind")
    collection: str | None = Field(None, description="Only this collection (its id or name, from library_collections)")
    thread_only: bool = Field(False, description="Only the files attached in this chat")
    limit: int = Field(8, ge=1, le=30, description="How many hits (at most two per output)")


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


def add_library_routes(app: FastAPI, lib: Library, enc: Encoder) -> None:
    store = lib.store

    @app.post("/v1/search", summary="Search every output by meaning: text and documents (with page and line), "
              "pictures, audio and video")
    async def search_route(body: SearchBody, x_aihub_origin: str | None = Header(None)) -> Any:
        """Hits are ranked by cosine score (higher is closer; ~0.5 is unrelated). Snippets are the files' own
        words, so they come as untrusted data. A search within a collection or a chat indexes its outputs first."""
        thread = origin_thread(x_aihub_origin) if body.thread_only else None
        if body.thread_only and not thread:
            return JSONResponse({"detail": "thread_only needs a chat: this call didn't come from one", "code": "no_thread",
                                 "fix": "leave thread_only out, or pass collection"}, 422)
        try:
            ids = await scope(lib, lib.hub, body.collection, thread)
            left = await index_scope(lib, ids) if ids else 0
            if ids is None:
                await index_recent(lib)
            lib.last_api = time.time()
            hits = await search(lib, enc, body.query, body.kind, ids, body.limit)
        except HubError as e:
            return JSONResponse(e.body(), e.status)
        c = store.counts()
        out: dict[str, Any] = {"results": hits, "searched": len(ids) if ids is not None else c["done"]}
        if ids is not None and not ids:
            out["note"] = "nothing to search: the chat has no attachments" if thread else "the collection is empty"
            out["fix"] = "leave thread_only and collection out to search every output"
        elif left or (ids is None and c["pending"]):
            n = left if ids is not None else c["pending"]
            out["note"] = f"{n} output(s) aren't indexed yet, so results may miss them"
        return out

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

    @app.get("/v1/collections", summary="Named sets of outputs to search within, and this chat's attachments")
    async def collections(x_aihub_origin: str | None = Header(None)) -> dict:
        cols = [{"id": c["id"], "name": c["name"], "outputs": c["outputs"], "count": len(c["outputs"])}
                for c in store.collections()]
        thread = origin_thread(x_aihub_origin)
        if thread:
            try:
                att = await lib.hub.thread_attachments(thread)
            except HubError:
                att = []
            cols.insert(0, {"id": f"thread:{thread}", "name": "this chat's attachments", "outputs": att,
                            "count": len(att), "implicit": True})
        return {"collections": cols}

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
