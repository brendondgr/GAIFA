"""Agent workflows' routes (plan agent-workflows 1.1): a chat's tree of sub-agents, and deleting a chat with its own.

    GET /v1/threads/{tid}/tree     the workflow `tid` is in: {root, children: [{id, label, parent, state, …}]}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


async def delete_children(agent: Any, tid: str) -> list[str]:
    """Deleting a chat deletes its sub-agents: each stopped, its events, its grants and its summary gone. Returns their ids."""
    gone: list[str] = []
    for c in reversed(agent.store.children(tid)):
        gone += await delete_children(agent, c["id"])         # deeper sub-agents first
        await agent.cancel(c["id"])
        agent.store.delete_thread(c["id"])
        try:
            await agent.hub.end_grants(c["id"])
        except Exception:  # noqa: BLE001: the hub may be restarting; its grants end with the chat's id unused
            pass
        if getattr(agent, "summaries", None):
            await agent.summaries.forget(c["id"])
        gone.append(c["id"])
    return gone


def add_routes(app: FastAPI) -> None:
    def A(request: Request) -> Any:
        return request.app.state.agent

    @app.get("/v1/threads/{tid}/tree", summary="The workflow a chat is in: its root chat and every sub-agent, each with its "
             "parent, label, state and whether you've seen how it ended")
    def tree(tid: str, request: Request) -> dict:
        t = A(request).store.tree(tid)
        if t is None:
            raise HTTPException(404, f"no thread {tid!r}")
        return t
