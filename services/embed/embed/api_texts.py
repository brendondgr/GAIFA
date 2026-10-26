"""Named text collections (plan structured-memory 2.1): short texts another mod sends, one vector each, searched by
meaning, like the `chats` collection (whose routes stay as they are). The agent's memory is `ns = "memory"`: its
facts and entities, sent as they change. Texts are embedded under the same idle rule and GPU lease as everything
else; a search first embeds what is pending in its collection, since someone is waiting."""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .api_library import backend_error
from .encoder import Encoder, prompt
from .hubclient import HubError
from .library import Library
from .worker import WorkerDied

NS = r"^[a-z][a-z0-9-]{1,31}$"
SEARCH_BUDGET_S = 20


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    title: str = Field("", max_length=300)
    meta: dict[str, Any] = Field(default_factory=dict, description="Returned with each search result as it was sent")


class TextSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(10, ge=1, le=200)
    ids: list[str] | None = Field(None, max_length=5000, description="Only these ids")


def add_text_routes(app: FastAPI, lib: Library, enc: Encoder) -> None:
    store = lib.store

    @app.put("/v1/texts/{ns}/{tid}", summary="Add or replace a text in a collection (queued to be embedded; unchanged text keeps its vector)")
    def put_text(body: TextBody, ns: str = Path(pattern=NS), tid: str = Path(max_length=200)) -> dict:
        store.put_text(ns, tid, body.title, body.text, json.dumps(body.meta))
        lib.wake.set()
        return {"ns": ns, "id": tid}

    @app.delete("/v1/texts/{ns}/{tid}", summary="Forget a text and its vector")
    def delete_text(ns: str = Path(pattern=NS), tid: str = Path(max_length=200)) -> Any:
        if not store.delete_texts(ns, [tid]):
            return JSONResponse({"detail": f"no text {tid!r} in {ns}", "code": "not_found"}, 404)
        return {"deleted": tid}

    @app.delete("/v1/texts/{ns}", summary="Forget a whole collection, or ?ids=a,b only those")
    def delete_texts(ns: str = Path(pattern=NS), ids: str | None = Query(None)) -> dict:
        return {"deleted": store.delete_texts(ns, [i for i in ids.split(",") if i] if ids is not None else None)}

    @app.get("/v1/texts/{ns}", summary="A collection's counts: embedded and waiting")
    def counts(ns: str = Path(pattern=NS)) -> dict:
        return store.text_counts(ns)

    @app.post("/v1/texts/{ns}/search", summary="A collection's texts closest in meaning to the query, best first")
    async def search(body: TextSearch, ns: str = Path(pattern=NS)) -> Any:
        """Cosine scores (~0.5 is unrelated for this model). Pending texts are embedded first, up to 20 s."""
        deadline = time.monotonic() + SEARCH_BUDGET_S
        try:
            while store.texts_pending(1) and time.monotonic() < deadline:
                await lib.index_chats(gate=False)
            lib.last_api = time.time()
            rows = [r for r in store.texts(ns, body.ids) if r["state"] == "done" and r["vector"]]
            if not rows:
                return {"results": [], "pending": store.text_counts(ns)["pending"]}
            q = (await lib.encode([("text", prompt(body.query, "query"))], 768, {"text": 1}, f"Search {ns}"))[0]
        except HubError as e:
            return JSONResponse(e.body(), e.status)
        except (FileNotFoundError, WorkerDied) as e:
            return backend_error(e)
        m = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float16).reshape(len(rows), -1).astype(np.float32)
        scores = m @ q
        order = np.argsort(-scores)[: body.limit]
        return {"results": [{"id": rows[i]["id"], "title": rows[i]["title"], "meta": json.loads(rows[i]["meta"] or "{}"),
                             "score": round(float(scores[i]), 3)} for i in order],
                "pending": store.text_counts(ns)["pending"]}
