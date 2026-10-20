"""The eval harness (plan 13.5): runs scripted conversations against the agent's HTTP API, answers
its questions and parameter cards from the task's script, and grades the outcome.

A run never needs a person: questions are answered by `Task.answer`, cards by `Task.card`
(approve as-is, approve with edits, or deny). With `dry_run`, generating tools stand in existing
outputs (the hub's dry-run), so 30 tasks × 3 runs fit in minutes without the GPU; live runs make
real outputs.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

REF = re.compile(r"#(\d+)\b")
EQUIV = {"comfy_generate_image": ("zimage-turbo", "zimage-intorealism", "qwen21-t2i"), "comfy_animate_image": ("wan21-i2v",),
         "comfy_generate_video": ("wan21-t2v",), "comfy_edit_image": ("qwen21-edit-multi",),
         "comfy_remove_background": ("qwen21-remove-bg",)}


@dataclass
class Run:
    """One conversation's record, with helpers for the checks."""

    task: str
    model: str
    events: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None
    fork_events: list[dict[str, Any]] = field(default_factory=list)
    original_before: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def of(self, t: str, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return [e["payload"] for e in (self.events if events is None else events) if e["type"] == t]

    def calls(self, name: str | None = None, by: str | None = "model", events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return [c for c in self.of("tool_call", events) if (name is None or c["name"] == name) and (by is None or c.get("by") == by)]

    def results(self, name: str | None = None, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if name in EQUIV:
            evs = self.events if events is None else events
            ids = {c["id"] for c, _ in self._equiv(name, evs)}
            return [r for r in self.of("tool_result", evs) if r["id"] in ids]
        return [r for r in self.of("tool_result", events) if name is None or r["name"] == name]

    def _equiv(self, name: str, evs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(call, the arguments it ran with) for `name`, counting `comfy_run_workflow` with one of
        `name`'s workflows as the same thing."""
        decided = {d["id"]: d.get("arguments") for d in self.of("decision", evs) if d.get("approve")}
        normalized = {a["id"]: a.get("arguments") for a in self.of("approval", evs)}   # as the hub read them
        out = []
        for c in self.calls(None, by=None, events=evs):
            args = decided.get(c["id"]) or normalized.get(c["id"]) or c.get("arguments") or {}
            if c["name"] == name:
                out.append((c, args))
            elif c["name"] in ("comfy_run_workflow", "comfy_run") and args.get("workflow") in EQUIV.get(name, ()):
                out.append((c, {**(args.get("inputs") or {}), "workflow": args["workflow"]}))
        return out

    def done(self, name: str, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        evs = self.events if events is None else events
        ids = {c["id"] for c, _ in self._equiv(name, evs)}
        return [r for r in self.of("tool_result", evs) if r["id"] in ids and r["status"] == "done"]

    def final_args(self, name: str, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """The arguments each `name` call ran with (after card edits)."""
        return [a for _, a in self._equiv(name, self.events if events is None else events)]

    def asked(self) -> bool:
        return bool(self.of("question"))

    def outputs(self, events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return [o for r in self.of("tool_result", events) for o in r.get("outputs") or []]

    def text(self) -> str:
        return "\n".join(a.get("text") or "" for a in self.of("assistant"))

    def final(self) -> str:
        a = self.of("assistant")
        return (a[-1].get("text") or "") if a else ""

    def usage(self) -> dict[str, int]:
        u = self.of("usage")
        return {"steps": len(u), "prompt_tokens": max((x.get("prompt_tokens") or 0 for x in u), default=0),
                "completion_tokens": sum(x.get("completion_tokens") or 0 for x in u)}


Check = Callable[[Run], tuple[bool, str]]


@dataclass
class Task:
    id: str
    group: str
    turns: list[str]
    checks: list[tuple[str, Check]]
    mode: str = "ask"
    settings: dict[str, Any] = field(default_factory=dict)
    answer: Callable[[dict[str, Any]], dict[str, Any]] | None = None     # a question → answers
    card: Callable[[dict[str, Any]], tuple[bool, dict[str, Any] | None]] | None = None   # approval → (approve, edits)
    fork_after_turn: int | None = None      # fork after this turn (1-based) and send `fork_turn` there
    fork_turn: str | None = None
    compact_after_turn: int | None = None
    setup: Callable[[], Any] | None = None
    prefs: list[dict[str, Any]] = field(default_factory=list)   # preferences seeded for this task, removed after (plan 21.6)
    timeout: float = 600
    note: str = ""


def first_option(q: dict[str, Any]) -> dict[str, Any]:
    return {x["question"]: (x.get("options") or [{"label": "yes"}])[0]["label"] for x in q["questions"]}


def approve_all(a: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    """The default answer to a card: approve, except destructive ones (stopping a mod, deleting),
    which a careful person would refuse unless they asked for it."""
    return a.get("risk") != "destructive", None


class Harness:
    def __init__(self, base: str, model: str, dry_run: bool = True, all_tools: bool = False,
                 log: Callable[[str], None] = print, transport: Any = None) -> None:
        self.base, self.model, self.dry_run, self.all_tools, self.log = base.rstrip("/"), model, dry_run, all_tools, log
        self.c = httpx.AsyncClient(base_url=self.base, timeout=httpx.Timeout(60, connect=10), trust_env=False, transport=transport)
        self.glitches: list[str] = []      # transient HTTP failures seen (and retried)

    async def close(self) -> None:
        await self.c.aclose()

    async def _events(self, tid: str) -> list[dict[str, Any]]:
        last = None
        for _ in range(5):
            try:
                r = await self.c.get(f"/v1/threads/{tid}/events")
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
            self.glitches.append(last)
            await asyncio.sleep(1)
        raise RuntimeError(f"events of {tid}: {last}")

    async def _settle(self, tid: str, deadline: float) -> str:
        while time.monotonic() < deadline:
            try:
                r = await self.c.get(f"/v1/threads/{tid}")
                t = r.json() if r.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                t = {}
            if t and not t.get("running") and t.get("state") != "running":
                return t["state"]
            await asyncio.sleep(0.5)
        raise TimeoutError("the turn didn't finish in time")

    async def _drive(self, task: Task, tid: str, text: str, deadline: float) -> None:
        """Send one user turn and answer questions and cards until the turn is over."""
        if text == "/compact":
            r = await self.c.post(f"/v1/threads/{tid}/compact")
            r.raise_for_status()
            return
        r = await self.c.post(f"/v1/threads/{tid}/messages", json={"text": text})
        r.raise_for_status()
        handled: set[str] = set()
        for _ in range(40):
            state = await self._settle(tid, deadline)
            if state != "waiting":
                return
            evs = await self._events(tid)
            done = {e["payload"]["id"] for e in evs if e["type"] == "tool_result"}
            pending_q = [e["payload"] for e in evs if e["type"] == "question" and e["payload"]["id"] not in done
                         and e["payload"]["id"] not in handled]
            decided = {e["payload"]["approval_id"] for e in evs if e["type"] == "decision"}
            pending_a = [e["payload"] for e in evs if e["type"] == "approval" and e["payload"]["approval_id"] not in decided
                         and e["payload"]["approval_id"] not in handled]
            if pending_q:
                q = pending_q[0]
                handled.add(q["id"])
                answers = (task.answer or first_option)(q)
                await self.c.post(f"/v1/threads/{tid}/answer", json={"question_id": q["id"], "answers": answers})
            elif pending_a:
                a = pending_a[0]
                handled.add(a["approval_id"])
                ok, edits = (task.card or approve_all)(a)
                args = {**(a.get("arguments") or {}), **edits} if edits else None
                r = await self.c.post(f"/v1/threads/{tid}/approval", json={"approval_id": a["approval_id"], "approve": ok,
                                                                          "arguments": args, "reason": None if ok else "No, don't do that."})
                if r.status_code >= 400:
                    await self.c.post(f"/v1/threads/{tid}/approval", json={"approval_id": a["approval_id"], "approve": ok})
            else:
                return
        return

    async def _followup(self, task: Task, tid: str, deadline: float) -> None:
        """The model asked in words instead of a card: answer with the task's typed text, once."""
        text = getattr(task.answer, "text", None)
        if not text:
            return
        evs = await self._events(tid)
        last_user = max((e["seq"] for e in evs if e["type"] == "user"), default=0)
        after = [e for e in evs if e["seq"] > last_user]
        asked = any(e["type"] == "assistant" and "?" in (e["payload"].get("text") or "") for e in after)
        acted = any(e["type"] == "tool_result" and e["payload"].get("status") == "done" and
                    e["payload"].get("name") not in ("read_skill", "load_tools", "find_tools", "ask_user", "tts_list_voices",
                                                     "hub_search_outputs", "hub_list_services") for e in after)
        if asked and not acted:
            await self._drive(task, tid, text, deadline)

    async def run(self, task: Task) -> Run:
        run = Run(task.id, self.model)
        t0 = time.monotonic()
        deadline = t0 + task.timeout
        settings = {"dry_run": self.dry_run, **task.settings}
        if self.all_tools:
            settings["pinned"] = ["comfy", "tts", "gen3d", "lcpp", "relay"]
        tid = None
        seeded: list[str] = []
        try:
            if task.setup:
                r = task.setup()
                if asyncio.iscoroutine(r):
                    await r
            for attempt in range(5):
                r = await self.c.post("/v1/threads", json={"title": f"{'eval' if self.dry_run else 'live'} {task.id}", "model": self.model, "mode": task.mode,
                                                           "settings": settings})
                if r.status_code == 201:
                    tid = r.json()["id"]
                    break
                self.glitches.append(f"create thread: HTTP {r.status_code}: {r.text[:200]}")
                await asyncio.sleep(1 + attempt)
            if tid is None:
                raise RuntimeError("couldn't create a thread: " + self.glitches[-1])
            run.extra["thread"] = tid
            for p in task.prefs:            # for this chat only (scope thread), so tasks running at once don't see them
                r = await self.c.post("/v1/prefs", json={**p, "scope": "thread", "thread": tid})
                if r.status_code < 400:
                    seeded.append(r.json()["id"])
                else:
                    self.glitches.append(f"seed preference: HTTP {r.status_code}: {r.text[:200]}")
            for i, text in enumerate(task.turns, 1):
                await self._drive(task, tid, text, deadline)
                if i == len(task.turns):
                    await self._followup(task, tid, deadline)
                if task.compact_after_turn == i:
                    await self.c.post(f"/v1/threads/{tid}/compact")
                if task.fork_after_turn == i:
                    evs = await self._events(tid)
                    seq = max(e["seq"] for e in evs if e["type"] == "assistant")
                    run.original_before = evs
                    fork = (await self.c.post(f"/v1/threads/{tid}/fork", json={"seq": seq})).json()
                    run.extra["fork"] = fork["id"]
            if task.fork_turn and run.extra.get("fork"):
                await self.c.patch(f"/v1/threads/{run.extra['fork']}", json={"settings": settings})
                await self._drive(task, run.extra["fork"], task.fork_turn, deadline)
                run.fork_events = await self._events(run.extra["fork"])
            run.events = await self._events(tid)
        except Exception as e:  # noqa: BLE001
            import traceback

            run.error = f"{type(e).__name__}: {e}"[:300]
            run.extra["traceback"] = traceback.format_exc()[-1500:]
            if tid:
                try:
                    await self.c.post(f"/v1/threads/{tid}/cancel")
                    run.events = await self._events(tid)
                except Exception:  # noqa: BLE001
                    pass
        for pid in seeded:
            try:
                await self.c.delete(f"/v1/prefs/{pid}")
            except Exception:  # noqa: BLE001
                pass
        if self.dry_run:  # dry-run threads go to Archived, out of the chat list (live ones stay as examples)
            for t in (tid, run.extra.get("fork")):
                if t:
                    try:
                        await self.c.patch(f"/v1/threads/{t}", json={"archived": True})
                    except Exception:  # noqa: BLE001
                        pass
        run.seconds = round(time.monotonic() - t0, 1)
        return run


def grade(task: Task, run: Run) -> dict[str, Any]:
    results = []
    for name, check in task.checks:
        try:
            ok, why = check(run)
        except Exception as e:  # noqa: BLE001
            ok, why = False, f"check crashed: {type(e).__name__}: {e}"
        results.append({"check": name, "ok": bool(ok), "why": why})
    errors = [e for e in run.of("error")]
    if run.error:
        results.append({"check": "ran to the end", "ok": False, "why": run.error})
    if errors:
        results.append({"check": "no agent errors", "ok": False, "why": "; ".join(e.get("detail", "")[:120] for e in errors)})
    # never invents outputs: every #n in the replies exists
    made = {o["n"] for o in run.outputs()}
    named = {int(n) for n in REF.findall(run.text())}
    bad = sorted(named - made)
    results.append({"check": "no invented outputs", "ok": not bad, "why": f"mentions #{bad} that don't exist" if bad else ""})
    return {"task": task.id, "group": task.group, "ok": all(r["ok"] for r in results), "checks": results,
            "seconds": run.seconds, "usage": run.usage(), "turns": task.turns,
            "tools": [c["name"] for c in run.of("tool_call")], "asked": run.asked(), "final": run.final()[:600],
            "notes": [n.get("text") for n in run.of("note")], "thread": run.extra.get("thread")}


def summary(rows: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["task"], []).append(r)
    tasks = []
    for tid, rs in by.items():
        tasks.append({"task": tid, "group": rs[0]["group"], "passes": sum(r["ok"] for r in rs), "runs": len(rs),
                      "pass_k": len(rs) >= runs and all(r["ok"] for r in rs),
                      "failed_checks": sorted({c["check"] for r in rs for c in r["checks"] if not c["ok"]})})
    n = len(tasks)
    return {"tasks": n, "pass_k": sum(t["pass_k"] for t in tasks), "pass_k_rate": round(sum(t["pass_k"] for t in tasks) / n, 3) if n else 0,
            "pass_1_rate": round(sum(r["ok"] for r in rows) / len(rows), 3) if rows else 0,
            "by_task": tasks, "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1) if rows else 0}


def dump(path: Any, obj: Any) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
