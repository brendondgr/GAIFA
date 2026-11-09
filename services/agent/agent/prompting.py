"""The agent's model side (split from loop.py): the harness a chat runs, its system prompt and its parts' sizes, the
model's window, the messages of a model call, the context meter, and one model call with its fallback, retries and
the thrash guard's wrap-up. Mixed into the loop's `Agent`."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from . import context as ctx
from . import gpuwait, prompts
from .llm import GPU_WAIT, THREAD, GpuWait, LLMError, Reply
from .store import mode_of, new_id
from .tools import ToolSet

PROMPT_REUSE_S = 10      # chat-responsive 3.2: the meter reuses a turn's prompt this long
# Sent (not stored) when a turn only repeats itself; that model call gets tool_choice "none".
WRAP_UP = ("(A note from the app, not from the user: you have repeated the same tool call and its result won't change. "
           "Tools are off for this reply. Answer the user in plain text: what you did, what blocked you, and what they can do.)")


def thread_settings(store: Any, tid: str) -> dict[str, Any]:
    t = store.thread(tid)
    return (t or {}).get("settings") or {}


class Prompting:
    def project_of(self, tid: str) -> dict[str, Any] | None:
        """The chat's project, or None (plan projects 2.2)."""
        from .projects.origin import project_of
        return project_of(thread_settings(self.store, tid), self.projects)

    def harness_of(self, tid: str) -> tuple[int, dict[str, str]]:
        """The harness version this chat runs (its `settings.harness` pin, else the active one) and its files."""
        from .harness import Harness, HarnessError

        h = Harness(self.cfg.data)
        pin = (thread_settings(self.store, tid) or {}).get("harness")
        try:
            n = int(pin) if pin is not None else h.current()
            return n, h.tree(n)
        except (HarnessError, ValueError):
            return 0, h.tree(0)

    def hooks_of(self, tid: str) -> Any:
        import tomllib

        from .hooks import Hooks
        _, tree = self.harness_of(tid)
        try:
            return Hooks(tomllib.loads(tree.get("hooks.toml") or ""))
        except tomllib.TOMLDecodeError:
            return Hooks(None)

    async def system_prompt(self, tid: str, tools: ToolSet, model: str) -> tuple[str, dict[str, int]]:
        from .knowledge import Knowledge

        hv, tree = self.harness_of(tid)
        tools.notes = {rel[6:-3]: text for rel, text in tree.items() if rel.startswith("tools/")}
        k = Knowledge(self.cfg.data, self.hub, tree, self.memory)
        events = self.store.events(tid)
        meta = await self.llm.meta(model)
        try:
            services, memory = await self.hub.services(), await self.hub.memory()
        except Exception:  # noqa: BLE001
            services, memory = None, None
        summary, _, _ = ctx.summary_state(events)
        prefs = await k.preferences(set(tools.full), tid) if not (thread_settings(self.store, tid) or {}).get("no_learn") else ""
        fdata = await ctx.chat_folders(self.hub, tid, thread_settings(self.store, tid), services, tools.disabled, self.projects)
        parts = {"base": tree.get("systemprompt.md", ""), "guardrails": tree.get("guardrails.md", ""),
                 "agent_md": k.agent_md(), "memory": "\n".join(x for x in (k.profile((fdata or {}).get("folders"), (self.project_of(tid) or {}).get("id")), prefs) if x),
                 "skills": await k.skill_list(set(tools.disabled), await ctx.chat_skills(
                     self.hub, tid, thread_settings(self.store, tid), services, tools.disabled, self.projects)),
                 "tools": prompts.tool_index(tools.deferred(), set(tools.full), tools.disabled),
                 "env": prompts.environment(services, memory, model, meta.get("context_length"), meta.get("vision"))
                 + (f"\nTurned off in this chat: {', '.join(sorted(tools.disabled))} (their tools can't be used here; "
                    "the user can turn them back on in the composer)" if tools.disabled else "")
                 + prompts.mode_note(mode_of((self.store.thread(tid) or {}).get("mode")))
                 + (prompts.folders_note(fdata, os.path.expanduser("~"), self.project_of(tid)) if fdata is not None else ""),
                 "outputs": prompts.outputs_table(ctx.model_outputs(events)), "summary": summary}
        sizes = {"instructions": ctx.est(parts["base"] + parts["guardrails"] + parts["agent_md"] + parts["env"]),
                 "skills_memory": ctx.est(parts["skills"] + parts["memory"]),
                 "tool_index": ctx.est(parts["tools"]), "outputs": ctx.est(parts["outputs"] + parts["summary"])}
        if (p := self.project_of(tid)) is not None:         # plan projects 3.3: the project, its files and pages
            from .projects import knowledge
            parts["project"] = knowledge.project_text(p)
            parts["project_knowledge"] = (await knowledge.project_knowledge(self, p["id"], await self.window(model, tid)))["text"]
            block, over = await knowledge.project_skills(self, tid, p, k)              # 4.1: its skills, always on
            if over:
                parts["skills"] = f"This project uses (read them with read_skill first): {', '.join(over)}\n" + parts["skills"]
            parts["skills"] = "\n\n".join(x for x in (block, parts["skills"]) if x)
            sizes["project"] = ctx.est(parts["project"] + parts["project_knowledge"] + block)
            sizes["skills_memory"] = ctx.est(parts["skills"] + parts["memory"]) - ctx.est(block)
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

    async def messages(self, tid: str, tools: ToolSet, model: str,
                       turn: bool = False) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """`turn`: for the turn's model call, which marks what it read (`_unanswered`) and keeps its prompt's sizes for
        the meter (chat-responsive 3.2)."""
        system, sizes = await self.system_prompt(tid, tools, model)
        sizes["tools"] = ctx.est(tools.functions())
        if turn:
            self._prompts[tid] = (model, time.monotonic(), dict(sizes))
        msgs, sizes = self._history(tid, sizes, mark=turn)
        return [{"role": "system", "content": system}, *msgs], sizes

    def _history(self, tid: str, sizes: dict[str, int], mark: bool = False) -> tuple[list[dict[str, Any]], dict[str, int]]:
        events = self.store.events(tid)
        if mark and events:
            self._read_upto[tid] = events[-1]["seq"]
        images = self.local.images(events)
        msgs, _ = ctx.rebuild(events, images)
        results = sum(ctx.est(m["content"]) for m in msgs if m["role"] == "tool")
        sizes["documents"] = ctx.doc_tokens(msgs)
        sizes["messages"] = ctx.est(msgs) - results - sizes["documents"]
        sizes["tool_results"] = results
        return msgs, sizes

    async def meter(self, tid: str, model: str | None = None) -> dict[str, Any]:
        thread = self.store.thread(tid) or {}
        model = model or thread.get("model") or self.cfg.model
        hit = self._prompts.get(tid)
        if hit and hit[0] == model and time.monotonic() - hit[1] < PROMPT_REUSE_S:   # the turn just built it: no hub calls
            _, sizes = self._history(tid, dict(hit[2]))
        else:
            tools = ToolSet(self.hub, thread.get("settings") or {}, await self.all_tools(model))
            await tools.refresh()
            _, sizes = await self.messages(tid, tools, model)
        m = ctx.meter(self.store.events(tid), await self.window(model, tid), sizes)
        m["model"] = model
        return m

    async def _model(self, tid: str, tools: ToolSet, model: str, wrap_up: bool = False) -> tuple[Reply, str]:
        """One model call (`_call_model`), with the chat named on its GPU lease and its wait shown (plan 31.4)."""
        token, waiting = THREAD.set(tid), GpuWait()
        wait_token = GPU_WAIT.set(waiting)          # the model client's stall limit skips the GPU wait
        client = getattr(self.hub, "client", None)
        watcher = asyncio.create_task(gpuwait.watch(client, tid, lambda p: self.transient(tid, "gpu_wait", p),
                                                    waiting=waiting)) if client else None
        try:
            return await self._call_model(tid, tools, model, wrap_up)
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            GPU_WAIT.reset(wait_token)
            THREAD.reset(token)

    async def _call_model(self, tid: str, tools: ToolSet, model: str, wrap_up: bool = False) -> tuple[Reply, str]:
        step = new_id("s_")
        await self._await_recall(tid)
        msgs, sizes = await self.messages(tid, tools, model, turn=True)
        choice = "auto"
        if wrap_up:     # the thrash guard: no more tools this turn, say what happened
            choice = "none"
            msgs.append({"role": "user", "content": WRAP_UP})
            self.emit(tid, "note", {"text": "the model kept repeating a call; asked it to answer without tools", "level": "warn"})

        t0, first = time.monotonic(), []                         # the call's time and time to first token (plan 21.4)

        async def delta(kind: str, text: str) -> None:
            if not first:
                first.append(time.monotonic() - t0)
            self.transient(tid, "delta", {"kind": kind, "text": text, "step": step})

        known = tools.visible() | {t["name"] for t in tools.index}
        try:
            reply = await self.llm.chat(model, msgs, tools.functions(), delta, known, tool_choice=choice)
        except LLMError as e:
            fb = self.cfg.fallback
            if not e.retryable or not fb or fb == model:
                raise
            self.emit(tid, "note", {"text": f"{model} didn't answer ({e.detail[:160]}); continuing on {fb}", "level": "warn"})
            self.transient(tid, "delta_reset", {"step": step})
            model = fb
            msgs, sizes = await self.messages(tid, tools, model, turn=True)
            if wrap_up:
                msgs.append({"role": "user", "content": WRAP_UP})
            reply = await self.llm.chat(model, msgs, tools.functions(), delta, known, tool_choice=choice)
        if reply.runaway:
            self.emit(tid, "note", {"text": "the model started repeating itself; stopped it and asked again", "level": "warn"})
            self.transient(tid, "delta_reset", {"step": step})
            reply = await self.llm.chat(model, msgs, tools.functions(), delta, known, tool_choice=choice)
            if reply.runaway:
                reply.tool_calls, reply.thinking = [], reply.thinking[:2000]
                reply.text = ("I got stuck repeating myself and stopped. Please ask again, perhaps one step at a time.")
        if not reply.text.strip() and not reply.tool_calls:
            # An empty reply (the server dropped a call it couldn't parse, or the model stopped early):
            # ask once more rather than leave the user with nothing.
            # vLLM's streaming parsers can drop a tool call made right after the thinking: ask again without streaming.
            self.emit(tid, "note", {"text": "the model's reply was empty; asked again", "level": "info"})
            self.transient(tid, "delta_reset", {"step": step})
            retry = await self.llm.chat(model, msgs, tools.functions(), None, known, stream=False, tool_choice=choice)
            retry.thinking = (reply.thinking + "\n" + retry.thinking).strip()
            reply = retry
        if wrap_up:
            reply.tool_calls = []
            if not reply.text.strip():
                reply.text = "I couldn't finish this: I kept repeating the same step without getting anywhere."
        if reply.thinking:
            self.emit(tid, "thinking", {"text": reply.thinking, "seconds": reply.thinking_s, "step": step})
        if reply.details:       # plan llm-servers 2.1: the provider's hidden state, sent back with this step
            self.emit(tid, "reasoning_details", {"details": reply.details, "model": model, "step": step})
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
        timing = {"seconds": round(time.monotonic() - t0, 2), **({"ttft_s": round(first[0], 2)} if first else {})}
        self.emit(tid, "usage", {**reply.usage, "model": model, "window": window, **timing, "harness": self.harness_of(tid)[0]},
                  tokens=int(reply.usage.get("total_tokens") or 0))
        events = self.store.events(tid)
        self.transient(tid, "context", ctx.meter(events, window, sizes) | {"model": model})
        return reply, model

