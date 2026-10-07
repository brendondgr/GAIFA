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
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import context as ctx
from . import prompts
from .hubapi import HubAPI
from .llm import LLM, LLMError, Reply
from .store import Store, new_id
from .tools import LOCAL_NAMES, ToolSet

log = logging.getLogger("agent.loop")
POLL_S = 15
HUB_MODE = {"ask": "ask", "auto": "auto", "read_only": "read_only"}


@dataclass
class Config:
    model: str = "skynet"
    fallback: str | None = None
    max_steps: int = 25
    default_window: int = 32768
    data: Any = None   # Path of data/agent
    all_tools_models: tuple[str, ...] = ()


@dataclass
class Live:
    """Per-thread subscribers (SSE)."""

    subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = field(default_factory=dict)

    def publish(self, tid: str, ev: dict[str, Any]) -> None:
        for q in list(self.subs.get(tid, ())):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    def subscribe(self, tid: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(2000)
        self.subs.setdefault(tid, set()).add(q)
        return q

    def unsubscribe(self, tid: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subs.get(tid, set()).discard(q)


class Busy(Exception):
    pass


class Agent:
    def __init__(self, cfg: Config, store: Store, hub: HubAPI, llm: LLM) -> None:
        from .local import Local

        self.cfg, self.store, self.hub, self.llm = cfg, store, hub, llm
        self.live = Live()
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.local = Local(self)
        self.on_turn_end: list[Callable[[str], Awaitable[None]]] = []
        self._deciding: set[str] = set()

    # ---- events ------------------------------------------------------------------------------

    def emit(self, tid: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        ev = self.store.append(tid, type_, payload)
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

    # ---- entry points ------------------------------------------------------------------------

    def start(self, tid: str) -> None:
        if self.running(tid):
            return
        self.tasks[tid] = asyncio.create_task(self._turn(tid))

    async def send(self, tid: str, text: str, attachments: list[str] | None = None) -> dict[str, Any]:
        thread = self.store.thread(tid)
        if thread is None:
            raise KeyError(tid)
        queued = self.running(tid)
        if not queued and thread["state"] == "waiting":
            await self._dismiss_pending(tid, "The user wrote a message instead of answering.")
        ev = self.emit(tid, "user", {"text": text, **({"attachments": attachments} if attachments else {}),
                                     **({"queued": True} if queued else {})})
        if not thread["title"]:
            self.store.update_thread(tid, title=_title_from(text))
            asyncio.create_task(self._title(tid, text))
        if not queued:
            self.start(tid)
        return ev

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
                       reason: str | None = None) -> dict[str, Any]:
        ap = next((e for e in self.store.events(tid, types=("approval",)) if e["payload"]["approval_id"] == approval_id), None)
        if ap is None:
            raise KeyError(approval_id)
        self._deciding.add(approval_id)      # the hub's approval event mustn't record it a second time
        try:
            res = await self.hub.decide(approval_id, approve, arguments, reason)   # HubCallError (422, 409) goes to the caller
        except BaseException:
            self._deciding.discard(approval_id)
            raise
        ev = self._decided(tid, ap["payload"]["id"], approval_id, approve, arguments, reason, res)
        self.start(tid)
        return ev

    def _decided(self, tid: str, call: str, aid: str, approve: bool, arguments: Any, reason: str | None,
                 res: dict[str, Any]) -> dict[str, Any]:
        ev = self.emit(tid, "decision", {"id": call, "approval_id": aid, "approve": approve, "arguments": arguments,
                                         "reason": reason, "call_id": res.get("call_id"), "status": res.get("status")})
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
        if ap is None:
            return
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

    async def resume_all(self) -> int:
        """At startup: threads a crash left `running` continue."""
        n = 0
        for t in self.store.threads(limit=1000):
            if t["state"] == "running":
                self.start(t["id"])
                n += 1
        return n

    # ---- the turn ----------------------------------------------------------------------------

    async def _turn(self, tid: str) -> None:
        self.set_state(tid, "running")
        thread = self.store.thread(tid) or {}
        model = thread.get("model") or self.cfg.model
        tools = ToolSet(self.hub, thread.get("settings") or {}, await self.all_tools(model))
        steps = 0
        final = "idle"
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
                reply, model = await self._model(tid, tools, model)
                steps += 1
                if not reply.tool_calls:
                    return
        except asyncio.CancelledError:
            final = "idle"
            await asyncio.shield(self._cancelled(tid))
        except Exception as e:  # noqa: BLE001
            log.exception("turn of %s failed", tid)
            self.emit(tid, "error", {"code": "agent_error", "detail": f"{type(e).__name__}: {e}"[:500]})
            final = "error"
        finally:
            self.set_state(tid, final)
            for cb in self.on_turn_end:
                try:
                    await cb(tid)
                except Exception:  # noqa: BLE001
                    log.exception("turn-end hook")

    async def _cancelled(self, tid: str) -> None:
        for e in self._unresolved(tid):
            p = e["payload"]
            call = self._find(tid, "call", p["id"])
            if call and call["payload"].get("call_id"):
                try:
                    await self.hub.cancel_call(call["payload"]["call_id"])
                except Exception:  # noqa: BLE001
                    pass
            self._result(tid, p["id"], p["name"], {"status": "cancelled", "error": {"code": "cancelled", "detail": "stopped by the user"}})
        self.emit(tid, "note", {"text": "stopped by the user", "level": "info"})

    async def _dismiss_pending(self, tid: str, why: str) -> None:
        for e in self._unresolved(tid):
            p = e["payload"]
            ap = self._find(tid, "approval", p["id"])
            if ap and not self._find(tid, "decision", p["id"]):
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

    def _unresolved(self, tid: str) -> list[dict[str, Any]]:
        done = {e["payload"]["id"] for e in self.store.events(tid, types=("tool_result",))}
        return [e for e in self._last_step(tid) if e["payload"]["id"] not in done]

    def _result(self, tid: str, call: str, name: str, res: dict[str, Any]) -> dict[str, Any]:
        """A hub-shaped result → a tool_result event (outputs numbered #n in the thread)."""
        n0 = len(ctx.outputs(self.store.events(tid, types=("tool_result",))))
        outs = []
        for i, o in enumerate(res.get("outputs") or []):
            outs.append({"n": n0 + i + 1, **{k: o.get(k) for k in ("output_id", "kind", "title", "summary", "url", "preview", "prompt")}})
        body: dict[str, Any] = {"status": res.get("status")}
        if res.get("result") is not None:
            body["result"] = res["result"]
        if outs:
            body["outputs"] = [{"ref": f"#{o['n']}", "output": f"output:{o['output_id']}", "kind": o["kind"], "summary": o["summary"]}
                               for o in outs]
        if res.get("error"):
            body["error"] = res["error"]
        content = res["content"] if isinstance(res.get("content"), str) else json.dumps(body, ensure_ascii=False, default=str)
        payload = {"id": call, "name": name, "status": res.get("status") or "done", "content": content}
        for k in ("call_id", "error", "image", "data"):
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
        if self._repeated(tid, e) >= 3:
            self._result(tid, cid, name, {"status": "error", "error": {
                "code": "repeated_call", "detail": f"{name} was already called with these same arguments {self._repeated(tid, e) - 1} "
                "times in this turn; its result won't change",
                "fix": "use the result you already have and move on to the next step (load_tools if the tool you need isn't loaded)"}})
            return "ok"
        if name in LOCAL_NAMES:
            return await self.local.run(tid, cid, name, args or {}, tools, thread)
        # a hub tool: decided approval, a call already started, or a new call
        dec = self._find(tid, "decision", cid)
        if self._find(tid, "approval", cid) and dec is None:
            return "waiting"
        started = self._find(tid, "call", cid)
        call_id = (dec or {}).get("payload", {}).get("call_id") or (started or {}).get("payload", {}).get("call_id")
        if dec is not None and not dec["payload"]["approve"]:
            return "ok"   # the denial was recorded as the result already
        if call_id is None:
            if name not in tools.full and tools.by_name(name):
                tools.load([name])
                await tools.refresh()
                self._save_loaded(tid, tools)
            mode = "auto" if p.get("by") == "user" else HUB_MODE.get(thread.get("mode") or "ask", "ask")
            meta = tools.by_name(name)
            if meta and meta["mod"] in tools.disabled:
                self._result(tid, cid, name, {"status": "denied", "error": {
                    "code": "disabled", "detail": f"the {meta['mod']} tools are turned off in this chat",
                    "fix": "don't use them; tell the user, who can turn the group back on in the composer"}})
                return "ok"
            origin = {"service": "agent", "thread": tid, "tool_call_id": cid}
            if (thread.get("settings") or {}).get("dry_run"):
                origin["dry_run"] = True    # the eval: generating tools stand in existing outputs
            res = await self.hub.call(name, args or {}, origin, mode, wait=2)
            if res.get("status") == "needs_approval":
                self.emit(tid, "approval", {"id": cid, "approval_id": res["approval_id"], "tool": name,
                                            "arguments": res.get("arguments"), "ask_fields": res.get("ask_fields") or [],
                                            "schema": res.get("schema"), "risk": res.get("risk"),
                                            "description": (res.get("description") or "")[:600]})
                return "waiting"
            if res.get("status") != "running":
                self._result(tid, cid, name, res)
                return "ok"
            call_id = res["call_id"]
            self.emit(tid, "call", {"id": cid, "call_id": call_id})
        res = await self._wait_call(tid, cid, call_id)
        self._result(tid, cid, name, res)
        return "ok"

    async def _wait_call(self, tid: str, cid: str, call_id: str) -> dict[str, Any]:
        last = None
        while True:
            try:
                st = await self.hub.call_status(call_id, wait=POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the hub restarting: try again
                log.warning("call %s status: %s", call_id, e)
                await asyncio.sleep(3)
                continue
            if st.get("status") != "running":
                return st
            key = (st.get("progress"), st.get("note"))
            if key != last:
                last = key
                self.transient(tid, "progress", {"id": cid, "progress": st.get("progress"), "note": st.get("note"),
                                                 "elapsed_s": st.get("elapsed_s"), "job_id": st.get("job_id")})

    def _repeated(self, tid: str, e: dict[str, Any]) -> int:
        """How many calls of this tool with these arguments since the last user message (this one included)."""
        evs = self.store.events(tid)
        start = max((x["seq"] for x in evs if x["type"] == "user"), default=0)
        key = (e["payload"]["name"], json.dumps(e["payload"].get("arguments") or {}, sort_keys=True))
        return sum(1 for x in evs if x["type"] == "tool_call" and x["seq"] > start and x["seq"] <= e["seq"]
                   and (x["payload"]["name"], json.dumps(x["payload"].get("arguments") or {}, sort_keys=True)) == key)

    def _save_loaded(self, tid: str, tools: ToolSet) -> None:
        t = self.store.thread(tid) or {}
        s = dict(t.get("settings") or {})
        s["loaded"] = tools.loaded
        self.store.update_thread(tid, settings=s)

    # ---- the model ---------------------------------------------------------------------------

    async def system_prompt(self, tid: str, tools: ToolSet, model: str) -> tuple[str, dict[str, int]]:
        from .knowledge import Knowledge

        k = Knowledge(self.cfg.data, self.hub)
        events = self.store.events(tid)
        meta = await self.llm.meta(model)
        try:
            services, memory = await self.hub.services(), await self.hub.memory()
        except Exception:  # noqa: BLE001
            services, memory = None, None
        summary, _, _ = ctx.summary_state(events)
        parts = {"agent_md": k.agent_md(), "memory": k.memory_index(), "skills": await k.skill_list(),
                 "tools": prompts.tool_index(tools.deferred(), set(tools.full), tools.disabled),
                 "env": prompts.environment(services, memory, model, meta.get("context_length"), meta.get("vision")),
                 "outputs": prompts.outputs_table(ctx.outputs(events)), "summary": summary}
        sizes = {"instructions": ctx.est(prompts.BASE + parts["agent_md"] + parts["env"]),
                 "skills_memory": ctx.est(parts["skills"] + parts["memory"]),
                 "tool_index": ctx.est(parts["tools"]), "outputs": ctx.est(parts["outputs"] + parts["summary"])}
        return prompts.build(parts), sizes

    async def all_tools(self, model: str) -> bool:
        """Load every tool for this model? Yes when its server constrains tool calls with a grammar
        (llama.cpp: the relay's facts come from `/props`), or when AGENT_ALL_TOOLS lists it."""
        if model in self.cfg.all_tools_models:
            return True
        meta = await self.llm.meta(model)
        return meta.get("source") == "props"

    async def window(self, model: str, tid: str | None = None) -> int:
        """The model's window, or the thread's own cap (`settings.window`) when that is smaller."""
        meta = await self.llm.meta(model)
        w = int(meta.get("context_length") or self.cfg.default_window)
        cap = ((self.store.thread(tid) or {}).get("settings") or {}).get("window") if tid else None
        return min(w, int(cap)) if isinstance(cap, (int, float)) and cap > 0 else w

    async def messages(self, tid: str, tools: ToolSet, model: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
        system, sizes = await self.system_prompt(tid, tools, model)
        events = self.store.events(tid)
        images = self.local.images(events)
        msgs, _ = ctx.rebuild(events, images)
        results = sum(ctx.est(m["content"]) for m in msgs if m["role"] == "tool")
        sizes["tools"] = ctx.est(tools.functions())
        sizes["messages"] = ctx.est(msgs) - results
        sizes["tool_results"] = results
        return [{"role": "system", "content": system}, *msgs], sizes

    async def meter(self, tid: str, model: str | None = None) -> dict[str, Any]:
        thread = self.store.thread(tid) or {}
        model = model or thread.get("model") or self.cfg.model
        tools = ToolSet(self.hub, thread.get("settings") or {}, await self.all_tools(model))
        await tools.refresh()
        _, sizes = await self.messages(tid, tools, model)
        m = ctx.meter(self.store.events(tid), await self.window(model, tid), sizes)
        m["model"] = model
        return m

    async def _model(self, tid: str, tools: ToolSet, model: str) -> tuple[Reply, str]:
        step = new_id("s_")
        msgs, sizes = await self.messages(tid, tools, model)

        async def delta(kind: str, text: str) -> None:
            self.transient(tid, "delta", {"kind": kind, "text": text, "step": step})

        known = tools.visible() | {t["name"] for t in tools.index}
        try:
            reply = await self.llm.chat(model, msgs, tools.functions(), delta, known)
        except LLMError as e:
            fb = self.cfg.fallback
            if not e.retryable or not fb or fb == model:
                raise
            self.emit(tid, "note", {"text": f"{model} didn't answer ({e.detail[:160]}); continuing on {fb}", "level": "warn"})
            self.transient(tid, "delta_reset", {"step": step})
            model = fb
            msgs, sizes = await self.messages(tid, tools, model)
            reply = await self.llm.chat(model, msgs, tools.functions(), delta, known)
        if not reply.text.strip() and not reply.tool_calls:
            # An empty reply (the server dropped a call it couldn't parse, or the model stopped early):
            # ask once more rather than leave the user with nothing.
            # vLLM's streaming parsers can drop a tool call made right after the thinking: ask again without streaming.
            self.emit(tid, "note", {"text": "the model's reply was empty; asked again", "level": "info"})
            self.transient(tid, "delta_reset", {"step": step})
            retry = await self.llm.chat(model, msgs, tools.functions(), None, known, stream=False)
            retry.thinking = (reply.thinking + "\n" + retry.thinking).strip()
            reply = retry
        if reply.thinking:
            self.emit(tid, "thinking", {"text": reply.thinking, "seconds": reply.thinking_s, "step": step})
        if reply.text or not reply.tool_calls:
            self.emit(tid, "assistant", {"text": reply.text, "step": step, "model": model})
        for tc in reply.tool_calls:
            args, err = tc.parsed()
            payload: dict[str, Any] = {"id": tc.id or new_id("tc_"), "name": tc.name, "arguments": args if args is not None else {},
                                       "step": step, "by": "model"}
            if err:
                payload["bad_arguments"] = err
                payload["raw_arguments"] = tc.arguments[:2000]
            if reply.leaked:
                payload["leaked"] = True
            self.emit(tid, "tool_call", payload)
        window = await self.window(model, tid)
        self.emit(tid, "usage", {**reply.usage, "model": model, "window": window})
        events = self.store.events(tid)
        self.transient(tid, "context", ctx.meter(events, window, sizes) | {"model": model})
        return reply, model

    async def _compact_if_needed(self, tid: str, tools: ToolSet, model: str, force: bool = False) -> bool:
        """Returns True when the turn must stop (the thrash guard)."""
        window = await self.window(model, tid)
        msgs, sizes = await self.messages(tid, tools, model)
        used = ctx.est(msgs) + sizes["tools"]
        if not force and used < ctx.CLEAR_AT * window:
            return False
        events = self.store.events(tid)
        cands = ctx.clear_candidates(events)
        if cands:
            self.emit(tid, "compact", {"stage": "clear", "cleared": cands, "before": used})
            msgs, sizes = await self.messages(tid, tools, model)
            used = ctx.est(msgs) + sizes["tools"]
        if force or used >= ctx.SUMMARIZE_AT * window:
            cut = ctx.summary_cut(self.store.events(tid))
            if cut:
                await self._summarize(tid, model, cut, used)
                msgs, sizes = await self.messages(tid, tools, model)
                used = ctx.est(msgs) + sizes["tools"]
        if used >= ctx.SUMMARIZE_AT * window:
            self.emit(tid, "error", {"code": "context_full", "detail": f"the chat still uses {used:,} of {window:,} tokens after "
                                     "compaction (one item is too large)", "fix": "start a new chat, or fork from an earlier message"})
            return True
        return False

    async def _summarize(self, tid: str, model: str, cut: int, before: int) -> None:
        events = [e for e in self.store.events(tid) if e["seq"] <= cut]
        old_summary, _, _ = ctx.summary_state(events)
        msgs, _ = ctx.rebuild(events)
        prompt = [{"role": "system", "content": "You summarize chats." + (f"\nEarlier summary:\n{old_summary}" if old_summary else "")},
                  *msgs, {"role": "user", "content": prompts.SUMMARY_PROMPT}]
        reply = await self.llm.chat(model, prompt)
        outs = prompts.outputs_table(ctx.outputs(events))
        summary = reply.text.strip() + (f"\n\nOutputs so far:\n{outs}" if outs else "")
        self.emit(tid, "compact", {"stage": "summary", "summary": summary, "upto_seq": cut, "before": before})

    async def compact(self, tid: str) -> dict[str, Any]:
        if self.running(tid):
            raise Busy("a turn is running")
        thread = self.store.thread(tid) or {}
        tools = ToolSet(self.hub, thread.get("settings") or {})
        await tools.refresh()
        model = thread.get("model") or self.cfg.model
        await self._compact_if_needed(tid, tools, model, force=True)
        return await self.meter(tid, model)

    async def _title(self, tid: str, text: str) -> None:
        try:
            model = (self.store.thread(tid) or {}).get("model") or self.cfg.model
            r = await asyncio.wait_for(self.llm.chat(model, [{"role": "system", "content": prompts.TITLE_PROMPT},
                                                             {"role": "user", "content": text[:2000]}]), timeout=120)
            title = r.text.strip().strip('"').strip()[:60]
            if title and "\n" not in title:
                self.store.update_thread(tid, title=title)
                self.transient(tid, "thread", self.store.thread(tid) or {})
        except Exception:  # noqa: BLE001 - the heuristic title stays
            pass


def _title_from(text: str) -> str:
    words = text.strip().split()
    t = " ".join(words[:7])
    return (t[:57] + "…") if len(t) > 58 else t or "New chat"
