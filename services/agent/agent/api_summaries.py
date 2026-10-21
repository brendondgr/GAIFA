"""Routes for conversations you can look up (plan 28.5): a chat's summary, running the summariser now, and the
Chat list's "by meaning" search (through the embed mod's `chats`)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .hubapi import HubCallError


def add_routes(app: FastAPI) -> None:
    def summaries(request: Request) -> Any:
        s = getattr(request.app.state.agent, "summaries", None)
        if s is None:
            raise HTTPException(503, "the summariser isn't running")
        return s

    @app.get("/v1/threads/{tid}/summary", summary="The chat's summary for search, if it has one (plan 28.5)")
    def thread_summary(tid: str, request: Request) -> dict:
        s = summaries(request).get(tid)
        if s is None:
            raise HTTPException(404, f"no summary for {tid} yet (it's written once the chat has been quiet a while)")
        return {k: s[k] for k in ("thread_id", "summary", "upto_seq", "made", "model", "sent")}

    @app.post("/v1/summaries/run", summary="Summarise the chats that are due now, and resend unsent summaries")
    async def run_now(request: Request) -> dict:
        s = summaries(request)
        return {"summarised": await s.check(), "idle_min": s.idle_s / 60}

    @app.get("/v1/chats/search", summary="Find chats by meaning: title, date, summary and a link (needs the embed mod)")
    async def search_chats(request: Request, q: str = Query(..., min_length=1, max_length=2000),
                           limit: int = Query(8, ge=1, le=50)) -> dict:
        try:
            return {"results": await summaries(request).search(q, limit)}
        except HubCallError as e:
            raise HTTPException(503 if e.status in (404, 502, 503) else e.status,
                                f"search by meaning needs the embed mod ({e.detail})") from e
