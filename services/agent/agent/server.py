"""The agent mod's HTTP API (plan 14.4): threads, the event stream, answers, approvals, actions,
fork, cancel, compaction, the context meter, models, settings, status and the widget.

Environment: AGENT_DB, AGENT_DATA, AGENT_LLM_URL, AGENT_MODEL, AGENT_FALLBACK_MODEL,
AGENT_MAX_STEPS, AIHUB_URL, AIHUB_PORT.
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .hubapi import HubAPI, HubCallError
from .knowledge import Knowledge
from .llm import LLM
from .loop import Agent, Busy, Config
from .store import MODES, Store

PING_S = 15.0


class NewThread(BaseModel):
    title: str = ""
    model: str | None = None
    mode: Literal["ask", "auto", "read_only"] = "ask"
    settings: dict[str, Any] = Field(default_factory=dict, description="pinned / disabled groups (mod ids)")


class ThreadPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    mode: Literal["ask", "auto", "read_only"] | None = None
    archived: bool | None = None
    settings: dict[str, Any] | None = None


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    attachments: list[str] = Field(default_factory=list, description="output ids")


class Answer(BaseModel):
    question_id: str
    answers: dict[str, Any] = Field(description="question text → the chosen label(s) or typed text")


class ApprovalDecision(BaseModel):
    approval_id: str
    approve: bool
    arguments: dict[str, Any] | None = None
    reason: str | None = None


class Action(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Feedback(BaseModel):
    value: Literal["up", "down"]
    output_id: str | None = None        # thumbs on an output…
    seq: int | None = None              # …or on a reply (its assistant event)
    note: str = ""


class Fork(BaseModel):
    seq: int = Field(ge=0)


class AgentFiles(BaseModel):
    agent_md: str | None = None
    memory: str | None = None


def config_from_env() -> Config:
    data = Path(os.environ.get("AGENT_DATA") or "data/agent")
    return Config(model=os.environ.get("AGENT_MODEL", "skynet"), fallback=os.environ.get("AGENT_FALLBACK_MODEL") or None,
                  max_steps=int(os.environ.get("AGENT_MAX_STEPS", "25")), data=data,
                  default_window=int(os.environ.get("AGENT_DEFAULT_WINDOW", "32768")),
                  all_tools_models=tuple(m for m in os.environ.get("AGENT_ALL_TOOLS", "").split(",") if m))


log = logging.getLogger("agent")

async def _import_memory(k: Any) -> None:
    """Once, a little after start (the hub may still be starting): the old memory files → preferences."""
    for _ in range(10):
        try:
            n = await k.import_memory()
            if n:
                log.info("imported %d memory lines as preferences", n)
            return
        except Exception:  # noqa: BLE001
            await asyncio.sleep(30)


async def _upkeep(store: Store, stop: asyncio.Event, every: float = 3600) -> None:
    """Hourly: archived eval threads older than 30 days go (plan 21.1)."""
    while not stop.is_set():
        try:
            n = store.prune_dry_runs()
            if n:
                log.info("pruned %d old eval threads", n)
        except Exception:  # noqa: BLE001
            log.exception("pruning eval threads")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except asyncio.TimeoutError:
            pass


def create_app(cfg: Config | None = None, db: Path | None = None, hub_url: str | None = None, llm_url: str | None = None) -> FastAPI:
    cfg = cfg or config_from_env()
    db = db or Path(os.environ.get("AGENT_DB") or "agent.db")
    hub_url = hub_url or os.environ.get("AIHUB_URL", "http://127.0.0.1:7000")
    llm_url = llm_url or os.environ.get("AGENT_LLM_URL", "http://127.0.0.1:4000/v1")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db)
        hub, llm = HubAPI(hub_url), LLM(llm_url)
        agent = Agent(cfg, store, hub, llm)
        app.state.agent = agent
        stop = asyncio.Event()
        watcher = asyncio.create_task(hub.follow_events(agent.hub_event, stop))
        upkeep = asyncio.create_task(_upkeep(store, stop))
        from . import records
        from .knowledge import Knowledge

        async def turn_record(tid: str) -> None:
            await asyncio.to_thread(records.record, store, tid)
        agent.on_turn_end.append(turn_record)
        from .learn import mine
        last_mine = [0.0]

        async def mine_after(tid: str) -> None:              # plan 21.5: cheap, at most once a minute
            t = agent.store.thread(tid) or {}
            if (t.get("settings") or {}).get("dry_run") or time.time() - last_mine[0] < 60:
                return
            last_mine[0] = time.time()
            try:
                done = await mine.run(hub, store)
            except Exception:  # noqa: BLE001: learning never breaks a turn
                log.exception("the miner")
                return
            if done.get("proposed"):
                agent.emit(tid, "proposal", {"prefs": [{k: p.get(k) for k in ("id", "scope", "tool", "field", "value", "when", "cue")}
                                                       for p in done["proposed"]]})
        agent.on_turn_end.append(mine_after)
        importer = asyncio.create_task(_import_memory(Knowledge(cfg.data, hub)))
        await agent.resume_all()
        try:
            yield
        finally:
            stop.set()
            watcher.cancel()
            agent.shutting_down = True
            for t in list(agent.tasks.values()):
                t.cancel()
            upkeep.cancel()
            importer.cancel()
            await asyncio.gather(*agent.tasks.values(), watcher, upkeep, importer, return_exceptions=True)
            await hub.close()
            await llm.close()
            store.close()

    app = FastAPI(title="Agent", version="0.1.0", lifespan=lifespan,
                  description="AIHub's chat agent: one loop, tools on demand, questions and parameter cards (plan Phase 14).")

    def A(request: Request) -> Agent:
        return request.app.state.agent

    def thread_or_404(agent: Agent, tid: str) -> dict[str, Any]:
        t = agent.store.thread(tid)
        if t is None:
            raise HTTPException(404, f"no thread {tid!r}")
        return t

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/status", summary="Status for AIHub: threads, messages and tokens today, running turns")
    def status(request: Request) -> dict:
        agent = A(request)
        today = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        s = agent.store.stats(today)
        jobs = []
        for tid, t in agent.tasks.items():
            if not t.done():
                th = agent.store.thread(tid) or {}
                jobs.append({"id": tid, "label": th.get("title") or "chat", "progress": None, "state": "running",
                             "route": f"#/chat/{tid}"})
        return {"loaded": None, "busy": bool(jobs), "stats": [
            {"label": "Threads", "value": s["threads"]},
            {"label": "Messages today", "value": s["messages"], "reset": "daily"},
            {"label": "Tokens today", "value": s["tokens"], "reset": "daily"}], "jobs": jobs}

    @app.get("/v1/widgets/messages", summary="Messages per day (dashboard widget)")
    def widget_messages(request: Request, rng: str = Query("7d", alias="range")) -> dict:
        days = 30 if rng == "30d" else 7
        end = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)) + 86400
        t = [int(end - (days - i) * 86400) for i in range(days)]
        counts = [0] * days
        for ts, n in A(request).store.per_day(t[0]):
            i = int((ts - t[0]) // 86400)
            if 0 <= i < days:
                counts[i] += n
        return {"unit": "messages", "t": t, "series": [{"name": "Messages", "values": counts}]}

    @app.get("/v1/models", summary="Models from the relay with their facts (window, tools, vision), and the defaults")
    async def models(request: Request) -> dict:
        agent = A(request)
        data = await agent.llm.models(max_age=10)
        return {"default": agent.cfg.model, "fallback": agent.cfg.fallback,
                "models": [{"id": m["id"], "meta": m.get("meta") or {}, "endpoint": (m.get("relay") or {}).get("endpoint"),
                            "health": (m.get("relay") or {}).get("health")} for m in data
                           if (m.get("relay") or {}).get("protocol") != "opencode"]}

    # ---- threads -----------------------------------------------------------------------------

    @app.get("/v1/threads", summary="Threads, newest first; ?q= searches titles and messages")
    def list_threads(request: Request, q: str | None = None, archived: bool = False, limit: int = Query(200, ge=1, le=1000)) -> list[dict]:
        return A(request).store.threads(q, archived, limit)

    @app.post("/v1/threads", status_code=201, summary="Start a thread")
    def new_thread(body: NewThread, request: Request) -> dict:
        return A(request).store.create_thread(body.title, body.model, body.mode, body.settings)

    @app.get("/v1/threads/{tid}", summary="One thread")
    def get_thread(tid: str, request: Request) -> dict:
        agent = A(request)
        t = thread_or_404(agent, tid)
        t["running"] = agent.running(tid)
        return t

    @app.patch("/v1/threads/{tid}", summary="Rename, change model or mode, archive, or change tool groups")
    def patch_thread(tid: str, body: ThreadPatch, request: Request) -> dict:
        agent = A(request)
        t = thread_or_404(agent, tid)
        settings = None
        if body.settings is not None:
            settings = {**t["settings"], **body.settings}
        return agent.store.update_thread(tid, title=body.title, model=body.model, mode=body.mode, archived=body.archived,
                                         settings=settings) or {}

    @app.delete("/v1/threads/{tid}", summary="Delete a thread and its events")
    async def delete_thread(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        await agent.cancel(tid)
        agent.store.delete_thread(tid)
        return {"deleted": tid}

    @app.get("/v1/threads/{tid}/events", summary="The thread's events after a seq (replay after a reload)")
    def events(tid: str, request: Request, after: int = 0) -> list[dict]:
        agent = A(request)
        thread_or_404(agent, tid)
        return agent.store.events(tid, after)

    @app.get("/v1/threads/{tid}/stream", summary="Server-sent events: the events after `after`, then live events and deltas")
    async def stream(tid: str, request: Request, after: int = 0) -> StreamingResponse:
        agent = A(request)
        thread_or_404(agent, tid)
        q = agent.live.subscribe(tid)

        async def gen():
            last = after
            try:
                yield "retry: 2000\n\n"
                for ev in agent.store.events(tid, after):
                    last = ev["seq"]
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                yield f"data: {json.dumps({'type': 'ready', 'thread_id': tid, 'seq': last, 'running': agent.running(tid)})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=PING_S)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if ev.get("seq") is not None:
                        if ev["seq"] <= last:
                            continue
                        last = ev["seq"]
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            finally:
                agent.live.unsubscribe(tid, q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/v1/threads/{tid}/messages", status_code=202, summary="Send a message; during a turn it's queued for the next model call")
    async def send(tid: str, body: Message, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        return await agent.send(tid, body.text, body.attachments)

    @app.post("/v1/threads/{tid}/answer", status_code=202, summary="Answer an ask_user question card")
    async def answer(tid: str, body: Answer, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        try:
            return await agent.answer(tid, body.question_id, body.answers)
        except KeyError:
            raise HTTPException(404, f"no question {body.question_id!r}") from None
        except Busy as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/v1/threads/{tid}/approval", status_code=202, summary="Decide a parameter card (edited arguments are what runs)")
    async def approval(tid: str, body: ApprovalDecision, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        try:
            return await agent.approval(tid, body.approval_id, body.approve, body.arguments, body.reason)
        except KeyError:
            raise HTTPException(404, f"no approval {body.approval_id!r} in this thread") from None
        except HubCallError as e:
            raise HTTPException(e.status, {"code": e.code, "detail": e.detail, "data": e.data}) from None

    @app.post("/v1/threads/{tid}/action", status_code=202, summary="Run a tool directly (a button): no model call first")
    async def action(tid: str, body: Action, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        try:
            return await agent.action(tid, body.tool, body.arguments)
        except Busy as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/v1/threads/{tid}/fork", status_code=201, summary="Copy the events up to `seq` into a new thread (rewind and branch)")
    def fork(tid: str, body: Fork, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        return agent.store.fork(tid, body.seq)

    @app.post("/v1/threads/{tid}/cancel", summary="Stop the running turn (and its tool call), or dismiss a pending card")
    async def cancel(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        await agent.cancel(tid)
        return {"cancelled": tid, "state": (agent.store.thread(tid) or {}).get("state")}

    @app.post("/v1/threads/{tid}/feedback", summary="Thumbs up or down on an output or a reply (plan 21.4)")
    async def feedback(tid: str, body: Feedback, request: Request) -> dict:
        agent = A(request)
        thread = thread_or_404(agent, tid)
        if not body.output_id and body.seq is None:
            raise HTTPException(422, "give output_id or seq")
        payload = {"value": body.value, "note": body.note[:500],
                   **({"output_id": body.output_id.removeprefix("output:")} if body.output_id else {"seq": body.seq})}
        ev = agent.emit(tid, "feedback", payload)
        if body.output_id and not (thread.get("settings") or {}).get("dry_run"):
            try:
                await agent.hub.output_feedback(payload["output_id"], body.value, body.note[:500],
                                                {"service": "agent", "thread": tid, **({"no_learn": True} if (thread.get("settings") or {}).get("no_learn") else {})})
            except Exception as e:  # noqa: BLE001: the chat's own record stays
                log.warning("output feedback to the hub: %s", e)
        return {"seq": ev["seq"], **payload}

    @app.get("/v1/prefs", summary="The user's preferences, from the hub (for the Learning page)")
    async def list_prefs(request: Request, state: str | None = None, tool: str | None = None, scope: str | None = None) -> list:
        return await A(request).hub.prefs(state=state, tool=tool, scope=scope)

    @app.post("/v1/prefs", summary="Save a preference in the hub (the eval seeds them; the page adds them)")
    async def create_pref(body: dict, request: Request) -> dict:
        return await A(request).hub.create_pref(body)

    @app.delete("/v1/prefs/{pid}", summary="Forget a preference")
    async def delete_pref(pid: str, request: Request) -> dict:
        return await A(request).hub.delete_pref(pid)

    @app.post("/v1/prefs/{pid}/{verb}", summary="Approve or reject a proposed preference (verb: approve | reject)")
    async def decide_pref(pid: str, verb: Literal["approve", "reject"], request: Request) -> dict:
        return await A(request).hub.decide_pref(pid, verb == "approve")

    @app.post("/v1/learn/mine", summary="Run the miner now: propose preferences from card edits, answers and thumbs")
    async def mine_now(request: Request) -> dict:
        from .learn import mine
        agent = A(request)
        done = await mine.run(agent.hub, agent.store)
        return {k: [p.get("id") for p in v] if isinstance(v, list) else v for k, v in done.items()}

    @app.get("/v1/threads/{tid}/turns", summary="The thread's turn records (plan 21.4)")
    async def thread_turns(tid: str, request: Request) -> list:
        from . import records
        agent = A(request)
        thread_or_404(agent, tid)
        return records.turns(agent.store, tid)

    @app.post("/v1/threads/{tid}/compact", summary="Compact the thread now (/compact)")
    async def compact(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        try:
            return await agent.compact(tid)
        except Busy as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/v1/threads/{tid}/context", summary="The context meter: used / window and the breakdown")
    async def context(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        return await agent.meter(tid)

    # ---- settings ----------------------------------------------------------------------------

    @app.get("/v1/settings", summary="AGENT.md, the memory index, topics, skills and the defaults")
    async def get_settings(request: Request) -> dict:
        agent = A(request)
        k = Knowledge(agent.cfg.data, agent.hub)
        return {**k.files(), "skills": await k.skills(), "model": agent.cfg.model, "fallback": agent.cfg.fallback,
                "max_steps": agent.cfg.max_steps, "modes": list(MODES)}

    @app.put("/v1/settings", summary="Save AGENT.md and/or the memory index")
    async def put_settings(body: AgentFiles, request: Request) -> dict:
        agent = A(request)
        Knowledge(agent.cfg.data, agent.hub).save(body.agent_md, body.memory)
        return await get_settings(request)

    return app
