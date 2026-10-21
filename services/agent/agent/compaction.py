"""Compaction (plan 14.7), mixed into the loop's `Agent`: clear old tool results first, then summarize the
older part of the chat with the chat's own model once the context passes its marks (context.py: CLEAR_AT,
SUMMARIZE_AT). The events it emits are in the log, so a rebuilt chat comes back compacted."""

from __future__ import annotations

from . import context as ctx
from . import prompts
from .tools import ToolSet


class Compaction:
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
        outs = prompts.outputs_table(ctx.model_outputs(events))
        summary = reply.text.strip() + (f"\n\nOutputs so far:\n{outs}" if outs else "")
        self.emit(tid, "compact", {"stage": "summary", "summary": summary, "upto_seq": cut, "before": before})
