"""The `chats` collection (plan 28.5): the agent sends each chat's summary once the chat has gone quiet; it's
embedded under the same idle rule as everything else, and searched by meaning from the Chat list and the agent's
`chat_search`. This is conversation search, not memory: nothing here reaches a prompt unless a chat is looked up."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .encoder import Encoder, prompt
from .library import Library

SEARCH_BUDGET_S = 20           # a search first embeds pending summaries, for up to this long


class ChatBody(BaseModel):
    title: str = Field("", max_length=300)
    summary: str = Field(min_length=1, max_length=8000, description="The agent's summary of the chat")
    created_ts: float | None = None
    updated_ts: float | None = None


class ChatSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="What the chat was about, in words")
    limit: int = Field(8, ge=1, le=50)


def add_chat_routes(app: FastAPI, lib: Library, enc: Encoder) -> None:
    store = lib.store

    @app.put("/v1/chats/{tid}", summary="Add or replace a chat's summary (queued to be embedded)")
    def put_chat(tid: str, body: ChatBody) -> dict:
        store.put_chat(tid, body.title, body.summary, body.created_ts, body.updated_ts)
        lib.wake.set()
        return {"thread_id": tid, "state": "pending"}

    @app.delete("/v1/chats/{tid}", summary="Forget a chat's summary and its vector")
    def delete_chat(tid: str) -> Any:
        if not store.delete_chat(tid):
            return JSONResponse({"detail": f"no chat {tid!r} in the index", "code": "not_found"}, 404)
        return {"deleted": tid}

    @app.get("/v1/chats", summary="The chats collection: how many summaries are embedded and waiting")
    def chats() -> dict:
        return store.chat_counts()

    @app.post("/v1/chats/search", summary="Find chats by meaning")
    async def search_chats(body: ChatSearch) -> dict:
        """Chats whose summary is closest to the query, best first (cosine; ~0.5 is unrelated). Pending summaries
        are embedded first: someone is waiting for them."""
        deadline = time.monotonic() + SEARCH_BUDGET_S
        while store.chats_pending(1) and time.monotonic() < deadline:
            await lib.index_chats(gate=False)
        lib.last_api = time.time()
        rows = [r for r in store.chats() if r["state"] == "done" and r["vector"]]
        if not rows:
            return {"results": [], "pending": store.chat_counts()["pending"]}
        q = (await asyncio.to_thread(enc.embed, [("text", prompt(body.query, "query"))], 768, {"text": 1}))[0]
        m = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float16).reshape(len(rows), -1).astype(np.float32)
        scores = m @ q
        order = np.argsort(-scores)[: body.limit]
        return {"results": [{"thread_id": rows[i]["thread_id"], "title": rows[i]["title"], "summary": rows[i]["summary"],
                             "updated_ts": rows[i]["updated_ts"], "score": round(float(scores[i]), 3)} for i in order],
                "pending": store.chat_counts()["pending"]}
