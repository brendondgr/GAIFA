"""Tools for the agent (plan 11.10), read by AIHub's tool catalog through `[agent] tools_source`.

One tool per task that has a ready pack (`generate_image`, `animate_image`, …): its parameters are
the task's shared inputs that those packs take, plus an optional `workflow` choosing among them
(without it the task's default pack runs, else its only one) and, when any of them has presets,
an optional `preset` (`fast`, `draft`, … from the packs' `[presets.*]`). `list_workflows` and `run_workflow`
reach any pack. A tool call becomes a run: `{"status": "running", "job_id": …}`, and the job's
route (`GET /v1/jobs/{id}?wait=`) gives its outputs.
"""

from __future__ import annotations

from typing import Any

from .library import Library
from .schema import input_schema

CALL_OP = "POST /v1/tools/{name}/call"
JOB = {"status": "GET /v1/jobs/{job_id}?wait=60", "cancel": "POST /v1/queue/{job_id}/cancel"}


ASK = ("workflow", "preset", "aspect", "megapixels", "seconds")   # choices shown on the parameter card (plan 13.1)
KIND = {"image": "image", "images": "image", "mask": "image", "video": "video"}
EXAMPLES = {"generate_image": [{"prompt": "a red fox sitting in fresh snow, golden hour", "aspect": "16:9 (Widescreen)"}],
            "animate_image": [{"image": "output:<id of an image>", "prompt": "the fox turns its head and blinks"}],
            "edit_image": [{"image": "output:<id>", "prompt": "make it night time"}]}


def _fn(name: str, description: str, parameters: dict, job: bool = True, risk: str = "generate") -> dict:
    for k, p in (parameters.get("properties") or {}).items():
        if k in KIND:
            p["x-kind"] = KIND[k]
    ask = [k for k in ASK if k in (parameters.get("properties") or {})]
    out = {"type": "function", "function": {"name": name, "description": description, "parameters": parameters},
           "op": CALL_OP.replace("{name}", name), "job": JOB if job else None, "risk": risk, "ask": ask}
    if name in EXAMPLES:
        out["examples"] = EXAMPLES[name]
    return out


def ready_by_task(lib: Library) -> dict[str, list]:
    out: dict[str, list] = {}
    for p in lib.packs.packs():
        _, issues = lib.analysed(p)
        if lib.state(p, issues) == "ready":
            out.setdefault(p.task, []).append(p)
    return out


def catalog(lib: Library, defaults: dict[str, str]) -> list[dict]:
    lib.packs.scan()
    by_task = ready_by_task(lib)
    tools = []
    for tid, packs in sorted(by_task.items()):
        task = lib.tasks.get(tid)
        if task is None or not task.tool:
            continue
        props: dict[str, Any] = {}
        for p in packs:
            conv, _ = lib.analysed(p)
            for k, v in input_schema(p, conv, lib.catalog, lib.tasks)["properties"].items():
                if k in lib.tasks.inputs and k not in props:
                    shared = lib.tasks.inputs[k]
                    q = {kk: vv for kk, vv in v.items() if kk in ("type", "enum", "minimum", "maximum", "format", "items")}
                    q["description"] = shared.get("description") or v.get("description", "")
                    if shared.get("choices"):      # one list for every pack (each pack's own labels are matched by ratio)
                        q["enum"] = list(shared["choices"])
                    if k == "seed":
                        q["minimum"] = -1
                    props[k] = q
        default = defaults.get(tid) or (packs[0].id if len(packs) == 1 else None)
        props["workflow"] = {"type": "string", "enum": sorted(p.id for p in packs),
                             "description": "Which workflow to use" + (f" (default: {default})" if default else "")}
        presets = sorted({name for p in packs for name in p.manifest.presets})
        if presets:
            props["preset"] = {"type": "string", "enum": presets,
                               "description": "A preset of the chosen workflow (its line below lists them): fast and draft "
                                              "trade size and detail for speed. Leave it out for the full-quality default."}
        lines = [task.description, "Workflows:"] + [
            f"- {p.id}: {p.name}" + (f" — {p.manifest.description}" if p.manifest.description and p.manifest.description != p.name else "")
            + (f" (presets: {', '.join(p.manifest.presets)})" if p.manifest.presets else "")
            + (" [default]" if p.id == default else "") for p in sorted(packs, key=lambda p: p.id != default)]
        lines.append("Returns a job; its outputs (files) come when it finishes.")
        req = [r for r in task.required if r in props]
        tools.append(_fn(task.tool, "\n".join(lines), {"type": "object", "properties": props, "required": req,
                                                     "additionalProperties": False}))
    all_ready = sorted(p.id for ps in by_task.values() for p in ps)
    tools.append(_fn("list_workflows", "List the image and video workflows, with their tasks and inputs.",
                     {"type": "object", "properties": {}}, job=False, risk="read"))
    tools.append(_fn("run_workflow", "Run a workflow by id with its own inputs (see list_workflows). Only for workflows the "
                     "task tools don't cover: for images, edits, animation, video and background removal use generate_image, "
                     "edit_image, animate_image, generate_video and remove_background (they take a `workflow` too).",
                     {"type": "object", "properties": {
                         "workflow": {"type": "string", "enum": all_ready},
                         "inputs": {"type": "object", "description": "The workflow's inputs by name"},
                         "preset": {"type": "string", "description": "One of the workflow's presets"}},
                      "required": ["workflow"], "additionalProperties": False}))
    return tools


def pick(lib: Library, task_id: str, workflow: str | None, defaults: dict[str, str]):
    packs = ready_by_task(lib).get(task_id, [])
    if workflow:
        p = next((p for p in packs if p.id == workflow), None)
        if p is None:
            raise ValueError(f"{workflow!r} isn't a ready {task_id} workflow (have: {', '.join(x.id for x in packs) or 'none'})")
        return p
    p = next((p for p in packs if p.id == defaults.get(task_id)), None) or (packs[0] if len(packs) == 1 else None)
    if p is None:
        raise ValueError(f"choose a workflow for {task_id}: {', '.join(x.id for x in packs) or 'none is ready'}")
    return p


def list_workflows(lib: Library) -> list[dict]:
    out = []
    for ps in ready_by_task(lib).values():
        for p in ps:
            conv, _ = lib.analysed(p)
            sch = input_schema(p, conv, lib.catalog, lib.tasks)
            out.append({"id": p.id, "name": p.name, "task": p.task, "description": p.manifest.description,
                        "inputs": {k: v.get("type") for k, v in sch["properties"].items()},
                        "required": sch.get("required", []), "presets": list(p.manifest.presets)})
    return sorted(out, key=lambda w: (w["task"], w["id"]))
