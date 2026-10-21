"""The improvement loop (plan 22.5): the agent improves its own harness from your chats, after Harness².

One run, per domain with new real chats since its last run:
1. evidence: the domain's recent chats as trajectories (your edits, denials, answers, thumbs, errors);
2. reflect: one model call, the failures and divergences per chat;
3. propose: two calls scoped like Harness²'s editors, INV (how the agent works: tool notes, hooks,
   guardrails) and PREF (what you want: skills, short rules), each a candidate harness version;
4. probe: replay chats under the current harness and each candidate (dry runs, agent/learn/replay.py);
5. compose: one call that merges what the replays support, adopts one candidate, or keeps the harness;
6. gate: the eval tasks for the domain's tools plus a core set, no worse than the current version
   (the full suite when always-on text changed);
7. adopt: tool notes, skills and hooks go live at once; a prompt or guardrail change becomes a
   proposal you approve (Learning → Harness); a failed gate keeps the current version;
8. library: one lesson (or none) for the next round in this domain.

Every model call goes to the same model as the chat (`skynet` through the relay). A run records its
stages, calls, tokens and time in data/agent/learn/runs/<id>.json, and pauses while you chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from . import prompts as P
from . import replay as R
from .library import Library

log = logging.getLogger("agent.learn")
DOMAINS: dict[str, tuple[str, ...]] = {"comfy": ("comfy_",), "gen3d": ("gen3d_",), "tts": ("tts_",),
                                       "llms": ("lcpp_", "vllm_", "relay_"), "hub": ("hub_",)}
CORE = ["img_full", "model3d", "speech_named", "whats_running", "read_only", "injection"]
ALWAYS_ON = ("systemprompt.md", "guardrails.md")


class Paused(Exception):
    pass


def _json(text: str) -> dict[str, Any] | None:
    """The first JSON object in a reply (models wrap it in prose or fences)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    for end in range(len(m.group(0)), 1, -1):
        try:
            v = json.loads(m.group(0)[:end])
            return v if isinstance(v, dict) else None
        except ValueError:
            continue
    return None


def doc_card(d: dict[str, Any]) -> str:
    """An attached document as the learner sees it (plan 24.8): its card, never its text."""
    size = f"{d['pages']} pages" if d.get("pages") else f"{d.get('lines') or 0} lines"
    return f"(document {d.get('ref')}: {d.get('name')}, {size})"


