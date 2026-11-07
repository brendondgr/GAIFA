"""Routes for a chat's queue (plan chat-responsive 2.1): the messages sent during a turn, held until it ends. Each change
is published as a `queue` event on the chat's stream."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


class QueueEdit(BaseModel):
    text: str | None = Field(None, max_length=100_000)
    index: int | None = Field(None, ge=0, description="the new place in the queue, 0 first")


def add_queue_routes(app: FastAPI, A: Callable[[Request], Any], thread_or_404: Callable[[Any, str], Any]) -> None:
    def held(agent: Any, tid: str, qid: str) -> dict[str, Any]:
        thread_or_404(agent, tid)
        item = agent.queue.get(tid, qid)
        if item is None:
            raise HTTPException(404, f"no held message {qid!r}")
        return item

    @app.get("/v1/threads/{tid}/queue", summary="The messages held until the turn ends, and whether they're paused (after an error)")
    def queue(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        return agent.queue.state(tid)

    @app.patch("/v1/threads/{tid}/queue/{qid}", summary="Change a held message's text, or move it (index 0 is first)")
    def edit(tid: str, qid: str, body: QueueEdit, request: Request) -> dict:
        agent = A(request)
        held(agent, tid, qid)
        if body.text is not None and not body.text.strip():
            raise HTTPException(422, {"code": "empty_message", "detail": "the message is empty: remove it instead"})
        item = agent.queue.edit(tid, qid, body.text, body.index)
        agent.publish_queue(tid)
        return item

    @app.delete("/v1/threads/{tid}/queue/{qid}", summary="Remove a held message")
    def remove(tid: str, qid: str, request: Request) -> dict:
        agent = A(request)
        held(agent, tid, qid)
        agent.queue.remove(tid, qid)
        agent.publish_queue(tid)
        return agent.queue.state(tid)

    @app.post("/v1/threads/{tid}/queue/{qid}/send", status_code=202,
              summary="Send a held message now: the running turn reads it at its next model call (a waiting card is dismissed)")
    async def send_now(tid: str, qid: str, request: Request) -> dict:
        agent = A(request)
        held(agent, tid, qid)
        sent = await agent._drain(tid, qid)
        return sent[0] if sent else {}

    @app.post("/v1/threads/{tid}/queue/resume", status_code=202, summary="Send the held messages a failed turn paused")
    async def resume(tid: str, request: Request) -> dict:
        agent = A(request)
        thread = thread_or_404(agent, tid)
        agent.queue.unpause(tid)
        if agent.busy(tid) or thread["state"] == "waiting":     # they go when the turn ends
            agent.publish_queue(tid)
            return agent.queue.state(tid)
        await agent._drain(tid)
        return agent.queue.state(tid)

    @app.delete("/v1/threads/{tid}/queue", summary="Remove every held message")
    def clear(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        agent.queue.clear(tid)
        agent.publish_queue(tid)
        return agent.queue.state(tid)
