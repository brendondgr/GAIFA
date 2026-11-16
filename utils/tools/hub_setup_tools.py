"""The hub's setup tools (plan capability-enablement 4.1): the chat agent sets mods up the way the app's dialog does, with
the same `gaifa setup` job (utils/setup_jobs.py).

- `hub_setup_plan` (read): what setting these mods up would do, in words the model passes on in full.
- `hub_setup` (execute, never at /mcp): runs the setup and waits for it; a card in every mode (the ask list), refused in
  an unattended run; `needs_you` comes back as what the person must run.
- `hub_setup_test` (read): a mod's test on this machine (its setup doc's smoke), with what it measured.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from utils.tools.modcall import ToolError

if TYPE_CHECKING:
    from utils.server import Hub

IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12,
       "description": "Mod ids to set up, e.g. [\"web\"] (hub_list_services lists them; Off on this machine names them)"}
ANSWERS = {"type": "object", "description": "The person's answers to the plan's questions, as gaifa setup takes them: "
           "{accept: [question ids], decline: [ids], models: {<setup id>: [names]}, values: {<id>: value}, done: [step ids they ran]}"}


def _gb(n: Any) -> str:
    return f"{n:.1f} GB" if isinstance(n, (int, float)) else "?"


def plan_text(plan: dict[str, Any]) -> str:
    """The plan in plain sentences: what it gives, what is installed and where, downloads with source and licence,
    containers, size, the variant, questions, host problems."""
    out = []
    for a in plan.get("about") or []:
        out.append(f"{a['name']} ({a['id']}): {a.get('provides') or a.get('description') or ''}. It goes in {a['folder']}"
                   + (f" and listens on 127.0.0.1:{a['port']}" if a.get("port") else "") + ".")
    for s in plan.get("steps") or []:
        out.append(f"Step {s['id']}: {s['what']}" + (" (the person runs this one)" if s.get("interactive") else "") + ".")
    for d in plan.get("suggestions") or []:
        out.append(f"Download {d['name']}: {_gb(d.get('size_gb'))} from {d.get('source') or d.get('repo') or 'its source'}"
                   + (f", licence {d['licence']}" if d.get("licence") else "") + (" (needed)" if d.get("required") else "")
                   + (" (its terms must be accepted on Hugging Face first)" if d.get("gated") else "") + ".")
    for img, gb in (plan.get("images") or {}).items():
        out.append(f"Container image {img} ({_gb(gb)}).")
    out.append(f"In all about {_gb(plan.get('disk_gb'))} on disk" + (f" plus {_gb(plan['required_models_gb'])} of models" if plan.get("required_models_gb") else "") + ".")
    for v in plan.get("variants") or []:
        out.append(f"For this machine: {v['setup']} as {v['label']}" + (" (not tested on this kind of machine)" if v.get("untested") else "") + ".")
    for q in plan.get("questions") or []:
        out.append(f"Question {q['id']}: {q.get('text') or q['id']}" + (f" (choices: {', '.join(q['choices'])})" if q.get("choices") else "") + ".")
    for h in plan.get("host") or []:
        if not h.get("ok", True) and (not h.get("gpu") or plan.get("gpu")):
            out.append(f"Fix first: {h['detail']}" + (f": {h['fix']}" if h.get("fix") else "") + (" (needs sudo: the person runs it)" if h.get("needs_root") else "") + ".")
    for u in plan.get("unavailable") or []:
        out.append(f"Can't run here: {u['setup']}: {u['why']}.")
    return "\n".join(out)


async def setup_plan(hub: Hub, args: dict[str, Any]) -> Any:
    plan = await hub.setup.plan(list(args["ids"]))
    return {"text": plan_text(plan), "questions": plan.get("questions") or [],
            "blocking": plan.get("blocking") or [], "next": "tell the user all of this, ask the questions, and call hub_setup "
            "with their answers only once they say yes"}


async def setup(hub: Hub, args: dict[str, Any]) -> Any:
    """Start the job and wait for it (the call stays running; job_status follows it). Cancelling the call stops it."""
    jobs = hub.setup
    job = await jobs.start(list(args["ids"]), dict(args.get("answers") or {}))
    try:
        while jobs.job and jobs.job["id"] == job["id"] and jobs.job["state"] == "running":
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        await jobs.cancel()
        raise
    j = jobs.public() or job
    if j["state"] == "done":
        return {"state": "done", "started": j.get("started") or [], "report": _short(j.get("report")),
                "next": "say what works now (hub_setup_test checks a mod with a test) and what still needs the user"}
    if j["state"] == "needs_you":
        n = j.get("needs") or {}
        return {"state": "needs_you", "questions": n.get("questions") or [], "steps_for_the_user": n.get("interactive") or [],
                "host": n.get("host") or [], "next": "tell the user exactly what to run or answer; after they have, call hub_setup "
                "again with done: [the step ids] or their answers"}
    raise ToolError("setup_failed", j.get("error") or f"setting up {', '.join(j['ids'])} {j['state']}",
                    "tell the user what failed and where its log is (data/state/setup/logs/); offer the coding-agent prompt "
                    "(gaifa setup --prompt) as the easier way; don't retry it yourself")


def _short(report: Any) -> Any:
    if not isinstance(report, dict):
        return report
    return {k: report[k] for k in ("done", "failed", "skipped", "next") if k in report}


async def setup_test(hub: Hub, args: dict[str, Any]) -> Any:
    from utils.services.model import ServiceError

    try:
        t = await hub.setup.test(str(args["id"]))
    except ServiceError as e:
        raise ToolError(e.code, e.detail, "this mod has no test; say it is set up and running instead") from None
    return {k: t[k] for k in ("id", "passed", "seconds", "device", "log")}


def specs(obj: Any) -> list[tuple[str, str, dict[str, Any], Any, str]]:
    """(name, description, parameters, handler, risk) for hub_tools.tools()."""
    return [
        ("setup_plan", "What setting mods up would do on this machine: what each gives, what is installed and where, sizes, "
         "downloads with their source and licence, containers and ports, the questions to ask, and host problems. Tell the "
         "user all of it before hub_setup.", obj({"ids": IDS}, ["ids"]), setup_plan, "read"),
        ("setup", "Set mods up (runs gaifa setup and waits; minutes for a large one). Only after the user said yes to "
         "hub_setup_plan's plan, with their answers to its questions. Returns what was started, or what the user must run.",
         obj({"ids": IDS, "answers": ANSWERS}, ["ids"]), setup, "execute"),
        ("setup_test", "Run a mod's test on this machine (real work, such as one answer or one picture) and say how long it "
         "took and on what device.", obj({"id": {"type": "string", "description": "A mod id"}}, ["id"]), setup_test, "read"),
    ]
