"""The loop (plan 14.4): one turn = call the model, run its tool calls, append the results, repeat
until a reply has no tool calls.

- **Stops:** done; `max_steps` (an honest note, not an invented answer); an error; cancel.
- **Pauses:** an `ask_user` question or a hub approval ends the turn as `waiting`; the answer or
  decision is appended and the same turn continues from the log. Nothing waits in memory, so a
  restart loses nothing; a thread left `running` by a crash resumes at startup.
- **Queued messages:** a message sent during a turn is appended at once and read at the next
  model call, after the current tool calls.
- **Buttons:** an action appends a user-initiated tool call and runs it with no model call; the
  model sees it next time the user writes.
- **Fallback:** if the thread's model doesn't answer, the turn continues on the fallback model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import context as ctx
from .compaction import Compaction
from .prompting import Prompting, thread_settings
from .queue import Queue, Queueing
from . import links
from .docs import describe as describe_docs
from . import prompts
from .hubapi import HubAPI
from .llm import LLM, THREAD
from .store import Store, mode_of, new_id
from .tools import LOCAL_NAMES, ToolSet

log = logging.getLogger("agent.loop")
POLL_S = 15
RECALL_WAIT_S = 10       # chat-responsive 1.1: how long a model call waits for its messages' recall
SERVICE_TOOLS = {"hub_start_service", "hub_stop_service", "hub_unload_service"}   # their `id` is a mod


@dataclass
class Config:
    model: str = "skynet"
    fallback: str | None = None
    max_steps: int = 25
    default_window: int = 32768
    data: Any = None   # Path of data/agent
    all_tools_models: tuple[str, ...] = ()
    inline_tokens: int = 6000   # an attached document up to this size goes in whole (Settings → Agent can change it; docs.py)
    reply_reserve: int = 4096   # tokens kept free for the reply and tools when documents go in whole (plan 24.9)
    summary_idle_min: float = 30   # a chat quiet this long gets its summary for search (plan 28.5)


@dataclass
class Live:
    """Per-thread subscribers (SSE)."""

    subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = field(default_factory=dict)
    watchers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)   # /v1/streams?watch=projects (plan projects 1.2)

    def broadcast(self, ev: dict[str, Any]) -> None:
        """An event about no one chat (a project changed) to every stream that watches for them."""
        for q in list(self.watchers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    def publish(self, tid: str, ev: dict[str, Any]) -> None:
        for q in list(self.subs.get(tid, ())):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    def subscribe(self, tid: str, q: asyncio.Queue[dict[str, Any]] | None = None) -> asyncio.Queue[dict[str, Any]]:
        """A queue for this thread's events; pass one to share it across threads (`/v1/streams`, plan chat-split 3.1)."""
        q = q if q is not None else asyncio.Queue(2000)
        self.subs.setdefault(tid, set()).add(q)
        return q

    def unsubscribe(self, tid: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subs.get(tid, set()).discard(q)


class Busy(Exception):
    pass


class Agent(Compaction, Queueing, Prompting):
    def __init__(self, cfg: Config, store: Store, hub: HubAPI, llm: LLM) -> None:
        from .local import Local

        self.cfg, self.store, self.hub, self.llm = cfg, store, hub, llm
        from .memory.store import MemoryStore
        self.memory = MemoryStore(store)          # plan structured-memory 1.1
        from .projects.store import ProjectStore
        self.projects = ProjectStore(store)       # plan projects 1.1
        self.project_created: list[Any] = []      # async (agent, project): its memory entity (4.2)
        self.project_changed: list[Any] = []      # async (agent, old, new): a rename renames the entity (4.2)
        self.project_cleanup: list[tuple[str, Any]] = []   # (step, async (agent, project)) when one is deleted (api_projects)
        from .tasks.store import TaskStore
        self.scheduled = TaskStore(store)         # plan scheduled-tasks 1.2 (`tasks` holds the running turns)
        self.runner: Any = None                   # tasks/runner.Runner, made in the app's lifespan (2.2)
        self.live = Live()
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.local = Local(self)
        self.on_turn_end: list[Callable[[str], Awaitable[None]]] = []
        self._deciding: set[str] = set()
        self._recalls: dict[str, set[asyncio.Task[Any]]] = {}   # chat-responsive 1.1: recall runs after the user event
        self._read_upto: dict[str, int] = {}     # the last seq the turn's latest model call read
        self._ending: dict[str, asyncio.Task[Any]] = {}          # a turn in its turn-end hooks: no longer busy
        self.queue = Queue(store)                # chat-responsive 2.1: messages held during a turn
        self._drains: set[asyncio.Task[Any]] = set()
        self._prompts: dict[str, tuple[str, float, dict[str, int]]] = {}   # the turn's last prompt sizes, for the meter
        self._titles: dict[str, str] = {}        # a new chat's words, to name it once its first reply is under way
        self.shutting_down = False   # set before the app stops: turns then stay `running` and resume at the next start

    # ---- events ------------------------------------------------------------------------------

    def emit(self, tid: str, type_: str, payload: dict[str, Any], tokens: int = 0) -> dict[str, Any]:
        ev = self.store.append(tid, type_, payload, tokens)
        self.live.publish(tid, ev)
        return ev

    def transient(self, tid: str, type_: str, payload: dict[str, Any]) -> None:
        self.live.publish(tid, {"thread_id": tid, "seq": None, "type": type_, "payload": payload, "ts": time.time()})

    def set_state(self, tid: str, state: str, reason: str | None = None) -> None:
        self.store.update_thread(tid, state=state)
        self.emit(tid, "state", {"state": state, **({"reason": reason} if reason else {})})

    def running(self, tid: str) -> bool:
        t = self.tasks.get(tid)
        return t is not None and not t.done()

    def busy(self, tid: str) -> bool:
        """A turn that will still read new messages: running, and not past its end (its turn-end hooks)."""
        t = self.tasks.get(tid)
        return t is not None and not t.done() and self._ending.get(tid) is not t

    def _unanswered(self, tid: str) -> bool:
        """A user message written after the turn's latest model call read the chat (sent while the reply streamed)."""
        mark = self._read_upto.get(tid)
        return mark is not None and bool(self.store.events(tid, after=mark, types=("user",)))

    # ---- entry points ------------------------------------------------------------------------

    def start(self, tid: str) -> None:
        if self.busy(tid):
            return
        self.tasks[tid] = asyncio.create_task(self._turn(tid))

    async def send(self, tid: str, text: str, attachments: list[str] | None = None,
                   doc_modes: dict[str, str] | None = None, quotes: list[dict[str, Any]] | None = None,
                   mentions: list[dict[str, Any]] | None = None, client_id: str | None = None, when: str = "auto",
                   start: bool = True, by: str | None = None) -> dict[str, Any]:
        """`quotes`: [{text (markdown), reply, seq?}], parts of earlier replies and the user's reply to each, in order
        (Select → Reply). `text` may be empty when a reply says something. `when` (chat-responsive 2.1): `auto` holds a
        message sent during a turn, or while a card waits, in the queue (answers `{queued: item}`); `now` writes it at
        once, for the running turn's next model call to read. `by`: who wrote it, when not the user typing
        (`schedule`: a scheduled task's instructions, plan scheduled-tasks 2.2)."""
        thread = self.store.thread(tid)
        if thread is None:
            raise KeyError(tid)
        if when != "now" and (held := self._hold(tid, thread, {"text": text, "attachments": attachments, "doc_modes": doc_modes,
                                                               "quotes": quotes, "mentions": mentions, "client_id": client_id})):
            return held
        if not self.busy(tid) and thread["state"] == "waiting":
            await self._dismiss_pending(tid, "The user wrote a message instead of answering.")
        docs = await describe_docs(self, tid, thread, attachments, doc_modes) if attachments else []
        # Numbered now, with no await before the event is written: a tool result that landed while the
        # documents were described has taken its #n already (two outputs never share one). Whether a turn
        # will read it is decided here too, so a turn that ended during the awaits above starts again.
        queued = self.busy(tid)
        n0 = len(ctx.outputs(self.store.events(tid, types=("tool_result", "user"))))
        for i, d in enumerate(docs):
            d["ref"] = f"#{n0 + i + 1}"
        servers = [f"mcp:{m['id']}" for m in mentions or [] if isinstance(m, dict) and m.get("kind") == "mcp" and m.get("id")]
        if servers:                                     # mcp-client 4.1: @mcp:<server> pins its tools in this chat
            st = dict(thread.get("settings") or {})
            st["pinned"] = sorted(set(st.get("pinned") or []) | set(servers))
            self.store.update_thread(tid, settings=st)
        ev = self.emit(tid, "user", {"text": text, **({"quotes": quotes} if quotes else {}),
                                     **({"mentions": mentions} if mentions else {}),     # plan 48.3
                                     **({"attachments": attachments} if attachments else {}),
                                     **({"docs": docs} if docs else {}), **({"queued": True} if queued else {}),
                                     **({"steer": True} if queued and when == "now" else {}),
                                     **({"client_id": client_id} if client_id else {}),
                                     **({"by": by} if by else {})})
        for d in docs:
            if d.get("fallback"):        # asked for whole, didn't fit (plan 24.9): say so in the chat
                self.emit(tid, "note", {"text": d["fallback"], "level": "warn"})
        if not thread["title"]:
            words = ctx.said({"text": text, "quotes": quotes})      # an empty text with replies: name it by the replies
            self.store.update_thread(tid, title=_title_from(words))
            self._titles[tid] = words       # asked for after the turn's first model call (chat-responsive 3.2)
        if self._recalling(thread):      # after the event (chat-responsive 1.1); the next model call waits for it
            task = asyncio.create_task(self._recall_into(tid, thread, text, ev["seq"]))
            self._recalls.setdefault(tid, set()).add(task)
            task.add_done_callback(lambda t: self._recalls.get(tid, set()).discard(t))
        if (thread.get("settings") or {}).get("project") and not (thread.get("settings") or {}).get("dry_run"):
            task = asyncio.create_task(self._fresh_into(tid, text, ev["seq"]))   # plan projects 3.5: waited for like recall
            self._recalls.setdefault(tid, set()).add(task)
            task.add_done_callback(lambda t: self._recalls.get(tid, set()).discard(t))
        if not queued and start:
            self.start(tid)
        return ev

    def _recalling(self, thread: dict[str, Any]) -> bool:
        from .memory import profile
        return not (thread.get("settings") or {}).get("dry_run") and bool(profile.settings(self.cfg.data)["recall"])

    async def _recall_into(self, tid: str, thread: dict[str, Any], text: str, seq: int) -> None:
        """A `recall` event for the user event `seq`: read with it as its `memory` (context.rebuild)."""
        got = await self._recall(tid, thread, text)
        if got:
            self.emit(tid, "recall", {"for": seq, "memory": got})

    async def _fresh_into(self, tid: str, text: str, seq: int) -> None:
        """The project's pages this message needs, fetched again when stale (a `project_refresh` event; plan projects 3.5)."""
        from .projects import fresh
        p = self.project_of(tid)
        if p is None:
            return
        try:
            await fresh.refresh_for(self, tid, p["id"], text, seq)
        except Exception:  # noqa: BLE001: a message never fails over a page
            log.exception("refreshing project pages for %s", tid)

    async def _await_recall(self, tid: str) -> None:
        pending = list(self._recalls.get(tid, ()))
        if pending:
            await asyncio.wait(pending, timeout=RECALL_WAIT_S)

    async def _recall(self, tid: str, thread: dict[str, Any], text: str) -> list[dict[str, Any]]:
        """structured-memory 3.3: the facts this message calls to mind (not an eval's, not when turned off)."""
        from .memory import profile
        if (thread.get("settings") or {}).get("dry_run") or not profile.settings(self.cfg.data)["recall"]:
            return []
        try:
            try:                                            # what the profile shows this chat isn't recalled again
                folders = (await ctx.chat_folders(self.hub, tid, thread.get("settings"), await self.hub.services(),
                                                  (thread.get("settings") or {}).get("disabled") or [], self.projects) or {}).get("folders")
            except Exception:  # noqa: BLE001
                folders = None
            days = int(profile.settings(self.cfg.data).get("interest_days") or profile.INTEREST_DAYS)
            pid = (self.project_of(tid) or {}).get("id")                # plan projects 4.2: its memory, not others'
            st = thread.get("settings") or {}
            sw = {"user": st.get("use_profile", True) is not False,      # a scheduled task's switches (scheduled-tasks 2.4)
                  "own_project": st.get("use_project_memory", True) is not False}
            got = await profile.recall(self.memory, self.hub, text, profile.build(self.memory, folders, days, project=pid, **sw)[1],
                                       project=pid, **sw)
        except Exception:  # noqa: BLE001: a message never fails over memory
            log.exception("recall for %s", tid)
            return []
        self.memory.touch([r["id"] for r in got])
        return got

    async def answer(self, tid: str, question_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        q = self._find(tid, "question", question_id)
        if q is None:
            raise KeyError(question_id)
        if self._find(tid, "tool_result", question_id) is not None:
            raise Busy("that question was already answered")
        self.emit(tid, "answer", {"id": question_id, "answers": answers})
        ev = self.emit(tid, "tool_result", {"id": question_id, "name": "ask_user", "status": "done",
                                             "content": json.dumps({"answers": answers}, ensure_ascii=False)})
        self.start(tid)
        return ev

    async def approval(self, tid: str, approval_id: str, approve: bool, arguments: dict[str, Any] | None = None,
                       reason: str | None = None, remember: str = "once", confirm: bool = False) -> dict[str, Any]:
        ap = next((e for e in self.store.events(tid, types=("approval",)) if e["payload"]["approval_id"] == approval_id), None)
        if ap is None:
            raise KeyError(approval_id)
        self._deciding.add(approval_id)      # the hub's approval event mustn't record it a second time
        try:
            res = await self.hub.decide(approval_id, approve, arguments, reason, remember, confirm)   # HubCallError (422, 409) goes to the caller
        except BaseException:
            self._deciding.discard(approval_id)
            raise
        ev = self._decided(tid, ap["payload"]["id"], approval_id, approve, arguments, reason, res, remember)
        self.start(tid)
        return ev

    def _decided(self, tid: str, call: str, aid: str, approve: bool, arguments: Any, reason: str | None,
                 res: dict[str, Any], remember: str = "once") -> dict[str, Any]:
        grant = (res.get("grant") or {}).get("id")
        ev = self.emit(tid, "decision", {"id": call, "approval_id": aid, "approve": approve, "arguments": arguments,
                                         "reason": reason, "call_id": res.get("call_id"), "status": res.get("status"),
                                         **({"remember": remember, "grant": grant} if grant else {})})
        if not approve:
            tc = self._find(tid, "tool_call", call)
            self._result(tid, call, tc["payload"]["name"] if tc else "?", res)
        return ev

    async def hub_event(self, ev: dict[str, Any]) -> None:
        """A decision made outside the chat (the hub's Approvals popover) continues the thread."""
        if ev.get("type") != "approval":
            return
        a = ev.get("approval") or {}
        origin = a.get("origin") or {}
        if origin.get("service") != "agent" or a.get("state") == "pending":
            return
        tid = origin.get("thread")
        if not tid or self.store.thread(tid) is None:
            return
        if a["id"] in self._deciding or any(e["payload"].get("approval_id") == a["id"]
                                            for e in self.store.events(tid, types=("decision",))):
            return
        ap = next((e for e in self.store.events(tid, types=("approval",)) if e["payload"]["approval_id"] == a["id"]), None)
        if ap is None or self._find(tid, "tool_result", ap["payload"]["id"]) is not None:
            return      # already settled here (Stop or a button dismissed the card): the hub's echo mustn't restart the turn
        approve = a["state"] == "approved"
        res = {"status": "running" if approve else "denied", "call_id": a.get("call_id"),
               "error": None if approve else {"code": "denied_by_user", "detail": a.get("reason") or "the user said no"}}
        self._decided(tid, ap["payload"]["id"], a["id"], approve, a.get("final"), a.get("reason"), res)
        self.start(tid)

    async def action(self, tid: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.running(tid):
            raise Busy("a turn is running; wait for it or stop it first")
        if self.store.thread(tid) is None:
            raise KeyError(tid)
        if self.store.thread(tid)["state"] == "waiting":
            await self._dismiss_pending(tid, "The user started an action instead.")
        ev = self.emit(tid, "tool_call", {"id": new_id("tc_"), "name": tool, "arguments": arguments, "step": new_id("s_"),
                                          "by": "user"})
        self.start(tid)
        return ev

    async def cancel(self, tid: str) -> None:
        t = self.tasks.get(tid)
        if t and not t.done():
            t.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=40)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        elif (self.store.thread(tid) or {}).get("state") == "waiting":
            await self._dismiss_pending(tid, "Cancelled by the user.")
            self.set_state(tid, "idle", "cancelled")
            self._queue_after(tid, "idle")      # Stop sends what was held (chat-responsive 2.1)

    async def resume_all(self) -> int:
        """At startup: threads a crash left `running` continue."""
        n = 0
        for t in self.store.threads(limit=1000):
            if t["state"] == "running":
                self.start(t["id"])
                n += 1
        return n

    # ---- the turn ----------------------------------------------------------------------------

    async def _cloud_notice(self, tid: str, model: str) -> None:
        """The first turn on a cloud model since the chat was on another says where the chat now goes (plan
        llm-servers 2.3): the provider sees its messages, attachments and tool results from here on."""
        last = next((e["payload"].get("model") for e in reversed(self.store.events(tid))
                     if e["type"] in ("usage", "cloud_notice")), None)
        if last == model:
            return
        try:
            data = await self.llm.models(max_age=60)
        except Exception:  # noqa: BLE001 — a notice never stops a turn
            return
        r = next(((m.get("relay") or {}) for m in data if m.get("id") == model), {})
        if r.get("group") != "cloud":
            return
        provider = {"anthropic": "Anthropic", "gemini": "Google (Gemini)"}.get(r.get("protocol") or "", r.get("endpoint") or "a cloud provider")
        if (r.get("protocol") or "") == "openai":
            provider = r.get("endpoint") or "OpenAI"
        self.emit(tid, "cloud_notice", {"model": model, "provider": provider})
        self.emit(tid, "note", {"text": f"This chat now goes to {provider} ({model}): its messages, attachments and tool "
                                        "results are sent there from this turn on.", "level": "info"})

    async def _turn(self, tid: str) -> None:
        self.set_state(tid, "running")
        thread = self.store.thread(tid) or {}
        model = thread.get("model") or self.cfg.model
        await self._cloud_notice(tid, model)
        tools = ToolSet(self.hub, thread.get("settings") or {}, await self.all_tools(model))
        steps = 0
        final, cancelled = "idle", False
        try:
            await tools.refresh()
            while True:
                pending = await self._resolve(tid, tools, thread)
                if pending == "waiting":
                    final = "waiting"
                    return
                if pending == "action":
                    return
                if steps >= self.cfg.max_steps:
                    self.emit(tid, "assistant", {"text": f"I stopped at the step limit ({self.cfg.max_steps} steps) before "
                                                          "finishing. Tell me to continue if you want me to go on.", "step": new_id("s_")})
                    self.emit(tid, "note", {"text": "step limit reached", "level": "warn"})
                    return
                stop = await self._compact_if_needed(tid, tools, model)
                if stop:
                    final = "error"
                    return
                stuck = self._stuck(tid)
                reply, model = await self._model(tid, tools, model, wrap_up=stuck)
                self._title_soon(tid)
                steps += 1
                if stuck or (not reply.tool_calls and not self._unanswered(tid)):
                    return
        except asyncio.CancelledError:
            if self.shutting_down:      # not the user's Stop: leave the turn to resume after the restart
                raise
            final = "idle"
            cancelled = True
            await asyncio.shield(self._cancelled(tid))
        except Exception as e:  # noqa: BLE001
            log.exception("turn of %s failed", tid)
            self.emit(tid, "error", {"code": "agent_error", "detail": f"{type(e).__name__}: {e}"[:500]})
            final = "error"
        finally:
            self._title_soon(tid)               # a turn that ended before its model call
            me = asyncio.current_task()
            if me is not None and self.tasks.get(tid) is me:
                self._ending[tid] = me      # from here a message starts a turn of its own (chat-responsive 1.1)
            if not self.shutting_down:
                self.set_state(tid, final)
                if self.queue.has(tid):           # held messages go now, Stop included; an error pauses them
                    self._queue_after(tid, final)
                elif final == "idle" and not cancelled and self._unanswered(tid):
                    self.start(tid)
            try:
                for cb in self.on_turn_end:
                    try:
                        await cb(tid)
                    except Exception:  # noqa: BLE001
                        log.exception("turn-end hook")
            finally:
                if self._ending.get(tid) is me:
                    del self._ending[tid]

    async def _cancelled(self, tid: str) -> None:
        for e in self._unresolved(tid):
            p = e["payload"]
            # the hub call's id: on the `call` event, or on the `decision` when it went through a card
            started = self._find(tid, "call", p["id"]) or self._find(tid, "decision", p["id"])
            call_id = (started or {}).get("payload", {}).get("call_id")
            if call_id:
                try:
                    await self.hub.cancel_call(call_id)
                except Exception:  # noqa: BLE001
                    pass
            self._result(tid, p["id"], p["name"], {"status": "cancelled", "error": {"code": "cancelled", "detail": "stopped by the user"}})
        self.emit(tid, "note", {"text": "stopped by the user", "level": "info"})

    async def _dismiss_pending(self, tid: str, why: str) -> None:
        for e in self._unresolved(tid):
            p = e["payload"]
            ap = self._find(tid, "approval", p["id"])
            if ap and not self._find(tid, "decision", p["id"]):
                self._deciding.add(ap["payload"]["approval_id"])
                try:
                    await self.hub.decide(ap["payload"]["approval_id"], False, None, why)
                except Exception:  # noqa: BLE001
                    pass
            self._result(tid, p["id"], p["name"], {"status": "skipped", "error": {"code": "skipped", "detail": why}})

    # ---- resolving tool calls ----------------------------------------------------------------

    def _find(self, tid: str, type_: str, call_id: str) -> dict[str, Any] | None:
        return next((e for e in reversed(self.store.events(tid, types=(type_,))) if e["payload"].get("id") == call_id), None)

    def _last_step(self, tid: str) -> list[dict[str, Any]]:
        calls = self.store.events(tid, types=("tool_call",))
        if not calls:
            return []
        step = calls[-1]["payload"].get("step")
        return [e for e in calls if e["payload"].get("step") == step]

    def _refs(self, tid: str, args: dict[str, Any], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """This chat's `#n` → `output:<id>` (the hub doesn't know the chat's numbers): in a hub tool's `ref`,
        and in any file input of `schema` (`x-kind`), alone or in a list (plan 27.6: workspace_python's inputs)."""
        def one(v: Any) -> Any:
            if isinstance(v, str) and re.fullmatch(r"\s*#\d+\s*", v) and (oid := self.local.resolve_ref(tid, v)):
                return f"output:{oid}"
            return v
        out = dict(args)
        if "ref" in out:
            out["ref"] = one(out["ref"])
        for k, p in ((schema or {}).get("properties") or {}).items():
            if k in out and isinstance(p, dict) and (p.get("x-kind") or (p.get("items") or {}).get("x-kind")):
                out[k] = [one(x) for x in out[k]] if isinstance(out[k], list) else one(out[k])
        return out

    def _unresolved(self, tid: str) -> list[dict[str, Any]]:
        done = {e["payload"]["id"] for e in self.store.events(tid, types=("tool_result",))}
        return [e for e in self._last_step(tid) if e["payload"]["id"] not in done]

    def _result(self, tid: str, call: str, name: str, res: dict[str, Any]) -> dict[str, Any]:
        """A hub-shaped result → a tool_result event (outputs numbered #n in the thread)."""
        n0 = len(ctx.outputs(self.store.events(tid, types=("tool_result", "user"))))
        outs = []
        for i, o in enumerate(res.get("outputs") or []):
            outs.append({"n": n0 + i + 1, **{k: o.get(k) for k in ("output_id", "kind", "title", "summary", "url", "preview", "prompt")}})
        body: dict[str, Any] = {"status": res.get("status")}
        if res.get("result") is not None:
            body["result"] = res["result"]
        if outs and isinstance(body.get("result"), dict) and isinstance(body["result"].get("cite"), str):
            body["result"] = {**body["result"], "cite": body["result"]["cite"].replace("#n:", f"#{outs[0]['n']}:")}
        if outs:
            body["outputs"] = [{"ref": f"#{o['n']}", "output": f"output:{o['output_id']}", "kind": o["kind"],
                                "summary": ctx.label(o["summary"])} for o in outs]
        if res.get("error"):
            body["error"] = res["error"]
        if isinstance(res.get("content"), str):
            content = res["content"]
        elif isinstance(res.get("result"), str) and not outs and not res.get("error"):
            content = res["result"]   # a text answer (hub_read_document): as it is, not as an escaped JSON string
        else:
            content = json.dumps(body, ensure_ascii=False, default=str)
        hk = self.hooks_of(tid)
        hint, cap = hk.after(name, res.get("status") or "done", (res.get("error") or {}).get("code"))
        if cap:                                            # a trim hook (plan 22.2), keeping <untrusted> blocks closed
            content = hk.trim(content, cap)
        if hint:
            content += "\nNote: " + hint
            self.emit(tid, "note", {"text": f"hook: added a hint to {name}'s error", "level": "info"})
        payload = {"id": call, "name": name, "status": res.get("status") or "done", "content": content}
        for k in ("call_id", "error", "image", "data", "judge", "grant_id"):
            if res.get(k) is not None:
                payload[k] = res[k]
        if outs:
            payload["outputs"] = outs
        return self.emit(tid, "tool_result", payload)

    async def _resolve(self, tid: str, tools: ToolSet, thread: dict[str, Any]) -> str:
        """Run or wait for the last step's unresolved calls: 'waiting', 'action' (a user action ran:
        no model call), or 'ok'."""
        pending = self._unresolved(tid)
        if not pending:
            return "ok"
        by_user = all(e["payload"].get("by") == "user" for e in self._last_step(tid))
        reads = all(tools.risk(e["payload"]["name"]) == "read" and e["payload"]["name"] != "ask_user" for e in pending)
        if reads and len(pending) > 1:
            outs = await asyncio.gather(*(self._run_call(tid, e, tools, thread) for e in pending))
        else:
            outs = []
            for e in pending:
                r = await self._run_call(tid, e, tools, thread)
                outs.append(r)
                if r == "waiting":
                    break
        if "waiting" in outs:
            return "waiting"
        return "action" if by_user else "ok"

    async def _run_call(self, tid: str, e: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        p = e["payload"]
        cid, name, args = p["id"], p["name"], p.get("arguments")
        if p.get("bad_arguments"):
            schema = (tools.full.get(name) or {}).get("parameters")
            if schema is None and tools.by_name(name):
                full = await self.hub.tools([name])
                schema = full[0]["parameters"] if full else None
            self._result(tid, cid, name, {"status": "error", "error": {
                "code": "invalid_arguments", "detail": p["bad_arguments"],
                "fix": "send the arguments as one JSON object matching the schema" + (f": {json.dumps(schema)[:1500]}" if schema else "")}})
            return "ok"
        stop = self.hooks_of(tid).before(name, args if isinstance(args, dict) else {}, self._turn_calls(tid, cid))
        if stop:                                    # a harness hook refused it (plan 22.2)
            self.emit(tid, "note", {"text": f"hook: {stop['detail']}", "level": "info"})
            self._result(tid, cid, name, {"status": "error", "error": stop})
            return "ok"
        if self._repeated(tid, e) >= 3:
            self._result(tid, cid, name, {"status": "error", "error": {
                "code": "repeated_call", "detail": f"{name} was already called with these same arguments {self._repeated(tid, e) - 1} "
                "times in this turn; its result won't change",
                "fix": "use the result you already have and move on to the next step (load_tools if the tool you need isn't loaded)"}})
            return "ok"
        hub_name = name
        if name == "remember":
            text = str((args or {}).get("text") or "").strip()
            if not text or (thread.get("settings") or {}).get("dry_run"):
                return await self.local.run(tid, cid, name, args or {}, tools, thread)   # refused there, or an eval's stand-in
            # A lasting fact goes into later chats: the hub decides it as agent_memory_save, a `write` in the ask list
            # (Plan refuses it; a chat that read untrusted text gets a card; structured-memory 3.2)
            about = (args or {}).get("about") or ([args["topic"]] if (args or {}).get("topic") else [])
            if isinstance(about, str):                     # "user", not ["user"]: one name, never its letters
                about = [about]
            hub_name, args = "agent_memory_save", {"text": text, **({"about": [str(a) for a in about][:6]} if about else {}),
                                                   **({"kind": args["kind"]} if (args or {}).get("kind") else {})}
        elif name in LOCAL_NAMES:
            return await self.local.run(tid, cid, name, args or {}, tools, thread)
        # a hub tool: decided approval, a call already started, or a new call
        dec = self._find(tid, "decision", cid)
        if self._find(tid, "approval", cid) and dec is None:
            return "waiting"
        started = self._find(tid, "call", cid)
        call_id = (dec or {}).get("payload", {}).get("call_id") or (started or {}).get("payload", {}).get("call_id")
        judged = ((started or {}).get("payload") or {}).get("judge")    # a resumed call keeps its Auto verdict
        if dec is not None and not dec["payload"]["approve"]:
            return "ok"   # the denial was recorded as the result already
        if call_id is None:
            if hub_name == name and name not in tools.full and tools.by_name(name):
                tools.load([name])
                await tools.refresh()
                self._save_loaded(tid, tools)
            thread = self.store.thread(tid) or thread     # the mode now: the user may have switched it during the turn
            mode = "accept_edits" if p.get("by") == "user" else mode_of(thread.get("mode"))
            meta = tools.by_name(hub_name)
            off = meta["mod"] if meta and meta["mod"] in tools.disabled else None
            if hub_name in SERVICE_TOOLS and str((args or {}).get("id")) in tools.disabled:
                off = str(args["id"])      # starting or stopping a turned-off mod is using it too
            if off:
                self._result(tid, cid, name, {"status": "denied", "error": {
                    "code": "disabled", "detail": f"the {off} tools are turned off in this chat",
                    "fix": "don't use them; tell the user, who can turn the group back on in the composer"}})
                return "ok"
            turn, said = self._turn_of(tid)
            origin = {"service": "agent", "thread": tid, "tool_call_id": cid, "turn": turn}
            if pins := self._pins(tid):
                origin["pins"] = pins       # plan 48.3: what the user's message @-mentioned fills this turn's calls
            named = ctx.named_files(said)
            if named:
                origin["named"] = named     # secret-looking files the user named: the workspace mod opens only these
            if (thread.get("settings") or {}).get("dry_run"):
                origin["dry_run"] = True    # the eval: generating tools stand in existing outputs
            if (thread.get("settings") or {}).get("unattended"):
                origin["unattended"] = True  # a scheduled run with no one watching: what would ask is refused (scheduled-tasks 2.2)
            from .projects.origin import chat_envs
            origin.update(chat_envs(thread.get("settings"), self.projects))   # the chat's workspace folders (plan 34; a project's: projects 2.2)
            if mode == "auto":
                origin["said"] = self._said(tid)   # the Auto judge reads the user's own words (plan 30.3)…
                origin["narration"] = ctx.narration(self.store.events(tid))   # …and with context "full", this turn's text
            if hub_name == "web_fetch":            # links the user typed open without a card; the page is read for the question
                origin["links"] = links.of_events(self.store.events(tid, types=("user",)))
                if said:
                    origin["question"] = said[:2000]
            if (thread.get("settings") or {}).get("no_learn"):
                origin["no_learn"] = True   # this chat opted out of learning (plan 21.4)
            if ctx.read_untrusted(self.store.events(tid)):
                origin["untrusted"] = True  # the chat holds text from a page, file or transcript: a preference asks first
            args = self._refs(tid, args or {}, (tools.full.get(hub_name) or {}).get("parameters"))
            res = await self.hub.call(hub_name, args, origin, mode, wait=2)
            if res.get("status") == "needs_approval":
                self.emit(tid, "approval", {"id": cid, "approval_id": res["approval_id"], "tool": hub_name,
                                            "arguments": res.get("arguments"), "ask_fields": res.get("ask_fields") or [],
                                            "schema": res.get("schema"), "risk": res.get("risk"),
                                            **({"grant_key": res["grant_key"]} if res.get("grant_key") else {}),
                                            **({"limits": res["limits"]} if res.get("limits") else {}),
                                            **({"why": res["why"]} if res.get("why") else {}),
                                            **({"judge": res["judge"]} if res.get("judge") else {}),
                                            "description": (res.get("description") or "")[:600],
                                            **({"filled": res["filled"]} if res.get("filled") else {}),
                                            **({"filled_by": res["filled_by"]} if res.get("filled_by") else {})})
                return "waiting"
            if res.get("status") != "running":
                self._hub_result(tid, cid, name, res, args)
                return "ok"
            call_id = res["call_id"]
            judged = res.get("judge")                     # the Auto judge's verdict (plan 30.5): on the step row
            granted = res.get("grant_id")                 # a pre-allow ran it (scheduled-tasks 3.3)
            self.emit(tid, "call", {"id": cid, "call_id": call_id, **({"judge": judged} if judged else {}),
                                    **({"grant_id": granted} if granted else {})})
        else:
            granted = ((started or {}).get("payload") or {}).get("grant_id")
        res = await self._wait_call(tid, cid, call_id)
        if judged and not res.get("judge"):
            res = {**res, "judge": judged}
        if granted and not res.get("grant_id"):
            res = {**res, "grant_id": granted}
        self._hub_result(tid, cid, name, res, args)
        return "ok"

    def _hub_result(self, tid: str, cid: str, name: str, res: dict[str, Any], args: dict[str, Any] | None) -> None:
        """A hub call's result; `remember` (run as agent_memory_save) says what it saved (local.py)."""
        self._result(tid, cid, name, self.local.remembered(tid, res, args or {}) if name == "remember" else res)

    async def _wait_call(self, tid: str, cid: str, call_id: str) -> dict[str, Any]:
        last = None
        first = True              # the state now (a job's first preview), then each change as it comes (plan 44.2)
        while True:
            try:
                st = await self.hub.call_status(call_id, wait=0 if first else POLL_S, changed=not first)
                first = False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the hub restarting: try again
                log.warning("call %s status: %s", call_id, e)
                await asyncio.sleep(3)
                continue
            if st.get("status") != "running":
                return st
            key = (st.get("progress"), st.get("note"), json.dumps(st.get("live"), sort_keys=True))   # live: plan 44.2
            if key != last:
                last = key
                self.transient(tid, "progress", {"id": cid, "progress": st.get("progress"), "note": st.get("note"),
                                                 "elapsed_s": st.get("elapsed_s"), "job_id": st.get("job_id"),
                                                 **({"live": st["live"]} if st.get("live") else {})})

    def _pins(self, tid: str) -> dict[str, dict[str, str]]:
        """The last user message's mentions as {tool: {field: value}} (plan 48.3)."""
        evs = self.store.events(tid, types=("user",))
        return ctx.pins((evs[-1] if evs else {}).get("payload"))

    def _turn_of(self, tid: str) -> tuple[int, str]:
        """This turn's number (the seq of its user message: checkpoints and undo are per turn) and what the user said."""
        evs = self.store.events(tid, types=("user",))
        last = evs[-1] if evs else None
        return (last["seq"] if last else 0), ctx.said((last or {}).get("payload"))   # its text and quote-replies' replies

    def _said(self, tid: str, n: int = 6) -> list[str]:
        """The user's last `n` typed messages (no attachments, files, pages, quoted parts or tool results; replies to quoted
        parts are the user's words and count), each cut at 2,000 characters."""
        evs = self.store.events(tid, types=("user",))[-n:]
        return [w[:2000] for w in (ctx.said(e.get("payload")) for e in evs) if w]

    def _turn_calls(self, tid: str, cid: str) -> list[str]:
        """Tool names called so far in this turn (since the last user message), not counting `cid`."""
        evs = self.store.events(tid)
        last = max((e["seq"] for e in evs if e["type"] == "user"), default=0)
        return [e["payload"]["name"] for e in evs if e["seq"] > last and e["type"] == "tool_call" and e["payload"].get("id") != cid]

    def _repeated(self, tid: str, e: dict[str, Any]) -> int:
        """How many calls of this tool with these arguments since the last user message (this one included)."""
        evs = self.store.events(tid)
        start = max((x["seq"] for x in evs if x["type"] == "user"), default=0)
        key = (e["payload"]["name"], json.dumps(e["payload"].get("arguments") or {}, sort_keys=True))
        return sum(1 for x in evs if x["type"] == "tool_call" and x["seq"] > start and x["seq"] <= e["seq"]
                   and (x["payload"]["name"], json.dumps(x["payload"].get("arguments") or {}, sort_keys=True)) == key)

    def _stuck(self, tid: str) -> bool:
        """The turn only repeats itself: the last result was a refused repeat, and not the first one since the user spoke."""
        evs = self.store.events(tid)
        start = max((x["seq"] for x in evs if x["type"] == "user"), default=0)
        codes = [((x["payload"].get("error") or {}).get("code")) for x in evs if x["type"] == "tool_result" and x["seq"] > start]
        return bool(codes) and codes[-1] == "repeated_call" and codes.count("repeated_call") >= 2

    def _save_loaded(self, tid: str, tools: ToolSet) -> None:
        t = self.store.thread(tid) or {}
        s = dict(t.get("settings") or {})
        s["loaded"] = tools.loaded
        if tools.on or s.get("mcp_on"):
            s["mcp_on"] = sorted(tools.on)              # mcp-client 4.1: MCP servers on in this chat
        self.store.update_thread(tid, settings=s)

    async def compact(self, tid: str) -> dict[str, Any]:
        if self.running(tid):
            raise Busy("a turn is running")
        thread = self.store.thread(tid) or {}
        tools = ToolSet(self.hub, thread.get("settings") or {})
        await tools.refresh()
        model = thread.get("model") or self.cfg.model
        await self._compact_if_needed(tid, tools, model, force=True)
        return await self.meter(tid, model)

    def _title_soon(self, tid: str) -> None:
        """Names a new chat after its first model call, so the title's call doesn't compete with it for a local GPU."""
        words = self._titles.pop(tid, None)
        if words is not None:
            asyncio.create_task(self._title(tid, words))

    async def _title(self, tid: str, text: str) -> None:
        token = THREAD.set(tid)          # part of the chat: its lease, and a cloud model may answer it
        try:
            model = (self.store.thread(tid) or {}).get("model") or self.cfg.model
            r = await asyncio.wait_for(self.llm.chat(model, prompts.title_messages(text)), timeout=120)
            title = prompts.reply_title(r.text, r.thinking)   # an answer instead of a title keeps the heuristic one
            if title:
                self.store.update_thread(tid, title=title)
                self.transient(tid, "thread", self.store.thread(tid) or {})
        except Exception:  # noqa: BLE001 - the heuristic title stays
            pass
        finally:
            THREAD.reset(token)


def _title_from(text: str) -> str:
    words = text.strip().split()
    t = " ".join(words[:7])
    return (t[:57] + "…") if len(t) > 58 else t or "New chat"
