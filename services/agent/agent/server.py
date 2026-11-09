"""The agent mod's HTTP API (plan 14.4): threads, the event stream, answers, approvals, actions,
fork, cancel, compaction, the context meter, models, settings, status and the widget.

Environment: AGENT_DB, AGENT_DATA, AGENT_LLM_URL, AGENT_MODEL, AGENT_FALLBACK_MODEL,
AGENT_MAX_STEPS, GAIFA_URL, GAIFA_PORT.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .hubapi import HubAPI, HubCallError
from . import api_imports, api_memory, api_projects, api_skills, api_summaries, api_tasks, api_workflows, docs
from .knowledge import Knowledge
from .llm import LLM
from .loop import Agent, Busy, Config
from .store import MODES, Store
from .streams import add_stream_routes
from .api_queue import add_queue_routes

PING_S = 15.0
QUOTE_MAX = 8000         # characters of a quoted reply (Select → Reply)
REPLY_MAX = 4000         # characters of the user's reply to one quoted part
QUOTES_TOTAL = 200_000   # characters of quoted parts and replies in one message, in all (no limit on how many)


class ThreadPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    mode: Literal["plan", "manual", "accept_edits", "auto", "bypass", "ask", "read_only"] | None = None
    archived: bool | None = None
    settings: dict[str, Any] | None = None


class Quote(BaseModel):
    text: str = Field(min_length=1, max_length=QUOTE_MAX, description="the quoted part of an earlier reply, as markdown")
    seq: int | None = Field(None, ge=1, description="the assistant event it came from")


class QuoteReply(BaseModel):
    text: str = Field(min_length=1, max_length=QUOTE_MAX, description="the quoted part of an earlier reply, as markdown")
    reply: str = Field("", max_length=REPLY_MAX, description="the user's reply to that part")
    seq: int | None = Field(None, ge=1, description="the assistant event it came from")


class Mention(BaseModel):
    kind: str = Field(max_length=24)
    id: str = Field(max_length=300)
    label: str = Field("", max_length=300)
    fills: list[str] = Field(default_factory=list, max_length=12, description="<tool>.<field>, e.g. tts_speak.name")


class Message(BaseModel):
    text: str = Field("", max_length=100_000, description="may be empty when a quote-reply says something")
    quotes: list[QuoteReply] | None = Field(None, description="parts of earlier replies and the user's reply to each, in order "
                                                             "(Select → Reply); any number")
    quote: Quote | None = Field(None, description="older clients: one quoted part with no reply (stored as `quotes`)")
    attachments: list[str] = Field(default_factory=list, description="output ids")
    doc_modes: dict[str, Literal["auto", "whole", "card"]] = Field(default_factory=dict,
                                                                   description="per attached document: whole, card, or auto (plan 24.9)")
    mentions: list[Mention] = Field(default_factory=list, max_length=20,
                                    description="plan 48.3: what the message @-mentions; fills that turn's calls")
    client_id: str | None = Field(None, max_length=64, description="chat-responsive 1.1: the page's id for the message, "
                                                                  "kept on its user event so the page can match what it drew")
    when: Literal["auto", "queue", "now"] = Field("auto", description="chat-responsive 2.1: during a turn (or while a card waits), "
                                                    "auto and queue hold it until the turn ends (answering {queued}); now "
                                                    "writes it at once, for the turn's next model call")


class NewThread(BaseModel):
    title: str = ""
    model: str | None = None
    mode: Literal["plan", "manual", "accept_edits", "auto", "bypass", "ask", "read_only"] = "manual"   # old names map over
    settings: dict[str, Any] = Field(default_factory=dict, description="pinned / disabled groups (mod ids)")
    message: Message | None = Field(None, description="chat-responsive 1.2: the first message, sent in the same call")


class Answer(BaseModel):
    question_id: str
    answers: dict[str, Any] = Field(description="question text → the chosen label(s) or typed text")


class ApprovalDecision(BaseModel):
    approval_id: str
    approve: bool
    arguments: dict[str, Any] | None = None
    reason: str | None = None
    remember: Literal["once", "thread", "always", "sites"] = Field("once", description="thread / always: the hub also allows "
                                                                   "calls like this one (plan 25.2); sites: a web tool on any site, in this chat (web-approvals)")
    confirm: bool = Field(False, description="the second confirm an always grant for execute and destructive tools needs")


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


class DocSettings(BaseModel):
    inline_tokens: int | Literal["window"] | None = Field(None, description='Whole documents up to this many tokens, or "window"')
    reply_reserve: int | None = Field(None, ge=0, description="Tokens kept free for the reply and tools")
    project_share: float | None = Field(None, ge=0, le=0.9, description="The share of the window a project's files and pages "
                                                                        "fill whole before they are listed (plan projects 3.3)")


class MemorySettings(BaseModel):
    recall: bool | None = Field(None, description="Recall memories in each message (structured-memory 3.3)")
    fade_days: int | None = Field(None, ge=7, le=3650, description="Learned facts unused this long are proposed for retiring (4.2)")
    interest_days: int | None = Field(None, ge=14, le=730, description="An interest not said this long becomes an earlier one (memory-auto-learning 3.2)")
    auto_approve: bool | None = Field(None, description="Save learned facts without asking when grounded, confident and not sensitive (memory-auto-learning 2.1)")
    auto_threshold: float | None = Field(None, ge=0.5, le=1, description="How sure the learner must be to save without asking")
    auto_after_seen: int | None = Field(None, ge=2, le=20, description="A proposal said this many times is saved without asking")
    always_review: list[Literal["health", "money", "legal", "relationships", "religion", "politics", "sexuality"]] | None = Field(
        None, description="Topics whose facts always wait for review")


class AgentFiles(BaseModel):
    agent_md: str | None = None
    memory: str | None = None
    documents: DocSettings | None = None
    memory_settings: MemorySettings | None = None


def config_from_env() -> Config:
    data = Path(os.environ.get("AGENT_DATA") or "data/agent")
    return Config(model=os.environ.get("AGENT_MODEL", "skynet"), fallback=os.environ.get("AGENT_FALLBACK_MODEL") or None,
                  max_steps=int(os.environ.get("AGENT_MAX_STEPS", "25")), data=data,
                  default_window=int(os.environ.get("AGENT_DEFAULT_WINDOW", "32768")),
                  inline_tokens=int(os.environ.get("AGENT_INLINE_TOKENS", "6000")),
                  reply_reserve=int(os.environ.get("AGENT_REPLY_RESERVE", "4096")),
                  summary_idle_min=float(os.environ.get("AGENT_SUMMARY_IDLE_MIN", "30")),
                  all_tools_models=tuple(m for m in os.environ.get("AGENT_ALL_TOOLS", "").split(",") if m))


log = logging.getLogger("agent")

async def _import_memory(agent: Any) -> None:
    """Once, a little after start (the hub may still be starting): the agent preferences and the old memory files
    become facts (plan structured-memory 1.3)."""
    from .memory import importer
    for _ in range(10):
        try:
            n = await importer.run(agent.memory, agent.hub, agent.cfg.data)
            if n:
                log.info("imported %d memories as facts", n)
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


ArchivedQ = Literal["false", "true", "all"]   # the thread list's ?archived= (plan chat-history 1.1)


def archived_of(value: str) -> bool | None:
    """`all` lists live and archived chats together (None to the store)."""
    return None if value == "all" else value == "true"


def envs_of(environment: str | None) -> list[str] | None:
    return [e.strip() for e in (environment or "").split(",") if e.strip()] or None


GROUP_ORDER = {"local": 0, "remote": 1, "cloud": 2}


def model_list(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The relay's catalog as the Chat page and Settings pick from it (plan llm-servers 2.2): each model with its
    server, where that server runs, its provider and facts; this machine first, then remote, then cloud.
    OpenCode's agent models are left out (the chat agent can't run its tools through another agent)."""
    out, seen = [], set()
    for m in data:
        r = m.get("relay") or {}
        if r.get("protocol") == "opencode" or m.get("id") == "auto" and not r or m.get("id") in seen:   # the relay may list an id twice
            continue
        seen.add(m.get("id"))
        group = r.get("group") or "local"
        out.append({"id": m["id"], "name": r.get("display_name") or m["id"], "meta": m.get("meta") or {},
                    "endpoint": r.get("endpoint"), "server": r.get("alias") or r.get("endpoint"), "group": group,
                    "provider": r.get("protocol") or "openai", "health": r.get("health"), "cloud": group == "cloud"})
    return sorted(out, key=lambda m: GROUP_ORDER.get(m["group"], 3))


