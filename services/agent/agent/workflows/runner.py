"""Running sub-agents (plan agent-workflows 1.2).

`Workflows.spawn(parent, prompt, label, …)` makes a sub-agent: a chat with the parent's settings (`settings.py`), its
first message the parent's prompt (`by: "parent"`), state `queued`. `drain()` starts queued sub-agents, oldest first,
while slots are free: `parallel_local` at once on this machine's models (the relay's `local` group; they only queue on
one GPU), `parallel_remote` on the others. One that waited longer than `queue_wait_s` is dropped.

A sub-agent's turn ending (`on_turn_end`) frees its slot; unless it waits on a card it is finished, unseen
(`spawn.seen: false`), and `result(child)` is what goes back to the parent: its last reply, capped, its state and the
calls it was refused. Stopping a chat stops its sub-agents (`on_cancel`). Per parent turn: at most `max_children`
sub-agents and `workflow_tokens` tokens among them; past the budget the turn's running sub-agents are stopped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .settings import Limits, child_settings, depth_of

log = logging.getLogger("agent.workflows")
ANSWER_CHARS = 8000            # ~2k tokens of a sub-agent's answer go back to its parent
FINISHED = ("idle", "error", "cancelled")
REFUSED = ("read_only", "unattended", "denied", "denied_by_user", "disabled")
TICK_S = 5.0


class WorkflowError(Exception):
    def __init__(self, code: str, detail: str, fix: str | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.fix = code, detail, fix

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, **({"fix": self.fix} if self.fix else {})}


def spawn_of(thread: dict[str, Any] | None) -> dict[str, Any]:
    return ((thread or {}).get("settings") or {}).get("spawn") or {}


class Workflows:
    def __init__(self, agent: Any, limits: dict[str, Any] | None = None, clock: Any = time.time) -> None:
        self.agent, self.clock = agent, clock
        self.store = agent.store
        self.limits = Limits(agent.hub, limits)
        self.active: dict[str, str] = {}          # started sub-agents whose turn runs → their slot (local | remote)
        self.waiters: dict[str, int] = {}         # parent → its agent_wait calls under way: they report what ends (2.1)
        self.changed = asyncio.Event()            # a sub-agent started, ended or was stopped
        self._draining = asyncio.Lock()
        agent.on_turn_end.append(self.turn_ended)
        agent.on_cancel.append(self.parent_stopped)

    # ---- spawning -------------------------------------------------------------------------------

    async def spawn(self, parent_id: str, prompt: str, label: str, model: str | None = None, write: bool = False,
                    by: str = "agent", tool_call_id: str | None = None, turn: int | None = None,
                    background: bool = False) -> dict[str, Any]:
        """A new sub-agent of `parent_id`, queued (WorkflowError when a limit refuses it)."""
        lim = await self.limits.get()
        if not lim["enabled"]:
            raise WorkflowError("workflows_off", "sub-agents are turned off (Settings → Agent → Sub-agents)",
                                "do the work yourself in this chat")
        parent = self.store.thread(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        prompt, label = (prompt or "").strip(), " ".join((label or "").split())[:60] or "Sub-agent"
        if not prompt:
            raise WorkflowError("invalid_arguments", "prompt is empty",
                                'send the whole task as `prompt` (with `label`): {"prompt": "…", "label": "…"}')
        depth = depth_of(parent) + 1
        if depth > int(lim["max_depth"]):
            raise WorkflowError("workflow_limit", "a sub-agent can't start sub-agents of its own",
                                "do this part yourself and say so in your answer")
        root = self.store.root_of(parent_id)
        turn = self.agent._turn_of(parent_id)[0] if turn is None else turn
        mine = [c for c in self.store.children(parent_id) if spawn_of(c).get("turn") == turn]
        if len(mine) >= int(lim["max_children"]):
            raise WorkflowError("workflow_limit", f"this turn already started {len(mine)} sub-agents, the most it may",
                                "use the answers you have, or do the rest yourself")
        if write and any(spawn_of(c).get("write") and c["state"] not in FINISHED for c in self.store.descendants(root)):
            raise WorkflowError("workflow_limit", "another sub-agent in this workflow may change files, and only one may "
                                "at a time", "wait for it (agent_wait), or spawn this one read-only")
        if self.tokens(parent_id, turn) >= int(lim["workflow_tokens"]):
            raise WorkflowError("workflow_budget", "this turn's sub-agents used their token budget",
                                "finish with what you have")
        spawn = {"root": root, "parent": parent_id, "label": label, "by": by, "tool_call_id": tool_call_id,
                 "write": bool(write), "depth": depth, "turn": turn, "seen": True,
                 **({"background": True, "reported": False} if background else {})}
        settings = child_settings(parent, spawn, int(lim["child_max_steps"]))
        unknown = model if model and not await self.served(model) else None     # "inherit", "same", a typo: the parent's
        th = self.store.create_thread(label, (None if unknown else model) or parent.get("model"), parent.get("mode") or "manual",
                                      settings, parent_id=parent_id)
        tid = th["id"]
        self.store.update_thread(tid, state="queued")
        if unknown:
            self.agent.emit(tid, "note", {"text": f"The relay doesn't serve {unknown!r}: this sub-agent uses its parent's model.",
                                          "level": "warn"})
        who = "the chat" if by == "agent" else ("another agent" if by == "mcp" else by)
        self.agent.emit(tid, "note", {"text": f"A sub-agent of “{parent.get('title') or 'a chat'}”, started by {who}"
                                              f"{'; it may change files' if write else '; it only reads'}. Its last reply "
                                              "goes back to the chat that started it.", "level": "info"})
        await self.agent.send(tid, prompt, by="parent", start=False)
        self.publish(tid)
        await self.drain()
        return self.store.thread(tid) or th

    # ---- the queue ------------------------------------------------------------------------------

    async def served(self, model: str) -> bool:
        """The relay serves it (or can't be asked: then the model is taken as given)."""
        try:
            ids = {m.get("id") for m in await self.agent.llm.models(max_age=60)}
        except Exception:  # noqa: BLE001
            return True
        return not ids or model in ids

    async def slot(self, model: str | None) -> str:
        """`local` for a model on this machine's relay group (or one the relay doesn't list), else `remote`."""
        try:
            for m in await self.agent.llm.models(max_age=60):
                if m.get("id") == (model or self.agent.cfg.model):
                    return "local" if ((m.get("relay") or {}).get("group") or "local") == "local" else "remote"
        except Exception:  # noqa: BLE001
            pass
        return "local"

    async def drain(self) -> None:
        """Start queued sub-agents while their slot has room; drop the ones that waited too long."""
        async with self._draining:
            lim = await self.limits.get()
            for c in self.store.spawned(("queued",)):
                tid = c["id"]
                if tid in self.active or self.agent.running(tid):
                    continue
                if self.clock() - c["created"] > float(lim["queue_wait_s"]):
                    self.agent.emit(tid, "error", {"code": "queue_timeout", "detail": "it waited too long for a free slot"})
                    self.agent.set_state(tid, "error")
                    self._ended(tid)
                    continue
                kind = await self.slot(c.get("model"))
                cap = int(lim["parallel_local" if kind == "local" else "parallel_remote"])
                if sum(1 for k in self.active.values() if k == kind) >= cap:
                    continue
                self.active[tid] = kind
                self.agent.start(tid)
                self.publish(tid)

    async def turn_ended(self, tid: str) -> None:
        t = self.store.thread(tid)
        sp = spawn_of(t)
        if t is not None and t["state"] == "idle" and self._unread_done(tid):
            self.agent.start(tid)                   # a sub-agent's end arrived as this chat's turn ended: read it now
        if not sp:
            return
        self.active.pop(tid, None)
        if t["state"] in FINISHED:
            self._ended(tid)
        else:
            self.publish(tid)
        await self.drain()

    def _ended(self, tid: str) -> None:
        t = self.store.thread(tid) or {}
        st = dict(t.get("settings") or {})
        sp = st["spawn"] = {**(st.get("spawn") or {}), "seen": False, "ended": self.clock()}
        self.store.update_thread(tid, settings=st)
        self.publish(tid)
        if sp.get("background") and not sp.get("reported") and not self.waiters.get(str(sp.get("parent"))):
            self.report(tid)

    def mark(self, tid: str, **fields: Any) -> None:
        t = self.store.thread(tid)
        if t is not None:
            st = dict(t["settings"])
            st["spawn"] = {**st.get("spawn", {}), **fields}
            self.store.update_thread(tid, settings=st)

    def delivered(self, tid: str) -> dict[str, Any]:
        """The result as the parent reads it: the answer inside <untrusted> when the sub-agent read outside text."""
        from .. import context as ctx
        res = self.result(tid)
        if res.get("answer") and ctx.read_untrusted(self.store.events(tid)):
            res["answer"] = ctx.untrusted(f"sub-agent {res.get('label')}", res["answer"])
        res["chat"] = f"#/chat/{tid}"
        return res

    def report(self, tid: str) -> None:
        """A background sub-agent ended: an `agent_done` event in its parent (read as a message from GAIFA, not the
        user); an idle parent starts a turn, a running one reads it at its next model call, a waiting one after."""
        sp = spawn_of(self.store.thread(tid))
        parent = str(sp.get("parent"))
        if self.store.thread(parent) is None:
            return
        self.mark(tid, reported=True)
        self.agent.emit(parent, "agent_done", self.delivered(tid))
        p = self.store.thread(parent) or {}
        if not self.agent.busy(parent) and p.get("state") != "waiting":
            self.agent.start(parent)

    def flush(self, parent: str) -> None:
        """Report the background sub-agents that ended while an agent_wait was under way and didn't return them."""
        if self.waiters.get(parent):
            return
        for c in self.store.children(parent):
            sp = spawn_of(c)
            if sp.get("background") and not sp.get("reported") and self.finished(c["id"]):
                self.report(c["id"])

    def _unread_done(self, tid: str) -> bool:
        done = self.store.events(tid, types=("agent_done",))
        if not done:
            return False
        mark = self.agent._read_upto.get(tid)
        if mark is None:
            usage = self.store.events(tid, types=("usage",))
            mark = usage[-1]["seq"] if usage else 0
        return done[-1]["seq"] > mark

    def finished(self, tid: str) -> bool:
        t = self.store.thread(tid)
        return t is None or (t["state"] in FINISHED and not self.agent.running(tid) and tid not in self.active)

    def publish(self, tid: str) -> None:
        """The sub-agent's row, to its parent's and its root's streams (`agent_child`, transient), and woken waiters."""
        t = self.store.thread(tid)
        sp = spawn_of(t)
        if t is not None and sp:
            node = next((n for n in (self.store.tree(tid) or {}).get("children", []) if n["id"] == tid), None)
            for to in dict.fromkeys((sp.get("parent"), sp.get("root"))):
                if to:
                    self.agent.transient(to, "agent_child", {"child": node})
        self.changed.set()
        self.changed = asyncio.Event()

    # ---- results --------------------------------------------------------------------------------

    def result(self, tid: str) -> dict[str, Any]:
        t = self.store.thread(tid)
        if t is None:
            return {"child": tid, "state": "deleted", "answer": ""}
        evs = self.store.events(tid, types=("assistant", "tool_result", "error"))
        answer = next((e["payload"].get("text") or "" for e in reversed(evs) if e["type"] == "assistant"), "")
        if len(answer) > ANSWER_CHARS:
            answer = answer[:ANSWER_CHARS] + f"\n…(cut: open the chat #/chat/{tid} for the rest)"
        refused = [e["payload"].get("name") for e in evs if e["type"] == "tool_result"
                   and ((e["payload"].get("error") or {}).get("code") in REFUSED)]
        out: dict[str, Any] = {"child": tid, "label": spawn_of(t).get("label") or t["title"], "state": t["state"],
                               "answer": answer}
        if refused:
            out["refused"] = refused
        errs = [e["payload"] for e in evs if e["type"] == "error"]
        if t["state"] == "error" and errs:
            out["error"] = {k: errs[-1].get(k) for k in ("code", "detail") if errs[-1].get(k)}
        return out

    async def wait(self, tid: str, timeout: float | None = None, on_change: Any = None) -> dict[str, Any] | None:
        """The sub-agent's result once it's finished; None at `timeout`. `on_change(thread)` on each change seen."""
        deadline = None if timeout is None else time.monotonic() + timeout
        last = None
        while True:
            t = self.store.thread(tid)
            key = (t or {}).get("state"), (t or {}).get("updated")
            if on_change is not None and key != last:
                last = key
                on_change(t)
            if self.finished(tid):
                return self.result(tid)
            left = 2.0 if deadline is None else min(2.0, deadline - time.monotonic())
            if left <= 0:
                return None
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=left)
            except asyncio.TimeoutError:
                pass

    # ---- stopping and budgets -------------------------------------------------------------------

    async def stop(self, tid: str, why: str) -> None:
        t = self.store.thread(tid)
        if t is None or self.finished(tid):
            return
        if t["state"] == "queued":
            self.agent.emit(tid, "note", {"text": why, "level": "info"})
            self.agent.set_state(tid, "cancelled")
            self._ended(tid)
            return
        self.agent.emit(tid, "note", {"text": why, "level": "info"})
        await self.agent.cancel(tid)       # its own sub-agents go too (on_cancel)
        if (self.store.thread(tid) or {}).get("state") == "waiting":
            self.agent.set_state(tid, "idle", "cancelled")
        self.active.pop(tid, None)
        self._ended(tid)

    async def parent_stopped(self, tid: str) -> None:
        """Queued ones first, so a running one's freed slot doesn't start them."""
        kids = sorted(self.store.children(tid), key=lambda c: c["state"] != "queued")
        for c in kids:
            if not self.finished(c["id"]):
                self.mark(c["id"], reported=True)    # stopped with its parent: nothing to report, no turn to start
            await self.stop(c["id"], "stopped with the chat that started it")

    def tokens(self, parent_id: str, turn: int) -> int:
        n = 0
        for c in self.store.children(parent_id):
            if spawn_of(c).get("turn") != turn:
                continue
            for e in self.store.events(c["id"], types=("usage",)):
                n += int(e["payload"].get("prompt_tokens") or 0) + int(e["payload"].get("completion_tokens") or 0)
        return n

    async def budgets(self) -> None:
        lim = await self.limits.get()
        seen: set[tuple[str, int]] = set()
        for c in self.store.spawned(("running", "queued", "waiting")):
            sp = spawn_of(c)
            key = (str(sp.get("parent")), int(sp.get("turn") or 0))
            if key in seen:
                continue
            seen.add(key)
            if self.tokens(*key) >= int(lim["workflow_tokens"]):
                for d in self.store.children(key[0]):
                    if spawn_of(d).get("turn") == key[1] and d["state"] == "queued":
                        await self.stop(d["id"], "stopped: this workflow's sub-agents used their token budget")
                for d in self.store.children(key[0]):
                    if spawn_of(d).get("turn") == key[1]:
                        await self.stop(d["id"], "stopped: this workflow's sub-agents used their token budget")

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Every TICK_S: budgets, then the queue (also sub-agents queued before a restart)."""
        while not stop.is_set():
            try:
                await self.budgets()
                await self.drain()
            except Exception:  # noqa: BLE001
                log.exception("workflows tick")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_S)
            except asyncio.TimeoutError:
                pass
