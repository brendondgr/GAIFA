"""Agent workflows' routes (plan agent-workflows): a chat's tree of sub-agents, deleting a chat with its own (1.1), and
its sub-agents' requests, decided from it (2.3).

    GET  /v1/threads/{tid}/tree             the workflow `tid` is in: {root, children: [{id, label, parent, state, …}]}
    GET  /v1/threads/{tid}/requests         its sub-agents' requests (?open=true: the ones still waiting)
    POST /v1/threads/{tid}/requests/{rid}   decide one: {approve, arguments?, reason?, remember?, confirm?} or {answers}
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


class RequestDecision(BaseModel):
    approve: bool = False
    arguments: dict[str, Any] | None = None
    reason: str | None = Field(None, max_length=500)
    remember: Literal["once", "thread", "always", "sites"] = Field("once", description="thread: allowed in the whole workflow "
                                                                   "(written for its root chat)")
    confirm: bool = False
    answers: dict[str, Any] | None = Field(None, description="A question's answers (question text → label or text)")


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

    @app.get("/v1/threads/{tid}/requests", summary="Its sub-agents' requests (approvals and questions sent to it), each with "
             "`waiting` (its card still waits), `open` (not reviewed yet) and its `review`; ?waiting=true: only those waiting")
    def list_requests(tid: str, request: Request, waiting: bool = False) -> list[dict]:
        from .workflows import requests
        agent = A(request)
        if agent.store.thread(tid) is None:
            raise HTTPException(404, f"no thread {tid!r}")
        reviews = {e["payload"]["id"]: e["payload"] for e in agent.store.events(tid, types=("agent_review",))}
        rows = [{**r, **({"review": reviews[r["id"]]} if r["id"] in reviews else {})} for r in requests.requests_of(agent, tid)]
        return [r for r in rows if r["waiting"] or not waiting]

    @app.post("/v1/threads/{tid}/requests/{rid}", status_code=202, summary="Decide a sub-agent's request from the chat that "
              "started it: its approval (remember: thread allows it in the whole workflow) or its question")
    async def decide_request(tid: str, rid: str, body: RequestDecision, request: Request) -> dict:
        from .hubapi import HubCallError
        from .workflows import requests
        agent = A(request)
        r = next((x for x in requests.requests_of(agent, tid) if x["id"] == rid), None)
        if r is None:
            raise HTTPException(404, {"code": "not_found", "detail": f"no request {rid!r} in this chat"})
        if not r["waiting"]:
            raise HTTPException(409, {"code": "already_decided", "detail": f"request {rid} was decided already"})
        try:
            if r["kind"] == "approval":
                await agent.approval(r["child"], r["approval_id"], body.approve, body.arguments, body.reason, body.remember,
                                     body.confirm)
            else:
                await agent.answer(r["child"], r["call"], body.answers or {"(the user)": body.reason or ""})
        except HubCallError as e:
            raise HTTPException(e.status, {"code": e.code, "detail": e.detail, **({"data": e.data} if e.data else {})})
        action = "answer" if r["kind"] == "question" else ("approve" if body.approve else "deny")
        ev = agent.emit(tid, "agent_review", {"id": rid, "child": r["child"], "action": action, "by": "user", "kind": r["kind"],
                                              **({"reason": body.reason} if body.reason else {}),
                                              **({"remember": body.remember} if body.remember != "once" else {}),
                                              **({"approval_id": r["approval_id"]} if r.get("approval_id") else {})})
        if agent.workflows is not None:
            agent.workflows.publish(r["child"])
        return {"request": rid, "action": action, "event": ev}