def check_quotes(agent: Agent, tid: str, body: Message) -> list[dict[str, Any]]:
    """The message's quote-replies as stored, `[{text, reply, seq?}]` (any number of them); the older single `quote`
    becomes one with an empty reply. 422 `invalid_quote`: both given, a blank quoted part, a seq that isn't a reply
    here, or more than QUOTES_TOTAL characters of quotes and replies in all."""
    if body.quotes is not None and body.quote is not None:
        raise HTTPException(422, {"code": "invalid_quote", "detail": "send `quotes` or the older `quote`, not both"})
    items = [QuoteReply(text=body.quote.text, seq=body.quote.seq)] if body.quote is not None else list(body.quotes or [])
    total = sum(len(q.text) + len(q.reply) for q in items)
    if total > QUOTES_TOTAL:
        raise HTTPException(422, {"code": "invalid_quote", "detail": f"the quoted parts and replies are {total:,} characters "
                                  f"in all; at most {QUOTES_TOTAL:,} (send some in a second message)"})
    seqs = {e["seq"] for e in agent.store.events(tid, types=("assistant",))} if any(q.seq is not None for q in items) else set()
    out = []
    for i, q in enumerate(items, 1):
        if not q.text.strip():
            raise HTTPException(422, {"code": "invalid_quote", "detail": f"quote {i} is empty"})
        if q.seq is not None and q.seq not in seqs:
            raise HTTPException(422, {"code": "invalid_quote", "detail": f"quote.seq {q.seq} isn't a reply in this chat"})
        out.append({"text": q.text, "reply": q.reply, **({"seq": q.seq} if q.seq is not None else {})})
    return out


