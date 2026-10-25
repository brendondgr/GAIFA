"""Tools for the agent (plan 11.10), read by GAIFA's tool catalog through `[agent] tools_source`.

One tool per task that has a ready pack (`generate_image`, `animate_image`, …): its parameters are
the task's shared inputs that those packs take, plus an optional `workflow` choosing among them
(without it the task's default pack runs, else its only one) and, when any of them has presets,
an optional `preset` (`fast`, `draft`, … from the packs' `[presets.*]`). `list_workflows` and `run_workflow`
reach any pack the agent may use (`agent = false` in a manifest hides one). A tool call becomes a run: `{"status": "running", "job_id": …}`, and the job's
route (`GET /v1/jobs/{id}?wait=`) gives its outputs.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .library import Library
from .schema import input_schema

CALL_OP = "POST /v1/tools/{name}/call"
JOB = {"status": "GET /v1/jobs/{job_id}?wait=60&live=true", "cancel": "POST /v1/queue/{job_id}/cancel"}   # live: answer at each new step or frame (plan 45.5)


ASK = ("workflow", "preset", "aspect", "megapixels", "seconds")   # choices shown on the parameter card (plan 13.1)
KIND = {"image": "image", "images": "image", "mask": "image", "video": "video", "references": "image"}
REF = re.compile(r"image_(\d+)")       # a pack's extra reference pictures: image_2, image_3, …
QUICK = "only when the user asks for a quick, rough, draft or preview result"
EXAMPLES = {"generate_image": [{"prompt": "a red fox sitting in fresh snow, golden hour", "aspect": "16:9"}],
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


def runs_here(p) -> bool:
    """A pack's `requires` (plan 39.6) against this mod's variant (GAIFA_ACCEL; unset: anything runs)."""
    accel = os.environ.get("GAIFA_ACCEL")
    return not (accel and p.manifest and p.manifest.requires and accel not in p.manifest.requires)


def ready_by_task(lib: Library) -> dict[str, list]:
    """The ready packs the agent may use, by task: not the ones this machine's variant can't run."""
    out: dict[str, list] = {}
    for p in lib.packs.packs():
        if p.manifest and not p.manifest.agent:
            continue
        if not runs_here(p):
            continue
        _, issues = lib.analysed(p)
        if lib.state(p, issues) == "ready" and not (p.task == "image-edit" and p.manifest.edit is None):
            out.setdefault(p.task, []).append(p)
    return out


def references(p) -> int:
    """How many extra reference pictures a pack takes (its image_2 … inputs)."""
    return sum(1 for k in (p.manifest.inputs if p.manifest else {}) if REF.fullmatch(k) and int(REF.fullmatch(k).group(1)) >= 2)


def default_for(task_id: str, packs: list, defaults: dict[str, str], style: str | None = None):
    """The pack a call without `workflow` runs: the default for this edit style, then for the task, then the only one."""
    ids = {p.id: p for p in packs}
    for key in ([f"{task_id}:{style}"] if style else []) + [task_id]:
        if defaults.get(key) in ids and (style is None or ids[defaults[key]].manifest.edit == style):
            return ids[defaults[key]]
    fitting = [p for p in packs if style is None or p.manifest.edit == style]
    return fitting[0] if len(fitting) == 1 else None


def _summary(p) -> str:
    m = p.manifest
    return m.good_for or (m.description.split(". ")[0].split(";")[0] if m.description and m.description != p.name else "")


def workflow_options(packs: list, default, refs: bool = False) -> dict[str, dict]:
    """`x-options` for a task tool's `workflow` (plan 20.3): what each pack is, takes and is good for."""
    out = {}
    for p in packs:
        m = p.manifest
        o: dict[str, Any] = {"label": p.name}
        if _summary(p):
            o["good_for"] = _summary(p)
        if m.speed:
            o["speed"] = m.speed
        if m.edit:
            o["kind"] = m.edit
        if "mask" in m.inputs:
            o["needs"] = ["mask"]
        if refs and not references(p):          # the tool takes references, but this pack can't use them
            o["excludes"] = ["references"]
        if p is default:
            o["default"] = True
        o["allows"] = {"preset": list(m.presets)}
        out[p.id] = o
    return out


