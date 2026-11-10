"""GAIFA's chats for other agents (plan agent-workflows 4.1): Claude Code, Codex or any MCP client starts a chat here,
writes to it, waits for it and reads its answer, through the hub's `/mcp` (the agent mod's `[tools]`, `agent_chat_*`).

    POST /v1/external/start  {prompt, title?, model?, mode?, environment?, project?}  → {chat, title, state, link, note}
    POST /v1/external/send   {chat, text}                                            → {chat, sent | queued}
    POST /v1/external/read   {chat, after?}                                          → the chat as the caller sees it
    POST /v1/external/wait   {chat, timeout?}   (≤ 60 s, until its turn ends)       → the same
    POST /v1/external/stop   {chat}
    POST /v1/external/list   {}                 the chats this client started

A chat started here is a root chat (`settings.external = {by: "mcp", client, started}`), in the list with a chip; it
may start sub-agents as any chat. Bypass is refused. The caller can only reach chats started over /mcp (and their
sub-agents), never the user's own. Its cards are the user's: the read says what waits (`waiting_for_you`).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

ANSWER_CHARS = 8000
MODES = ("plan", "manual", "accept_edits", "auto")


class StartIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000, description="What the chat should do: its first message")
    title: str = Field("", max_length=120, description="A name for the chat (default: from the prompt)")
    model: str | None = Field(None, max_length=200, description="A model the relay serves (default: the agent's)")
    mode: str = Field("manual", description="plan, manual, accept_edits or auto (never bypass); manual asks before anything changes")
    environment: str | None = Field(None, max_length=80, description="A workspace environment for its folders")
    project: str | None = Field(None, max_length=80, description="A project to start it in")


class ChatIn(BaseModel):
    chat: str = Field(min_length=3, max_length=40, description="The chat's id, from agent_chat_start or agent_chat_list")


class SendIn(ChatIn):
    text: str = Field(min_length=1, max_length=100_000)


class ReadIn(ChatIn):
    after: int = Field(0, ge=0, description="Only messages after this seq (the read's last_seq)")


class WaitIn(ChatIn):
    timeout: float = Field(30, ge=1, le=60, description="Seconds to wait for its turn to end")


class Nothing(BaseModel):
    pass


def origin_of(request: Request) -> dict[str, Any]:
    try:
        o = json.loads(request.headers.get("x-gaifa-origin") or "{}")
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def client_of(request: Request) -> str:
    return str(origin_of(request).get("client") or "another agent")[:80]


def external_of(agent: Any, tid: str) -> dict[str, Any]:
    """The chat if it was started over /mcp, or is a sub-agent of one; else 404 (the user's own chats stay theirs)."""
    t = agent.store.thread(tid)
    if t is not None and not (t.get("settings") or {}).get("external"):
        root = agent.store.thread(agent.store.root_of(tid))
        t = t if root is not None and (root.get("settings") or {}).get("external") else None
    if t is None:
        raise HTTPException(404, {"code": "not_found", "detail": f"no chat {tid!r} started over /mcp",
                                  "fix": "use a chat you started with agent_chat_start (agent_chat_list shows them)"})
    return t


def view(agent: Any, t: dict[str, Any], after: int = 0) -> dict[str, Any]:
    """What the caller reads: its state, the last answer, what waits for the user, the messages after `after`."""
    from .workflows import requests
    tid = t["id"]
    evs = agent.store.events(tid, after)
    answer = next((e["payload"].get("text") or "" for e in reversed(agent.store.events(tid, types=("assistant",)))), "")
    msgs = [{"seq": e["seq"], "role": "user" if e["type"] == "user" else "assistant", "text": (e["payload"].get("text") or "")[:ANSWER_CHARS]}
            for e in evs if e["type"] in ("user", "assistant") and (e["payload"].get("text") or "").strip()]
    waits = [{"kind": c["kind"], **({"tool": c.get("tool"), "risk": c.get("risk")} if c["kind"] == "approval" else {})}
             for c in requests.open_cards(agent, tid)]
    waits += [{"kind": r["kind"], "tool": r.get("tool"), "risk": r.get("risk"), "sub_agent": r["label"]}
              for r in requests.requests_of(agent, tid) if r["waiting"]]
    out = {"chat": tid, "title": t["title"], "state": "running" if agent.running(tid) else t["state"], "running": agent.running(tid),
           "answer": answer.strip()[:ANSWER_CHARS], "messages": msgs, "last_seq": agent.store.last_seq(tid),
           "sub_agents": [{"chat": c["id"], "label": (c["settings"].get("spawn") or {}).get("label"), "state": c["state"]}
                          for c in agent.store.children(tid)], "link": f"#/chat/{tid}"}
    if waits:
        out["waiting_for_you"] = waits
        out["note"] = "the user decides these in GAIFA (the chat, or the header's Approvals); you can't. Tell them, and wait."
    return out


def add_routes(app: FastAPI) -> None:
    def A(request: Request) -> Any:
        return request.app.state.agent

    @app.post("/v1/external/start", status_code=201, summary="Start a chat for another agent: its first message is `prompt`; "
              "it runs on its own (wait for it, then read it)")
    async def start(body: StartIn, request: Request) -> dict:
        from . import api_projects
        agent = A(request)
        if body.mode not in MODES:
            raise HTTPException(422, {"code": "bypass_refused" if body.mode == "bypass" else "invalid_arguments",
                                      "detail": f"mode {body.mode!r}: one of {', '.join(MODES)}" + (" (never bypass over /mcp)" if body.mode == "bypass" else ""),
                                      "fix": "use manual (asks before anything changes) or auto"})
        st: dict[str, Any] = {"external": {"by": "mcp", "client": client_of(request), "started": time.time()}}
        if body.environment:
            st["environment"] = body.environment
        if body.project:
            st["project"] = body.project
        settings, model, mode = api_projects.new_chat(agent, st, body.model, body.mode)
        if model and agent.workflows is not None and not await agent.workflows.served(model):
            raise HTTPException(400, {"code": "unknown_model", "detail": f"the relay doesn't serve {model!r}", "fix": "leave model out"})
        th = agent.store.create_thread(body.title.strip(), model, mode or "manual", settings)
        await agent.send(th["id"], body.prompt, by="mcp")
        t = agent.store.thread(th["id"]) or th
        return {"chat": t["id"], "title": t["title"], "state": "running" if agent.running(t["id"]) else t["state"], "link": f"#/chat/{t['id']}",
                "note": "it runs on its own: agent_chat_wait waits for its turn to end, agent_chat_read reads it"}

    @app.post("/v1/external/send", status_code=202, summary="Write to a chat you started (held until its turn ends, if it runs)")
    async def send(body: SendIn, request: Request) -> dict:
        agent = A(request)
        external_of(agent, body.chat)
        ev = await agent.send(body.chat, body.text, by="mcp")
        return {"chat": body.chat, **({"queued": True} if "queued" in ev else {"sent": True, "seq": ev.get("seq")})}

    @app.post("/v1/external/read", summary="A chat you started: its state, last answer, new messages and what waits for the user")
    def read(body: ReadIn, request: Request) -> dict:
        agent = A(request)
        return view(agent, external_of(agent, body.chat), body.after)

    @app.post("/v1/external/wait", summary="Wait (at most 60 s) for a chat you started to end its turn, then read it")
    async def wait(body: WaitIn, request: Request) -> dict:
        agent = A(request)
        external_of(agent, body.chat)
        deadline = time.monotonic() + body.timeout
        await asyncio.sleep(0.05)
        while agent.running(body.chat) and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
        out = view(agent, external_of(agent, body.chat))
        if out["running"]:
            out["note"] = (out.get("note", "") + " Still running: wait again.").strip()
        return out

    @app.post("/v1/external/stop", summary="Stop a chat you started (and its sub-agents)")
    async def stop(body: ChatIn, request: Request) -> dict:
        agent = A(request)
        external_of(agent, body.chat)
        await agent.cancel(body.chat)
        return {"chat": body.chat, "state": (agent.store.thread(body.chat) or {}).get("state")}

    @app.post("/v1/external/list", summary="The chats this client started over /mcp, newest first")
    def list_chats(body: Nothing, request: Request) -> dict:
        agent, client = A(request), client_of(request)
        rows = [t for t in agent.store.threads(limit=1000) + agent.store.threads(archived=True, limit=1000)
                if ((t.get("settings") or {}).get("external") or {}).get("client") == client]
        rows.sort(key=lambda t: t["updated"], reverse=True)
        return {"chats": [{"chat": t["id"], "title": t["title"], "state": t["state"], "updated": t["updated"],
                           "archived": t["archived"]} for t in rows[:50]]}
