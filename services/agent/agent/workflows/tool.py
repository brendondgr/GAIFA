"""The `agent` tool and the Sub-agents prompt part (plan agent-workflows 1.3).

A chat that may spawn (workflows on, not at `max_depth`) gets the local tool `agent {prompt, label, model?, write?}`:
it spawns a sub-agent and waits for it; transient `progress` events carry the sub-agent's state and current step for
the fold; the result is `{child, label, state, answer, refused?, error?, chat}`. The answer is wrapped as untrusted
text when the sub-agent read pages, files or other outside text. A turn resumed after a restart finds the sub-agent
its call already started (`spawn.tool_call_id`) and waits for it again. Several `agent` calls in one step run side
by side (they count as reads, so the loop gathers them), each in its slot.
"""

from __future__ import annotations

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
                       "description": "It may change files (one such sub-agent at a time); otherwise it only reads"}},
             "required": ["prompt", "label"]}}
TOOLS = [AGENT]
NAMES = {t["name"] for t in TOOLS}

PARENT = ("`agent` hands one independent part of a task to a sub-agent, in a chat of its own that sees none of this one: "
          "`prompt` says the goal, where to look and what to report; its last reply is the result. Several in one step run "
          "side by side. Use them for parts that don't depend on each other (several folders, documents or pages; surveying "
          "options), never for one lookup, steps that build on each other, or what you can do in a step or two: each costs "
          "a whole chat. They only read unless write: true (one writer at a time). Check what matters in their answers.")
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
        if child is None:
            try:
                child = await wf.spawn(tid, str(args.get("prompt") or ""), str(args.get("label") or ""),
                                       model=args.get("model") or None, write=bool(args.get("write")), tool_call_id=cid)
            except WorkflowError as e:
                return self.err(tid, cid, "agent", e.code, e.detail, e.fix)  # type: ignore[attr-defined]
        kid = child["id"]

        def changed(t: dict[str, Any] | None) -> None:
            words, live = _doing(self.a, t)
            self.a.transient(tid, "progress", {"id": cid, "note": f"{live.get('label', 'sub-agent')}: {words}",
                                               "live": {"agent": live}})

        res = await wf.wait(kid, on_change=changed)
        t = self.a.store.thread(kid)
        if t is not None:                                     # its answer is shown here: seen
            st = dict(t["settings"])
            st["spawn"] = {**st.get("spawn", {}), "seen": True}
            self.a.store.update_thread(kid, settings=st)
            wf.publish(kid)
        res = dict(res or wf.result(kid))
        if res.get("answer") and ctx.read_untrusted(self.a.store.events(kid)):
            res["answer"] = ctx.untrusted(f"sub-agent {res.get('label')}", res["answer"])
        res["chat"] = f"#/chat/{kid}"
        return self.ok(tid, cid, "agent", res, data={"agent": {"child": kid, "label": res.get("label"),  # type: ignore[attr-defined]
                                                                "state": res.get("state")}})