def create_app(cfg: Config | None = None, db: Path | None = None, hub_url: str | None = None, llm_url: str | None = None) -> FastAPI:
    cfg = cfg or config_from_env()
    db = db or Path(os.environ.get("AGENT_DB") or "agent.db")
    hub_url = hub_url or os.environ.get("GAIFA_URL", "http://127.0.0.1:7000")
    llm_url = llm_url or os.environ.get("AGENT_LLM_URL", "http://127.0.0.1:4000/v1")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db)
        hub, llm = HubAPI(hub_url), LLM(llm_url)
        agent = Agent(cfg, store, hub, llm)
        app.state.agent = agent
        api_projects.install(agent)                                  # plan projects: what deleting one also removes
        api_tasks.install(agent)                                     # plan scheduled-tasks 1.3: a deleted project detaches its tasks
        stop = asyncio.Event()
        watcher = asyncio.create_task(hub.follow_events(agent.hub_event, stop))
        upkeep = asyncio.create_task(_upkeep(store, stop))
        from . import records

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
        importer = asyncio.create_task(_import_memory(agent))
        from .learn.loop import Learner
        from .learn.schedule import Schedule
        app.state.learner = Learner(agent, base=f"{hub_url.rstrip('/')}/api/s/agent")       # plan 22.5–22.6
        app.state.schedule = Schedule(agent, app.state.learner)
        scheduler = asyncio.create_task(app.state.schedule.run_forever(stop))
        from .summaries import Summaries
        agent.summaries = Summaries(agent, cfg.summary_idle_min)                             # plan 28.5
        summarizer = asyncio.create_task(agent.summaries.run_forever(stop))
        from .memory.index import MemoryIndex
        agent.memory_index = MemoryIndex(agent.memory, hub)                                  # structured-memory 2.2
        indexer = asyncio.create_task(agent.memory_index.run_forever(stop))
        from .memory.learn import MemoryLearner
        agent.memory_learner = MemoryLearner(agent, cfg.summary_idle_min)                    # structured-memory 4.1
        mem_learner = asyncio.create_task(agent.memory_learner.run_forever(stop))
        from .memory.imports import Importer
        agent.memory_importer = Importer(agent)                                              # memory-import 1.4
        from .tasks.runner import Runner
        from .tasks.schedule import TaskSchedule
        agent.runner = Runner(agent)                                                         # scheduled-tasks 2.2–2.3
        app.state.task_schedule = TaskSchedule(agent, agent.runner)
        task_scheduler = asyncio.create_task(app.state.task_schedule.run_forever(stop))
        await agent.resume_all()
        try:
            yield
        finally:
            stop.set()
            watcher.cancel()
            agent.shutting_down = True
            for t in list(agent.tasks.values()) + list(getattr(agent, "project_tasks", ())):   # project fetches, indexing
                t.cancel()
            upkeep.cancel()
            importer.cancel()
            scheduler.cancel()
            summarizer.cancel()
            indexer.cancel()
            mem_learner.cancel()
            task_scheduler.cancel()
            await asyncio.gather(*agent.tasks.values(), watcher, upkeep, importer, scheduler, summarizer, indexer, mem_learner,
                                 task_scheduler, return_exceptions=True)
            await hub.close()
            await llm.close()
            store.close()

    app = FastAPI(title="Agent", version="0.1.0", lifespan=lifespan,
                  description="GAIFA's chat agent: one loop, tools on demand, questions and parameter cards (plan Phase 14).")
    api_summaries.add_routes(app)                                    # plan 28.5
    api_skills.add_routes(app)                                       # skill-sources 3.1
    api_memory.add_routes(app)                                       # structured-memory 1.2
    api_imports.add_routes(app)                                      # memory-import 1.4
    api_projects.add_routes(app)                                     # plan projects 1.2
    api_tasks.add_routes(app)                                        # plan scheduled-tasks 1.3
    api_workflows.add_routes(app)                                    # plan agent-workflows 1.1

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

    @app.get("/v1/status", summary="Status for GAIFA: threads, messages and tokens today, running turns")
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
        run = getattr(request.app.state, "learner", None) and request.app.state.learner.running
        if run:                                  # the learner's run, with its stage (plan 22.6)
            jobs.append({"id": run["id"], "label": f"Learning: {run['stage']}", "progress": None, "state": "running",
                         "route": "#/s/agent/runs"})
        review = agent.memory.count_facts("proposed")
        return {"loaded": None, "busy": bool(jobs), "stats": [
            {"label": "Threads", "value": s["threads"]},
            {"label": "Memories to review", "value": review},          # structured-memory 5.1
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

    @app.get("/v1/widgets/corrections", summary="Cards the user changed per day, and cards shown (dashboard widget, plan 21.7)")
    def widget_corrections(request: Request, rng: str = Query("7d", alias="range")) -> dict:
        days = 30 if rng == "30d" else 7
        end = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)) + 86400
        t = [int(end - (days - i) * 86400) for i in range(days)]
        edits, cards = [0] * days, [0] * days
        st = A(request).store
        with st._lock:
            rows = st._c.execute("SELECT t.started, t.edits, (SELECT count(*) FROM events e WHERE e.thread_id = t.thread_id AND e.type = 'approval' "
                                 "AND e.ts >= t.started AND e.ts <= COALESCE(t.ended, t.started)) FROM turns t JOIN threads th ON th.id = t.thread_id "
                                 "WHERE t.started >= ? AND json_extract(th.settings, '$.dry_run') IS NULL", (t[0],)).fetchall()
        for started, ed, n in rows:
            i = int((started - t[0]) // 86400)
            if 0 <= i < days:
                edits[i] += ed or 0
                cards[i] += n or 0
        return {"unit": "cards", "t": t, "series": [{"name": "Changed by you", "values": edits}, {"name": "Cards", "values": cards}]}

    @app.get("/v1/learn/usage", summary="Per-tool usage from the hub (calls, errors, cards, cards you changed), for the Learning page")
    async def learn_usage(request: Request, days: float = 30) -> list:
        return await A(request).hub._json("GET", "/api/tools/usage", params={"days": days})

    @app.patch("/v1/prefs/{pid}", summary="Change a preference")
    async def patch_pref(pid: str, body: dict, request: Request) -> dict:
        return await A(request).hub.update_pref(pid, body)

    @app.get("/v1/models", summary="Models from the relay with their facts (window, tools, vision), grouped by server "
             "(this machine, remote, cloud), and the defaults")
    async def models(request: Request) -> dict:
        agent = A(request)
        data = await agent.llm.models(max_age=10)
        return {"default": agent.cfg.model, "fallback": agent.cfg.fallback, "models": model_list(data)}

    # ---- threads -----------------------------------------------------------------------------

    @app.get("/v1/threads", summary="Threads, newest first; ?q= searches titles and messages; ?environment= only those "
             "environments' chats (comma-separated; `default` also matches chats without one)")
    def list_threads(request: Request, q: str | None = None, archived: ArchivedQ = "false",
                     limit: int = Query(200, ge=1, le=1000),
                     environment: str | None = Query(None, description="Environment ids, comma-separated (plan 41.1)"),
                     sort: Literal["updated", "created", "title"] = "updated", offset: int = Query(0, ge=0),
                     project: str | None = Query(None, description="Project ids, comma-separated; `none`: chats in no project "
                                                                    "(plan projects 1.2)"),
                     task: str | None = Query(None, description="Scheduled task ids, comma-separated: their run chats; `none`: "
                                                                 "chats no task started (plan scheduled-tasks 1.3)"),
                     children: bool = Query(False, description="Sub-agents too (a search always finds them; plan agent-workflows 1.1)")
                     ) -> list[dict]:
        return A(request).store.threads(q, archived_of(archived), limit, environment=envs_of(environment), sort=sort,
                                        offset=offset, project=envs_of(project), task=envs_of(task), children=children)

    @app.get("/v1/threads/count", summary="How many threads /v1/threads would list with the same filters, no limit")
    def count_threads(request: Request, q: str | None = None, archived: ArchivedQ = "false",
                      environment: str | None = Query(None, description="Environment ids, comma-separated"),
                      project: str | None = Query(None, description="Project ids, comma-separated (`none`: in no project)"),
                      children: bool = False) -> dict:
        return {"count": A(request).store.count(q, archived_of(archived), environment=envs_of(environment),
                                                project=envs_of(project), children=children)}

    @app.get("/v1/threads/groups", summary="Per environment the chats use: how many, the newest activity, and how many "
             "are running or waiting (`default` for chats without one); ?by=project: per project (`none` for chats in none)")
    def thread_groups(request: Request, archived: ArchivedQ = "false",
                      by: Literal["environment", "project"] = "environment") -> list[dict]:
        return A(request).store.groups(archived_of(archived), by=by)

    async def check_model(agent: Agent, model: str | None) -> None:
        """A chat's model must be one the relay serves (plan llm-servers 2.2); with the relay unreachable, anything goes."""
        if not model:
            return
        if model in [m["id"] for m in model_list(await agent.llm.models(max_age=float("inf")))]:
            return                  # known already: no wait for the relay (chat-responsive 1.2)
        ids = [m["id"] for m in model_list(await agent.llm.models(max_age=10))]
        if ids and model not in ids:
            near = difflib.get_close_matches(model, ids, n=3, cutoff=0.4)
            raise HTTPException(400, f"the relay doesn't serve {model!r}" + (f"; did you mean {', '.join(near)}?" if near else ""))

    @app.post("/v1/threads", status_code=201, summary="Start a thread")
    async def new_thread(body: NewThread, request: Request) -> dict:
        """With a `message`, the thread and its first message in one call: the thread, with that message's `event`."""
        agent = A(request)
        settings, model, mode = api_projects.new_chat(agent, dict(body.settings), body.model,
                                                      body.mode if "mode" in body.model_fields_set else None)
        await check_model(agent, model)
        if body.message is not None:
            check_message(agent, None, body.message)
        th = agent.store.create_thread(body.title, model, mode or body.mode, settings)
        if body.message is not None:
            th["event"] = await send_message(agent, th["id"], body.message)
        return th

    @app.get("/v1/threads/{tid}", summary="One thread")
    def get_thread(tid: str, request: Request) -> dict:
        agent = A(request)
        t = thread_or_404(agent, tid)
        t["running"] = agent.running(tid)
        return t

    @app.patch("/v1/threads/{tid}", summary="Rename, change model or mode, archive, or change tool groups")
    async def patch_thread(tid: str, body: ThreadPatch, request: Request) -> dict:
        agent = A(request)
        t = thread_or_404(agent, tid)
        await check_model(agent, body.model)
        settings = None
        if body.settings is not None:
            settings = api_projects.move_chat(agent, t["settings"], body.settings)   # into a project or out (plan projects 1.2)
        return agent.store.update_thread(tid, title=body.title, model=body.model, mode=body.mode, archived=body.archived,
                                         settings=settings) or {}

    @app.delete("/v1/threads/{tid}", summary="Delete a thread and its events")
    async def delete_thread(tid: str, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        children = await api_workflows.delete_children(agent, tid)    # its sub-agents go with it (agent-workflows 1.1)
        await agent.cancel(tid)
        agent.store.delete_thread(tid)
        await agent.hub.end_grants(tid)      # "allow in this chat" ends with the chat (plan 25.2)
        if getattr(agent, "summaries", None):
            await agent.summaries.forget(tid)   # its summary and vector go too (plan 28.5)
        return {"deleted": tid, **({"children": children} if children else {})}

    @app.get("/v1/threads/{tid}/events", summary="The thread's events after a seq (replay after a reload)")
    def events(tid: str, request: Request, after: int = 0) -> list[dict]:
        agent = A(request)
        thread_or_404(agent, tid)
        return agent.store.events(tid, after)

    add_stream_routes(app, A, thread_or_404, PING_S)                 # one thread's stream, and several on one (plan chat-split 3.1)
    add_queue_routes(app, A, thread_or_404)                          # messages held during a turn (chat-responsive 2.1)

    @app.post("/v1/threads/{tid}/messages", status_code=202, summary="Send a message; during a turn it's held until the turn ends "
              "(`when: now`: read at the turn's next model call)")
    async def send(tid: str, body: Message, request: Request) -> dict:
        agent = A(request)
        thread_or_404(agent, tid)
        return await send_message(agent, tid, body)

    def check_message(agent: Agent, tid: str | None, body: Message) -> list[dict[str, Any]]:
        """The message's quote-replies, checked (`tid` None: a new thread, where no reply can be named), or a 422."""
        quotes = check_quotes(agent, tid or "", body)
        if not body.text.strip() and not any(q["reply"].strip() for q in quotes):
            raise HTTPException(422, {"code": "empty_message" if not quotes else "invalid_quote",
                                      "detail": "the message is empty" if not quotes else "say something: a reply to a quoted part or a message"})
        return quotes

    async def send_message(agent: Agent, tid: str, body: Message) -> dict:
        quotes = check_message(agent, tid, body)
        return await agent.send(tid, body.text, body.attachments, body.doc_modes, quotes=quotes,
                                mentions=[m.model_dump() for m in body.mentions], client_id=body.client_id, when=body.when)

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
            return await agent.approval(tid, body.approval_id, body.approve, body.arguments, body.reason,
                                        body.remember, body.confirm)
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

    @app.post("/v1/learn/run", summary="Learn now: one improvement run over the domains with new chats (plan 22.6)")
    async def learn_now(request: Request, body: dict | None = None) -> dict:
        sch = request.app.state.schedule
        if not (await sch.settings()).get("enabled", True):
            raise HTTPException(409, "learning is turned off (Settings → Agent → Learning)")
        started = sch.start("manual", (body or {}).get("domains"))
        return {"started": started, "running": (request.app.state.learner.running or {}).get("id")}

    @app.get("/v1/learn/runs", summary="The learner's runs, newest first, and the one running now")
    def learn_runs(request: Request) -> dict:
        lr = request.app.state.learner
        return {"running": lr.running, "runs": lr.runs()}

    @app.get("/v1/learn/runs/{rid}", summary="One run: its stages, candidates, replays, gate, decision and ledger")
    def learn_run(rid: str, request: Request) -> dict:
        lr = request.app.state.learner
        if lr.running and lr.running["id"] == rid:
            return lr.running
        hit = next((r for r in lr.runs(200) if r["id"] == rid), None)
        if hit is None:
            raise HTTPException(404, f"no run {rid!r}")
        return hit

    @app.post("/v1/learn/runs/{rid}/cancel", summary="Stop the running learner run")
    def learn_cancel(rid: str, request: Request) -> dict:
        sch, lr = request.app.state.schedule, request.app.state.learner
        if lr.running and lr.running["id"] == rid and sch.task and not sch.task.done():
            sch.task.cancel()
            return {"cancelled": rid}
        raise HTTPException(409, f"run {rid!r} isn't running")

    @app.get("/v1/learn/library", summary="The learner's lessons, by domain")
    def learn_library(request: Request) -> dict:
        from .learn.library import Library
        from .learn.loop import DOMAINS
        return {d: Library(A(request).cfg.data, d).listing() for d in DOMAINS}

    @app.post("/v1/learn/mine", summary="Run the miner now: propose preferences from card edits, answers and thumbs")
    async def mine_now(request: Request) -> dict:
        from .learn import mine
        agent = A(request)
        done = await mine.run(agent.hub, agent.store)
        return {k: [p.get("id") for p in v] if isinstance(v, list) else v for k, v in done.items()}

    # ---- the harness (plan 22.1) ----------------------------------------------------------------
    def H(request: Request) -> Any:
        from .harness import Harness
        return Harness(A(request).cfg.data)

    @app.get("/v1/harness", summary="The active harness version and its files (systemprompt, guardrails, hooks, tool notes, skills)")
    def harness_now(request: Request) -> dict:
        h = H(request)
        n = h.current()
        return {"current": n, "files": h.tree(n), "versions": h.versions()}

    @app.get("/v1/harness/versions", summary="Every harness version: parent, who adopted it, the composer's notes, the gate's results")
    def harness_versions(request: Request) -> list:
        return H(request).versions()

    @app.get("/v1/harness/versions/{n}/diff", summary="What version n changes against ?against= (default: its parent), as a unified diff")
    def harness_diff(n: int, request: Request, against: int | None = None) -> dict:
        from .harness import HarnessError
        h = H(request)
        try:
            base = against if against is not None else (h.meta(n).get("parent") or 0)
            return {"n": n, "against": base, "diff": h.diff(base, n)}
        except HarnessError as e:
            raise HTTPException(404, str(e)) from None

    @app.post("/v1/harness/versions/{n}/activate", summary="Make version n the active harness (0 = the base): forward or rollback")
    def harness_activate(n: int, request: Request) -> dict:
        from .harness import HarnessError
        h = H(request)
        try:
            h.activate(n)
        except HarnessError as e:
            raise HTTPException(404, str(e)) from None
        if n and h.meta(n).get("adopted_by") == "proposed":
            h.set_meta(n, adopted_by="user")
        return {"current": h.current()}

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
        from .memory import auto, profile, tidy
        m = agent.memory
        mem = {"settings": {"fade_days": tidy.FADE_DAYS, **auto.DEFAULTS, **profile.settings(agent.cfg.data)},
               "facts": len(m.facts(current=True, limit=100000)), "entities": len(m.entities()) - 1, "proposed": m.count_facts("proposed")}
        return {**k.files(), "memory_settings": mem["settings"], "memory_stats": {k_: v for k_, v in mem.items() if k_ != "settings"},
                "skills": await k.skills(), "model": agent.cfg.model, "fallback": agent.cfg.fallback,
                "max_steps": agent.cfg.max_steps, "modes": list(MODES), "documents": docs.load(agent.cfg.data, agent.cfg)}

    @app.put("/v1/settings", summary="Save AGENT.md, the document settings and/or memory's settings (recall, fade_days, auto-approval)")
    async def put_settings(body: AgentFiles, request: Request) -> dict:
        agent = A(request)
        Knowledge(agent.cfg.data, agent.hub).save(body.agent_md, body.memory)
        if body.documents is not None:
            try:
                docs.save(agent.cfg.data, agent.cfg, body.documents.model_dump(exclude_none=True))
            except docs.SettingsError as e:
                raise HTTPException(422, str(e)) from None
        if body.memory_settings is not None:                  # structured-memory 5.2: data/agent/memory.json
            from .memory import profile
            cur = {**profile.settings(agent.cfg.data), **body.memory_settings.model_dump(exclude_none=True)}
            agent.cfg.data.mkdir(parents=True, exist_ok=True)
            tmp = agent.cfg.data / "memory.json.part"
            tmp.write_text(json.dumps(cur, indent=1))
            tmp.replace(agent.cfg.data / "memory.json")
        return await get_settings(request)

    return app
