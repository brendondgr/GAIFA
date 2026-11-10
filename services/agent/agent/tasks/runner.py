"""Runs of a scheduled task (plan scheduled-tasks 2.2): each is a new chat with no one watching.

`Runner.start(task, why, due)` records a run and launches it when a slot is free:
1. **The chat:** titled "<task> · <Mon 10 Nov 07:00>", in the task's model and mode, with `settings` `{task, task_run,
   unattended, no_learn, use_profile, use_project_memory, task_env?, task_only?}` and the task's tool groups; a project
   task takes the project's defaults under the task's own (`api_projects.new_chat`). The MCP servers it pre-allows are on.
2. **Pre-allows** become the chat's grants (`POST /api/grants`): each tool glob, each site (`web_fetch` per host, or
   every site), each MCP server (`mcp_<server>_*`). One that the hub refuses is noted and the run goes on.
3. **The judge:** in Auto, `GET /api/judge/status` first; when it doesn't answer, a note says only pre-allowed calls will
   run (the judge fails closed, so everything else is refused) and the run's `judge` says so.
4. **The first message** is the instructions, as a user event with `by: "schedule"`.

A run ends with its chat's first turn (`on_turn_end`): `done`, or `failed` when the turn ended in an error (or, with no one
watching, waiting on a card), with `refused` counted from its results and `seen: false`. After that the chat is a
normal chat; later turns never change the run.

Limits: at most `parallel` runs at once (test runs, which you watch, don't count); more wait as `queued`, oldest first,
and one that waited more than `max_wait_s` is `skipped` (busy). A task whose last run is still going skips the new one.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger("agent.tasks")
PARALLEL = int(os.environ.get("AGENT_TASKS_PARALLEL", "2"))
MAX_WAIT_S = float(os.environ.get("AGENT_TASKS_MAX_WAIT_S", "3600"))
WEB_TOOL = "web_fetch"           # the tool whose grant key is a site (url:host)


def title_of(task: dict[str, Any], due: float) -> str:
    return f"{task['name']} · {time.strftime('%a %d %b %H:%M', time.localtime(due))}"


def refused_count(events: list[dict[str, Any]]) -> int:
    return sum(1 for e in events if e["type"] == "tool_result"
               and ((e["payload"].get("error") or {}).get("code") == "unattended"))


class Runner:
    def __init__(self, agent: Any, parallel: int = PARALLEL, max_wait_s: float = MAX_WAIT_S, clock: Any = time.time) -> None:
        self.agent, self.parallel, self.max_wait_s, self.clock = agent, parallel, max_wait_s, clock
        self.k = agent.scheduled
        agent.on_turn_end.append(self.turn_ended)

    def publish(self, run: dict[str, Any] | None) -> None:
        if run is not None:
            from ..api_tasks import publish_run
            publish_run(self.agent, run)

    def running(self) -> list[dict[str, Any]]:
        return [r for r in self.k.active() if r["state"] == "running" and not r["test"]]

    async def start(self, task: dict[str, Any], why: str, due: float | None = None, late: int = 0,
                    test: bool = False, occurrence: str | None = None) -> dict[str, Any]:
        """Record a run of `task` and launch it when a slot is free (a test run at once)."""
        due = self.clock() if due is None else due
        if not test and any(not r["test"] for r in self.k.active(task["id"])):
            run = self.k.add_run(task["id"], due, state="skipped", why="still running", late=late, occurrence=occurrence)
            self.publish(run)
            return run
        run = self.k.add_run(task["id"], due, state="queued", why=why, late=late, test=test, occurrence=occurrence)
        self.publish(run)
        if test or len(self.running()) < self.parallel:
            return await self.launch(run)
        return run

    async def drain(self) -> None:
        """Launch queued runs while slots are free; skip the ones that waited too long."""
        for run in [r for r in self.k.active() if r["state"] == "queued"]:
            if self.clock() - run["due"] > self.max_wait_s:
                self.publish(self.k.update_run(run["id"], state="skipped", why="busy", ended=self.clock()))
                continue
            if len(self.running()) >= self.parallel:
                return
            await self.launch(run)

    async def launch(self, run: dict[str, Any]) -> dict[str, Any]:
        task = self.k.get(run["task_id"])
        if task is None:
            return self.k.update_run(run["id"], state="skipped", why="the task is gone", ended=self.clock()) or run
        try:
            return await self._launch(task, run)
        except Exception as e:  # noqa: BLE001: one run failing never stops the scheduler
            log.exception("starting run %s of task %s", run["id"], task["id"])
            out = self.k.update_run(run["id"], state="failed", why=f"couldn't start: {type(e).__name__}: {e}"[:300],
                                    ended=self.clock(), seen=False)
            self.publish(out)
            return out or run

    def chat_settings(self, task: dict[str, Any], run: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
        from ..api_projects import new_chat
        s: dict[str, Any] = {"task": task["id"], "task_run": run["id"], "no_learn": True,
                             "use_profile": task["use_profile"], "use_project_memory": task["use_project_memory"],
                             **{k: list(v) for k, v in (task.get("settings") or {}).items()}}
        if not run["test"]:
            s["unattended"] = True
        servers = [f"mcp:{m}" for m in task["allow"].get("mcp") or []]
        if servers:                                       # a pre-allowed MCP server is on in the run (its group listed)
            s["mcp_on"] = sorted(set(s.get("mcp_on") or []) | set(servers))
        if task.get("own_env"):
            s["task_env"] = task["own_env"]
            if task.get("only_own") or not task.get("project_id"):
                s["task_only"] = True
        if task.get("project_id") and self.agent.projects.get(task["project_id"]) is not None:
            s["project"] = task["project_id"]
        return new_chat(self.agent, s, task.get("model"), task.get("mode"))

    async def _launch(self, task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        agent = self.agent
        settings, model, mode = self.chat_settings(task, run)
        th = agent.store.create_thread(title_of(task, run["due"]), model, mode or "auto", settings)
        tid = th["id"]
        run = self.k.update_run(run["id"], state="running", thread_id=tid, started=self.clock()) or run
        self.publish(run)
        notes = [f"A scheduled run of “{task['name']}” ({task['when']})"
                 + (f", late: {run['late']} due time(s) passed while GAIFA was off; this one run stands for them" if run["late"] else "")
                 + (": a test run, with cards as usual." if run["test"] else ": no one is watching, so what would ask is refused.")]
        notes += await self._grants(tid, task)
        judge = None
        if (mode or "auto") == "auto":
            try:
                st = await agent.hub.judge_status()
                judge = "ok" if st.get("available") else f"unavailable: {st.get('detail') or 'no answer'}"
            except Exception as e:  # noqa: BLE001
                judge = f"unavailable: {type(e).__name__}"
            if judge != "ok":
                notes.append(f"The Auto judge isn't available ({judge[13:]}): only pre-allowed calls and what the rules "
                             "allow will run; the rest is refused.")
            run = self.k.update_run(run["id"], judge=judge) or run
        for n in notes:
            agent.emit(tid, "note", {"text": n, "level": "info" if "isn't available" not in n else "warn"})
        await agent.send(tid, task["instructions"] or task["name"], by="schedule")
        return self.k.run(run["id"]) or run

    async def _grants(self, tid: str, task: dict[str, Any]) -> list[str]:
        """The pre-allows as the chat's grants; what the hub refused, as notes."""
        allow, out, hub = task.get("allow") or {}, [], self.agent.hub
        wants: list[tuple[str, str | None, str | None]] = [(t, None, None) for t in allow.get("tools") or []]
        for site in allow.get("sites") or []:
            wants.append((WEB_TOOL, "url:any", None) if site == "*" else (WEB_TOOL, "url:host", site))
        wants += [(f"mcp_{m}_*", None, None) for m in allow.get("mcp") or []]
        for tool, kind, key in wants:
            try:
                await hub.add_grant(tid, tool, kind, key, note=f"pre-allowed by the scheduled task {task['name']}")
            except Exception as e:  # noqa: BLE001
                what = key or ("every site" if kind else tool)
                out.append(f"The pre-allow {what} couldn't be set ({getattr(e, 'detail', None) or e}); calls it would "
                           "have covered go to the judge.")
        return out

    async def turn_ended(self, tid: str) -> None:
        """A run's chat ended its first turn: the run is done (or failed). Later turns leave it alone."""
        t = self.agent.store.thread(tid) or {}
        rid = (t.get("settings") or {}).get("task_run")
        if not rid:
            return
        run = self.k.run(rid)
        if run is None or run["state"] != "running":
            return
        state = t.get("state")
        if state == "waiting" and run["test"]:
            return                                   # a test run waits on its card; you're there
        failed = state == "error" or (state == "waiting" and not run["test"])
        why = "the turn ended in an error" if state == "error" else "it waited on a card" if failed else run["why"]
        out = self.k.update_run(rid, state="failed" if failed else "done", ended=self.clock(), seen=False, why=why,
                                refused=refused_count(self.agent.store.events(tid, types=("tool_result",))))
        self.publish(out)
        from ..api_tasks import publish
        publish(self.agent, run["task_id"], self.k.get(run["task_id"]))
        await self.drain()