def preset_options(packs: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in packs:
        for name, vals in p.manifest.presets.items():
            if name in out:
                continue
            q = p.manifest.preset_quality(name)
            o: dict[str, Any] = {"label": str(vals.get("label") or name.replace("_", " ").capitalize()), "quality": q}
            if q != "full":
                o["when"] = QUICK
            out[name] = o
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
                    q["description"] = task.notes.get(k) or shared.get("description") or v.get("description", "")
                    if shared.get("choices"):      # one list for every pack (each pack's own labels are matched by ratio)
                        q["enum"] = list(shared["choices"])
                    if k == "seed":
                        q["minimum"] = -1
                    props[k] = q
        styles = sorted({p.manifest.edit for p in packs if p.manifest.edit})
        default = default_for(tid, packs, defaults, "instruction" if len(styles) > 1 else None)
        refs = max((references(p) for p in packs), default=0)
        if refs:
            props["references"] = {"type": "array", "items": {"type": "string", "format": "gaifa-file"}, "maxItems": refs,
                                   "description": lib.tasks.inputs.get("references", {}).get("description", "Extra pictures")}
        if len(styles) > 1:                     # more than one kind of edit is ready: the caller says which
            props["edit"] = {"type": "string", "enum": styles, "description": "What kind of edit (default: instruction)",
                             "x-options": {st: {"label": st.capitalize(), "default": st == "instruction",
                                                "allows": {"workflow": sorted(p.id for p in packs if p.manifest.edit == st)}}
                                           for st in styles}}
        props["workflow"] = {"type": "string", "enum": sorted(p.id for p in packs),
                             "description": "Which workflow to use", "x-options": workflow_options(packs, default, bool(refs))}
        if len(styles) > 1:
            props["workflow"]["x-depends-on"] = "edit"
        presets = sorted({name for p in packs for name in p.manifest.presets})
        if presets:
            props["preset"] = {"type": "string", "enum": presets, "x-depends-on": "workflow", "x-options": preset_options(packs),
                               "description": "Leave it out for full quality (the default). A quick preset only when the user asks "
                                              "for a quick, rough, draft or preview result."}
        lines = [task.description, "Returns a job; its outputs (files) come when it finishes."]
        req = [r for r in task.required if r in props]
        tools.append(_fn(task.tool, "\n".join(lines), {"type": "object", "properties": props, "required": req,
                                                     "additionalProperties": False}))
    all_ready = sorted(p.id for ps in by_task.values() for p in ps)
    every = {p.id: p for ps in by_task.values() for p in ps}
    lw = _fn("list_workflows", "List the image and video workflows, with their tasks and inputs.",
             {"type": "object", "properties": {}}, job=False, risk="read")
    lw["view"] = {"kind": "table", "rows": "workflows", "columns": [{"key": "name", "label": "Workflow"}, {"key": "task", "label": "Task"},
                                                                  {"key": "presets", "label": "Presets", "format": "list"},
                                                                  {"key": "description", "label": "What it's for"}]}   # plan 46.4: drawn as a table in Chat
    tools.append(lw)
    tools.append(_fn("run_workflow", "Run a workflow by id with its own inputs (see list_workflows). Only for workflows the "
                     "task tools don't cover: for images, edits, animation, video and background removal use generate_image, "
                     "edit_image, animate_image, generate_video and remove_background (they take a `workflow` too).",
                     {"type": "object", "properties": {
                         "workflow": {"type": "string", "enum": all_ready, "x-options": {
                             pid: {"label": p.name, "kind": p.task, **({"good_for": _summary(p)} if _summary(p) else {})}
                             for pid, p in every.items()}},
                         "inputs": {"type": "object", "description": "The workflow's inputs by name"},
                         "preset": {"type": "string", "description": "One of the workflow's presets"}},
                      "required": ["workflow"], "additionalProperties": False}))
    return tools


def pick(lib: Library, task_id: str, workflow: str | None, defaults: dict[str, str], style: str | None = None):
    lib.packs.scan()                            # a pack added since the tool list was read
    by_task = ready_by_task(lib)
    packs = by_task.get(task_id, [])
    if style is None and len({p.manifest.edit for p in packs if p.manifest.edit}) > 1:
        style = "instruction" if not workflow else None   # the `edit` parameter's default
    if workflow:
        p = next((p for p in packs if p.id == workflow), None)
        if p is None:
            other = next((x for ps in by_task.values() for x in ps if x.id == workflow), None)
            tool = lib.tasks.get(other.task).tool if other and lib.tasks.get(other.task) else None
            if other and tool:                  # a pack of another task: say which tool runs it
                raise ValueError(f"{workflow!r} is {'an' if other.task[0] in 'aeiou' else 'a'} {other.task} workflow, not {task_id}: call {tool} for it, or use one of: "
                                 f"{', '.join(x.id for x in packs) or 'none'}")
            raise ValueError(f"{workflow!r} isn't a ready {task_id} workflow (have: {', '.join(x.id for x in packs) or 'none'})")
        if style and p.manifest.edit != style:
            raise ValueError(f"{workflow!r} is a {p.manifest.edit} edit, not {style}")
        return p
    p = default_for(task_id, packs, defaults, style)
    if p is None:
        raise ValueError(f"choose a workflow for {task_id}: {', '.join(x.id for x in packs if not style or x.manifest.edit == style) or 'none is ready'}")
    return p


def list_workflows(lib: Library) -> list[dict]:
    out = []
    for ps in ready_by_task(lib).values():
        for p in ps:
            conv, _ = lib.analysed(p)
            sch = input_schema(p, conv, lib.catalog, lib.tasks)
            out.append({"id": p.id, "name": p.name, "task": p.task, "description": p.manifest.description,
                        "inputs": {k: v.get("type") for k, v in sch["properties"].items()},
                        "required": sch.get("required", []), "presets": list(p.manifest.presets),
                        **({"edit": p.manifest.edit} if p.manifest.edit else {}), **({"references": references(p)} if references(p) else {})})
    return sorted(out, key=lambda w: (w["task"], w["id"]))