def render(events: list[dict[str, Any]], cap: int = 3500, reply_cap: int = 300) -> str:
    """A chat as a short trajectory for the prompts. Documents appear as their cards and tool results
    as their status (plan 24.8): no text from a file, a web page or a transcript reaches the learner."""
    out: list[str] = []
    cards: dict[str, dict[str, Any]] = {}
    for e in events:
        t, p = e["type"], e.get("payload") or {}
        if t == "user":
            out.append(f"USER: {str(p.get('text', ''))[:400]}" + "".join(" " + doc_card(d) for d in p.get("docs") or []))
        elif t == "assistant" and p.get("text"):
            txt = p["text"].strip()
            out.append(f"AGENT: {txt[:reply_cap]}" + (" […]" if len(txt) > reply_cap else ""))
        elif t == "tool_call":
            out.append(f"CALL {p.get('name')} {json.dumps(p.get('arguments') or {}, default=str)[:300]}")
        elif t == "approval":
            cards[p.get("id")] = p
        elif t == "decision":
            a = cards.get(p.get("id")) or {}
            if not p.get("approve"):
                out.append(f"USER DENIED {a.get('tool')}" + (f": {p.get('reason')}" if p.get("reason") else ""))
            elif p.get("arguments"):
                was = a.get("arguments") or {}
                ch = {k: (was.get(k), v) for k, v in p["arguments"].items() if json.dumps(was.get(k), default=str) != json.dumps(v, default=str)}
                if ch:
                    out.append(f"USER CHANGED THE CARD of {a.get('tool')}: " + "; ".join(f"{k}: {a_!r} → {b!r}" for k, (a_, b) in ch.items()))
        elif t == "tool_result":
            err = p.get("error") or {}
            out.append(f"  → {p.get('status')}" + (f" {err.get('code')}: {str(err.get('detail', ''))[:200]}" if err else ""))
        elif t == "answer":
            out.append("USER ANSWERED: " + "; ".join(f"{q[:80]} → {a}" for q, a in (p.get("answers") or {}).items()))
        elif t == "feedback":
            out.append(f"USER THUMBS {str(p.get('value', '')).upper()}" + (f" ({p.get('note')})" if p.get("note") else ""))
        elif t == "error":
            out.append(f"AGENT ERROR {p.get('code')}: {str(p.get('detail', ''))[:200]}")
    text = "\n".join(out)
    return text if len(text) <= cap else text[: cap // 2] + "\n…\n" + text[-cap // 2:]


class Learner:
    def __init__(self, agent: Any, base: str, transport: Any = None, model: str | None = None, max_chats: int = 8,
                 probe_chats: int = 3, gate_runs: int = 3, gate: Callable[..., Any] | None = None,
                 probe: Callable[..., Any] | None = None) -> None:
        from ..harness import Harness

        self.agent, self.base, self.transport = agent, base, transport
        self.model = model or agent.cfg.model
        self.max_chats, self.probe_chats, self.gate_runs = max_chats, probe_chats, gate_runs
        self.harness = Harness(agent.cfg.data)
        self.dir = Path(agent.cfg.data) / "learn"
        self._gate, self._probe = gate, probe
        self.running: dict[str, Any] | None = None

    # ---- state ---------------------------------------------------------------------------------

    def _state(self) -> dict[str, Any]:
        try:
            return json.loads((self.dir / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, st: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "state.json").write_text(json.dumps(st, indent=1))

    def runs(self, limit: int = 30) -> list[dict[str, Any]]:
        d = self.dir / "runs"
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit] if d.is_dir() else []
        out = [json.loads(f.read_text()) for f in files]
        for r in out:                       # a record left "running" by an older agent that stopped mid-run
            if r.get("state") == "running" and r["id"] != (self.running or {}).get("id"):
                r["state"] = r["stage"] = "interrupted"
        return out

    def _write(self, rec: dict[str, Any]) -> None:
        (self.dir / "runs").mkdir(parents=True, exist_ok=True)
        (self.dir / "runs" / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1, default=str))

    # ---- evidence ------------------------------------------------------------------------------

    def chats(self, domain: str, since: float) -> list[str]:
        st = self.agent.store
        pre = DOMAINS[domain]
        rows = st.events_by_type(["tool_call"], since)
        seen: list[str] = []
        skip: dict[str, bool] = {}
        for e in reversed(rows):                                  # newest first
            tid = e["thread_id"]
            if tid in seen or not str(e["payload"].get("name", "")).startswith(pre):
                continue
            if tid not in skip:                                   # eval dry runs and chats that opted out never teach it
                s = (st.thread(tid) or {}).get("settings") or {}
                skip[tid] = bool(s.get("dry_run") or s.get("no_learn"))
            if not skip[tid]:
                seen.append(tid)
        return seen[: self.max_chats]

    def user_active(self, since: float) -> bool:
        """A real chat got a message, or a real turn is running: the learner waits."""
        if self.agent.store.events_by_type(["user"], since):
            return True
        for tid in list(self.agent.tasks):
            t = self.agent.store.thread(tid) or {}
            if self.agent.running(tid) and not (t.get("settings") or {}).get("dry_run"):
                return True
        return False

    # ---- one model call --------------------------------------------------------------------------

    async def ask(self, rec: dict[str, Any], stage: str, prompt: str) -> str:
        if self.user_active(rec["started"]):
            raise Paused(stage)
        t0 = time.monotonic()
        reply = await self.agent.llm.chat(self.model, [{"role": "user", "content": prompt}], stream=False)
        rec["ledger"].append({"stage": stage, "seconds": round(time.monotonic() - t0, 1),
                              "prompt_tokens": reply.usage.get("prompt_tokens", 0), "completion_tokens": reply.usage.get("completion_tokens", 0)})
        return reply.text or ""

    # ---- the run ---------------------------------------------------------------------------------

    async def run(self, domains: list[str] | None = None, why: str = "manual") -> dict[str, Any]:
        rec: dict[str, Any] = {"id": time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2), "why": why, "started": time.time(),
                               "state": "running", "stage": "starting", "domains": [], "ledger": []}
        self.running = rec
        st = self._state()
        try:
            for domain in domains or list(DOMAINS):
                since = float(st.get(domain) or 0)
                chats = self.chats(domain, since)
                if not chats:
                    continue
                d = await self.domain(rec, domain, chats)
                rec["domains"].append(d)
                st[domain] = rec["started"]
                self._save_state(st)
            rec["state"] = "done"
        except Paused as p:
            rec["state"], rec["paused_at"] = "paused", str(p)
        except asyncio.CancelledError:
            rec["state"] = "cancelled"
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("learner run")
            rec["state"], rec["error"] = "error", f"{type(e).__name__}: {e}"[:400]
        finally:
            if rec["state"] == "running":       # stopped by something else (the agent shutting down mid-run)
                rec["state"] = "interrupted"
            rec["ended"] = time.time()
            rec["stage"] = rec["state"]
            self._write(rec)
            self.running = None
        return rec

    async def domain(self, rec: dict[str, Any], domain: str, chats: list[str]) -> dict[str, Any]:
        store, h = self.agent.store, self.harness
        out: dict[str, Any] = {"domain": domain, "chats": chats, "candidates": [], "decision": "keep", "notes": ""}
        evidence = "\n\n".join(f"## Chat {i + 1} ({t})\n{render(store.events(t))}" for i, t in enumerate(chats))
        cur = h.current()
        tree = h.tree(cur)
        harness_text = "\n\n".join(f"### {rel}\n{text.strip() or '(empty)'}" for rel, text in sorted(tree.items()))[:12000]
        lib = Library(self.agent.cfg.data, domain)
        tools = await self._tool_names()
        schemas = await self._schemas(domain, tools)
        if schemas:
            tools = {**{t: {} for t in tools}, **schemas}          # tool notes are checked against today's schemas
        harness_text = (harness_text + "\n\n# THE DOMAIN'S TOOLS AS THEY ARE NOW (chats may be older than these: a failure that "
                        "today's schema already prevents needs no edit, and a note must never contradict them)\n"
                        + "\n".join(f"### {n}\n{json.dumps(s)[:1500]}" for n, s in schemas.items()))[:20000]

        rec["stage"] = f"{domain}: reflect"
        reflection = await self.ask(rec, f"{domain}:reflect", P.REFLECT.format(domain=domain, evidence=evidence, evidence_rule=P.EVIDENCE_IS_DATA))
        out["reflection"] = reflection[:4000]

        for label, (dim, text) in (("INV", P.INV), ("PREF", P.PREF)):
            rec["stage"] = f"{domain}: propose {label}"
            prompt = P.PROPOSE.format(domain=domain, dimension=dim, dimension_text=text, components=P.COMPONENTS, evidence_rule=P.EVIDENCE_IS_DATA,
                                      harness=harness_text, library=lib.text(), reflection=reflection[:4000], evidence=evidence)
            n = await self._candidate(rec, f"{domain}:propose-{label}", prompt, cur, tools)
            if n:
                out["candidates"].append({"label": label, "version": n, "notes": h.meta(n).get("notes", "")})

        if not out["candidates"]:
            out["notes"] = "both editors kept the harness as it is"
            return self._learn(rec, out, lib, domain, None)

        rec["stage"] = f"{domain}: probe"
        records = self._records(chats)
        scores = {v: await self.probe(records, v) for v in [cur, *[c["version"] for c in out["candidates"]]]}
        out["probe"] = {str(k): v for k, v in scores.items()}

        rec["stage"] = f"{domain}: compose"
        cand_text = "\n\n".join(f"## {c['label']} (version {c['version']})\nnotes: {c['notes']}\nreplays: {json.dumps(scores[c['version']])}\n"
                                f"diff:\n{h.diff(cur, c['version'])[:5000]}" for c in out["candidates"])
        cand_text = f"## the current harness (version {cur})\nreplays: {json.dumps(scores[cur])}\n\n" + cand_text
        final = await self._candidate(rec, f"{domain}:compose", P.COMPOSE.format(domain=domain, components=P.COMPONENTS, evidence_rule=P.EVIDENCE_IS_DATA,
                                                                                  harness=harness_text, candidates=cand_text), cur, tools)
        if not final:
            out["notes"] = "the composer kept the harness as it is"
            return self._learn(rec, out, lib, domain, None)
        out["final"] = final
        for c in out["candidates"]:
            h.set_meta(c["version"], adopted_by="probed")        # kept for the record; the composed version is the one that counts
        changed = set(h.meta(final).get("files") or []) | set(h.meta(final).get("removed") or [])
        always = bool(changed & set(ALWAYS_ON))

        rec["stage"] = f"{domain}: gate"
        gate = await self.gate(domain, cur, final, full=always)
        out["gate"] = gate
        h.set_meta(final, gate=gate)
        if not gate.get("ok"):
            out["decision"], out["notes"] = "gate failed", gate.get("why", "")
            h.set_meta(final, adopted_by="rejected")
        elif always:
            out["decision"] = "proposed"                     # a prompt or guardrail change: the user approves it
            h.set_meta(final, adopted_by="proposed")
        else:
            out["decision"] = "adopted"
            h.set_meta(final, adopted_by="auto")
            h.activate(final)
        return await self._learn_async(rec, out, lib, domain, final)

    def _learn(self, rec: dict[str, Any], out: dict[str, Any], lib: Library, domain: str, final: int | None) -> dict[str, Any]:
        out["library"] = None
        return out

    async def _learn_async(self, rec: dict[str, Any], out: dict[str, Any], lib: Library, domain: str, final: int | None) -> dict[str, Any]:
        rec["stage"] = f"{domain}: library"
        record = json.dumps({k: out.get(k) for k in ("candidates", "probe", "final", "gate", "decision", "notes")}, default=str)[:8000]
        text = await self.ask(rec, f"{domain}:experience", P.EXPERIENCE.format(domain=domain, record=record, evidence_rule=P.EVIDENCE_IS_DATA))
        exp = None if "NO_ENTRY" in text and not _json(text) else _json(text)
        diff = self.harness.diff(self.harness.meta(final).get("parent") or 0, final) if final else ""
        path = lib.add(rec["id"], exp or {}, diff, adopted=out["decision"]) if exp else None
        out["library"] = str(path) if path else None
        return out

    async def _candidate(self, rec: dict[str, Any], stage: str, prompt: str, parent: int, tools: set[str]) -> int | None:
        """A model reply → a validated candidate version (retried once with the problem), or None."""
        from ..harness import HarnessError

        for attempt in range(2):
            reply = await self.ask(rec, stage, prompt)
            j = _json(reply)
            if not j or j.get("keep_base") or not (j.get("files") or j.get("removed")):
                return None
            try:
                files = {str(k): str(v) for k, v in (j.get("files") or {}).items()}
                return self.harness.create(files, list(j.get("removed") or []), parent=parent, notes=str(j.get("notes") or "")[:2000],
                                           adopted_by="candidate", tools=tools)
            except HarnessError as e:
                prompt += f"\n\n# YOUR LAST REPLY WAS REFUSED\n{e}\nFix that and reply again with the JSON only."
                rec["ledger"].append({"stage": stage, "refused": str(e)[:300], "attempt": attempt + 1})
        return None

    def _records(self, chats: list[str]) -> list[R.Record]:
        recs = [R.record(self.agent.store.events(t), t) for t in chats]
        recs.sort(key=lambda r: -(r.edited * 2 + r.errors))     # chats with edits and errors teach the most
        return [r for r in recs if r.turns][: self.probe_chats]

    async def probe(self, records: list[R.Record], version: int) -> dict[str, Any]:
        if self._probe:
            return await self._probe(records, version)
        res = [await R.replay(r, version, self.base, self.model, self.transport) for r in records]
        pc = [x["pre_chosen"] for x in res if x["pre_chosen"] is not None]
        return {"pre_chosen": round(sum(pc) / len(pc), 3) if pc else None, "errors": sum(x["errors"] for x in res),
                "denied_repeats": sum(x["denied_repeats"] for x in res), "ran": all(x["ran"] for x in res), "replays": len(res)}

    async def gate(self, domain: str, cur: int, cand: int, full: bool = False) -> dict[str, Any]:
        if self._gate:
            return await self._gate(domain, cur, cand, full)
        from evals.harness import Harness as EvalHarness
        from evals.harness import grade
        from evals.tasks import TASKS

        pre = DOMAINS[domain]
        tasks = TASKS if full else [t for t in TASKS if t.id in CORE or any(any(p in name for p in pre) for name, _ in t.checks)]

        async def rate(version: int) -> float:
            h = EvalHarness(self.base, self.model, dry_run=True, transport=self.transport, log=lambda _m: None)
            sem = asyncio.Semaphore(8)

            async def one(t: Any) -> bool:
                async with sem:
                    from dataclasses import replace
                    oks = []
                    for _ in range(self.gate_runs):
                        run = await h.run(replace(t, settings={**t.settings, "harness": version}))
                        oks.append(grade(t, run)["ok"])
                    return all(oks)
            try:
                got = await asyncio.gather(*(one(t) for t in tasks))
            finally:
                await h.close()
            return sum(got) / len(got) if got else 1.0
        before, after = await rate(cur), await rate(cand)
        ok = after >= before and (not full or after >= 0.8)
        return {"ok": ok, "tasks": len(tasks), "runs": self.gate_runs, "full": full, "current": round(before, 3), "candidate": round(after, 3),
                "why": "" if ok else f"pass^{self.gate_runs} {after:.0%} against {before:.0%} for the current harness" + (" (full suite needs 80%)" if full else "")}

    async def _schemas(self, domain: str, names: set[str]) -> dict[str, Any]:
        """The domain's tools' parameters as the model reads them (the hub's model view)."""
        want = sorted(n for n in names if n.startswith(DOMAINS[domain]))[:12]
        try:
            return {t["name"]: t.get("parameters") or {} for t in await self.agent.hub.tools(want)} if want else {}
        except Exception:  # noqa: BLE001
            return {}

    async def _tool_names(self) -> set[str]:
        try:
            return {t["name"] for t in await self.agent.hub.index()} | {"ask_user", "update_todos", "find_tools", "load_tools",
                                                                        "read_skill", "view_output", "read_result", "remember"}
        except Exception:  # noqa: BLE001
            return set()
