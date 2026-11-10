"""The `agent` tools and the Sub-agents prompt part (plan agent-workflows 1.3, 2.1).

`agent_wait`, `agent_send`, `agent_stop` and `agent_list` (2.1) come with it: `background: true` returns at once, and the
sub-agent's end arrives as an `agent_done` event (runner.report) unless an agent_wait returns it first.

A chat that may spawn (workflows on, not at `max_depth`) gets the local tool `agent {prompt, label, model?, write?}`:
it spawns a sub-agent and waits for it; transient `progress` events carry the sub-agent's state and current step for
the fold; the result is `{child, label, state, answer, refused?, error?, chat}`. The answer is wrapped as untrusted
text when the sub-agent read pages, files or other outside text. A turn resumed after a restart finds the sub-agent
its call already started (`spawn.tool_call_id`) and waits for it again. Several `agent` calls in one step run side
by side (they count as reads, so the loop gathers them), each in its slot.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .. import context as ctx
from .runner import WorkflowError, spawn_of
from .settings import depth_of

if TYPE_CHECKING:
    from ..tools import ToolSet

AGENT = {"name": "agent", "description": "Start a sub-agent for one independent part of the task and wait for its answer. "
         "It works in a chat of its own and sees none of this chat, so `prompt` must say everything it needs: the goal, "
         "where to look, what to report back. Its last reply comes back as this tool's result. Call several in one step "
         "to run them side by side.",
         "parameters": {"type": "object", "properties": {
             "prompt": {"type": "string", "description": "The whole task for the sub-agent, with what to report back"},
             "label": {"type": "string", "description": "2–4 words naming its part, e.g. \"Read the tests folder\""},
             "model": {"type": "string", "description": "Only to use another model the relay serves; leave it out for this chat's"},
             "write": {"type": "boolean", "default": False,
                       "description": "It may change files (one such sub-agent at a time); otherwise it only reads"},
             "background": {"type": "boolean", "default": False,
                            "description": "Return at once and go on; its answer arrives as a message when it's done"}},
             "required": ["prompt", "label"]}}
CHILD_ARG = {"type": "string", "description": "The sub-agent's id (child, from agent or agent_list)"}
TOOLS = [AGENT,
         {"name": "agent_wait", "description": "Wait for a background sub-agent to finish (the first one, or `child`) and get "
          "its answer.", "parameters": {"type": "object", "properties": {
              "child": CHILD_ARG, "timeout": {"type": "integer", "minimum": 5, "maximum": 1800, "default": 600}}}},
         {"name": "agent_send", "description": "Send a sub-agent this chat started a follow-up message (more to do, or a "
          "correction); its next answer comes back as from a background one.",
          "parameters": {"type": "object", "properties": {"child": CHILD_ARG, "text": {"type": "string"}},
                         "required": ["child", "text"]}},
         {"name": "agent_stop", "description": "Stop a sub-agent this chat started.",
          "parameters": {"type": "object", "properties": {"child": CHILD_ARG}, "required": ["child"]}},
         {"name": "agent_list", "description": "The sub-agents this chat started, with their state.",
          "parameters": {"type": "object", "properties": {}}},
         {"name": "agent_review", "description": "Review a sub-agent's request (to run a tool that asks first, or a question): "
          "deny it with a reason the sub-agent reads, or forward it to the user, who decides on a card. You can't approve.",
          "parameters": {"type": "object", "properties": {
              "request": {"type": "string", "description": "The request's id (rq_…); may be left out when only one is open"},
              "action": {"type": "string", "enum": ["deny", "forward"]},
              "reason": {"type": "string", "description": "Why: the sub-agent reads it when denied, the user when forwarded"}},
              "required": ["action"]}}]
NAMES = {t["name"] for t in TOOLS}

PARENT = ("`agent` hands one independent part of a task to a sub-agent, in a chat of its own that sees none of this one: "
          "`prompt` says the goal, where to look and what to report; its last reply is the result. Several in one step run "
          "side by side. Use them for parts that don't depend on each other (several folders, documents or pages; surveying "
          "options), never for one lookup, steps that build on each other, or what you can do in a step or two: each costs "
          "a whole chat. They only read unless write: true (one writer at a time). With background: true it returns at once; "
          "its answer arrives later as a message (or agent_wait for it). A sub-agent's request to run something that asks "
          "first comes to you: agent_review denies it with a reason or forwards it to the user; you can never approve. "
          "Check what matters in their answers.")
CHILD = ("You are a sub-agent: the chat “{parent}” started you to do one task, and its prompt is this chat's first message. "
         "Do that task, then reply with what you found or did, complete and to the point: that last reply goes back to the "
         "chat that started you (the user can read this chat too). {rights} Don't ask questions: decide what you can, and say "
         "in your reply what you assumed or couldn't do.")
READS = "You can only read: tools that change, generate or delete things are refused here."
WRITES = "You may change files in this chat's folders; nothing else in the workflow does at the same time."


async def offered(agent: Any, thread: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    wf = getattr(agent, "workflows", None)
    if wf is None:
        return False, {}
    lim = await wf.limits.get()
    if not lim["enabled"] or depth_of(thread) >= int(lim["max_depth"]):
        return False, lim
    window = await agent.window(thread.get("model") or agent.cfg.model, thread.get("id"))
    return window >= int(lim["min_window"]), lim             # a small window has no room for a workflow's answers


async def prompt_part(agent: Any, tid: str, tools: ToolSet) -> str:
    """The Sub-agents section: how to use `agent` (when it's offered; sets `tools.spawn`), and what a sub-agent is."""
    thread = agent.store.thread(tid) or {}
    ok, lim = await offered(agent, thread)
    tools.spawn = ok
    out = []
    sp = spawn_of(thread)
    if sp:
        parent = agent.store.thread(str(sp.get("parent"))) or {}
        out.append(CHILD.format(parent=ctx.label(parent.get("title") or "a chat"), rights=WRITES if sp.get("write") else READS))
    if ok:
        slot = await agent.workflows.slot(thread.get("model"))
        out.append(PARENT + f" Up to {lim['max_children']} per turn, "
                   + (f"{lim['parallel_local']} at a time on this machine." if slot == "local"
                      else f"{lim['parallel_remote']} at a time."))
    return "\n\n".join(out)


def _doing(agent: Any, t: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """What the sub-agent is doing now, in words, and its live row."""
    if t is None:
        return "gone", {}
    calls = agent.store.events(t["id"], types=("tool_call",))
    last = calls[-1]["payload"]["name"] if calls else None
    words = {"queued": "waiting for a free slot", "waiting": "waiting on a card", "error": "stopped with an error"}.get(
        t["state"], f"running {last}" if t["state"] == "running" and last else
        "thinking" if t["state"] == "running" else "done")
    return words, {"child": t["id"], "label": spawn_of(t).get("label") or t["title"], "state": t["state"], "tool": last,
                   "calls": len(calls)}


class WorkflowTools:
    """Mixed into the agent's Local tools (local.py)."""

    a: Any

    async def t_agent(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        wf = self.a.workflows
        if wf is None:
            return self.err(tid, cid, "agent", "unavailable", "sub-agents aren't running", "do the work yourself")  # type: ignore[attr-defined]
        child = next((c for c in self.a.store.children(tid) if spawn_of(c).get("tool_call_id") == cid), None)
        other = sorted(set(args) - {"prompt", "label", "model", "write", "background"})
        if child is None and not str(args.get("prompt") or "").strip() and other:     # `instruction`, `task`: say which name
            return self.err(tid, cid, "agent", "invalid_arguments", f"prompt is empty; there is no {', '.join(other)}",  # type: ignore[attr-defined]
                            'send the whole task as `prompt` (with `label`): {"prompt": "…", "label": "…"}')
        background = bool(args.get("background"))
        if child is None:
            try:
                child = await wf.spawn(tid, str(args.get("prompt") or ""), str(args.get("label") or ""),
                                       model=args.get("model") or None, write=bool(args.get("write")), tool_call_id=cid,
                                       background=background)
            except WorkflowError as e:
                return self.err(tid, cid, "agent", e.code, e.detail, e.fix)  # type: ignore[attr-defined]
        kid = child["id"]
        data = {"agent": {"child": kid, "label": spawn_of(child).get("label"), "background": background}}
        if background or spawn_of(child).get("background"):
            return self.ok(tid, cid, "agent", {"child": kid, "label": spawn_of(child).get("label"), "state": child["state"],  # type: ignore[attr-defined]
                                               "background": True, "chat": f"#/chat/{kid}",
                                               "note": "it runs on its own: its answer arrives as a message when it's done "
                                                       "(agent_wait waits for it)"}, data=data)
        from . import requests
        res = await wf.wait(kid, on_change=self._progress(tid, cid), until=lambda: requests.open_requests(self.a, tid, kid))
        if res is None:                                       # it waits on a card: the parent reviews it (2.2)
            wf.mark(kid, background=True, reported=False)     # …and its answer comes later, as a background one's
            asks = [requests.summary(r) for r in requests.open_requests(self.a, tid, kid)]
            data["agent"]["state"] = "needs_review"
            return self.ok(tid, cid, "agent", {"child": kid, "label": spawn_of(child).get("label"), "state": "needs_review",  # type: ignore[attr-defined]
                                               "requests": [{**a, "arguments": ctx.untrusted(f"sub-agent {a['label']} request",
                                                                                            str(a.get("arguments") or a.get("asks")))}
                                                            for a in asks],
                                               "chat": f"#/chat/{kid}",
                                               "note": "review each with agent_review: deny (with a reason it reads) or forward "
                                                       "(the user decides on a card); you can't approve. It goes on in the "
                                                       "background: its answer arrives as a message (or agent_wait)."}, data=data)
        wf.mark(kid, seen=True)                               # its answer is shown here
        wf.publish(kid)
        res = wf.delivered(kid)
        data["agent"]["state"] = res.get("state")
        return self.ok(tid, cid, "agent", res, data=data)  # type: ignore[attr-defined]

    def _progress(self, tid: str, cid: str) -> Any:
        def changed(t: dict[str, Any] | None) -> None:
            words, live = _doing(self.a, t)
            self.a.transient(tid, "progress", {"id": cid, "note": f"{live.get('label', 'sub-agent')}: {words}",
                                               "live": {"agent": live}})
        return changed

    def _own(self, tid: str, cid: str, name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """The sub-agent `child` names, if this chat started it; else an error result."""
        kid = str(args.get("child") or "").strip()
        c = next((c for c in self.a.store.children(tid) if c["id"] == kid), None)
        if c is None:
            return None, self.err(tid, cid, name, "unknown_child", f"{kid or 'child'} isn't a sub-agent this chat started",  # type: ignore[attr-defined]
                                  "agent_list shows them")
        return c, None

    async def t_agent_wait(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        from . import requests
        wf = self.a.workflows
        want = None
        if args.get("child"):
            want, bad = self._own(tid, cid, "agent_wait", args)
            if bad:
                return bad
        def pending() -> list[dict[str, Any]]:
            return [c for c in self.a.store.children(tid) if spawn_of(c).get("background") and not spawn_of(c).get("reported")
                    and (want is None or c["id"] == want["id"])]
        if want is not None and not pending() and spawn_of(want).get("reported") and wf.finished(want["id"]):
            return self.ok(tid, cid, "agent_wait", {**wf.delivered(want["id"]),  # type: ignore[attr-defined]
                                                    "note": "it had reported already, as a message in this chat"})
        if not pending():
            return self.err(tid, cid, "agent_wait", "nothing_to_wait_for",  # type: ignore[attr-defined]
                            "no background sub-agent of this chat is still to report" if want is None
                            else f"{want['id']} has reported already, or wasn't started in the background",
                            "its answer is in this chat already; agent_list shows them all")
        timeout = min(max(int(args.get("timeout") or 600), 5), 1800)
        wf.waiters[tid] = wf.waiters.get(tid, 0) + 1
        try:
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                done = next((c for c in pending() if wf.finished(c["id"])), None)
                if done is not None:
                    wf.mark(done["id"], reported=True, seen=True)
                    wf.publish(done["id"])
                    res = wf.delivered(done["id"])
                    left = [spawn_of(c).get("label") for c in pending()]
                    return self.ok(tid, cid, "agent_wait", {**res, **({"still_running": left} if left else {})},  # type: ignore[attr-defined]
                                   data={"agent": {"child": done["id"], "label": res.get("label"), "state": res.get("state")}})
                asks = [r for r in requests.open_requests(self.a, tid) if r["child"] in {c["id"] for c in pending()}]
                if asks:                                         # one waits on a card: the parent reviews it now (2.2)
                    return self.ok(tid, cid, "agent_wait", {"needs_review": [requests.summary(r) for r in asks],  # type: ignore[attr-defined]
                        "still_running": [spawn_of(c).get("label") for c in pending()],
                        "note": "review each with agent_review (deny with a reason, or forward to the user), then agent_wait again"})
                left_s = deadline - asyncio.get_running_loop().time()
                if left_s <= 0:
                    return self.ok(tid, cid, "agent_wait", {"timed_out": True, "still_running": [  # type: ignore[attr-defined]
                        {"child": c["id"], "label": spawn_of(c).get("label"), "state": c["state"]} for c in pending()]})
                changed = wf.changed
                try:
                    await asyncio.wait_for(changed.wait(), timeout=min(2.0, left_s))
                except asyncio.TimeoutError:
                    pass
        finally:
            wf.waiters[tid] -= 1
            if not wf.waiters[tid]:
                del wf.waiters[tid]
                wf.flush(tid)

    async def t_agent_send(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        c, bad = self._own(tid, cid, "agent_send", args)
        if bad:
            return bad
        text = str(args.get("text") or "").strip()
        if not text:
            return self.err(tid, cid, "agent_send", "invalid_arguments", "text is empty")  # type: ignore[attr-defined]
        wf = self.a.workflows
        wf.mark(c["id"], background=True, reported=False)    # its next answer comes back as a background one's
        if wf.finished(c["id"]):
            await self.a.send(c["id"], text, by="parent", start=False)
            self.a.store.update_thread(c["id"], state="queued")
            await wf.drain()
        else:
            await self.a.send(c["id"], text, by="parent")
        wf.publish(c["id"])
        return self.ok(tid, cid, "agent_send", {"child": c["id"], "sent": True,  # type: ignore[attr-defined]
                                                "note": "its answer arrives as a message when it's done (agent_wait waits for it)"})

    async def t_agent_stop(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        c, bad = self._own(tid, cid, "agent_stop", args)
        if bad:
            return bad
        self.a.workflows.mark(c["id"], reported=True)        # stopped on purpose: no message about it
        await self.a.workflows.stop(c["id"], "stopped by the chat that started it")
        return self.ok(tid, cid, "agent_stop", {"child": c["id"], "state": (self.a.store.thread(c["id"]) or {}).get("state")})  # type: ignore[attr-defined]

    async def t_agent_review(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        from . import requests
        try:
            out = await requests.review(self.a, tid, str(args.get("request") or ""), str(args.get("action") or ""),
                                        str(args.get("reason") or ""))
        except ValueError as e:
            return self.err(tid, cid, "agent_review", "invalid_request", str(e), "agent_list and the requests you were given")  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001: the hub's 409 when the user decided it meanwhile
            return self.err(tid, cid, "agent_review", "already_decided", f"{type(e).__name__}: {e}",  # type: ignore[attr-defined]
                            "the user decided it; go on")
        return self.ok(tid, cid, "agent_review", out)  # type: ignore[attr-defined]

    async def t_agent_list(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        rows = [{"child": c["id"], "label": spawn_of(c).get("label"), "state": c["state"],
                 "background": bool(spawn_of(c).get("background")), "reported": bool(spawn_of(c).get("reported")),
                 "write": bool(spawn_of(c).get("write"))} for c in self.a.store.children(tid)]
        return self.ok(tid, cid, "agent_list", {"sub_agents": rows} if rows else {"sub_agents": [], "note": "none yet"})  # type: ignore[attr-defined]
