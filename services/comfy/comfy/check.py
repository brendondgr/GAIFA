"""Checking a pack against what's installed (plan 11.5): it converts, its nodes exist, the files
its loaders name are present, its inputs point at real fields, and it fits its task."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .convert import Converted, ConvertError, to_api
from .nodes import NodeCatalog
from .packs import Pack
from .tasks import Tasks

FILE_EXTS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".onnx", ".sft")
INPUT_LOADERS = {"LoadImage", "LoadImageMask", "LoadVideo", "LoadAudio", "LoadImageOutput"}
# Which models/ folder a loader's file goes in (by input name; a few loaders differ by class).
FOLDERS = {"unet_name": "diffusion_models", "clip_name": "text_encoders", "clip_name1": "text_encoders",
           "clip_name2": "text_encoders", "vae_name": "vae", "lora_name": "loras", "ckpt_name": "checkpoints",
           "model_name": "upscale_models", "control_net_name": "controlnet", "style_model_name": "style_models"}
FOLDERS_BY_CLASS = {"CLIPVisionLoader": "clip_vision", "UnetLoaderGGUF": "unet"}


@dataclass
class Issue:
    level: str                      # error | warning | info
    code: str
    detail: str
    node: str | None = None
    fix: str | None = None
    data: dict | None = None

    def json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def locate(conv: Converted, node: str | None, title: str | None) -> tuple[str | None, str | None]:
    """The exec id an input or output points at, or (None, why)."""
    if node is not None:
        return (str(node), None) if str(node) in conv.graph else (None, f"node {node} isn't in the graph")
    hits = [k for k, t in conv.titles.items() if t == title and k in conv.graph]
    if len(hits) == 1:
        return hits[0], None
    return None, (f"no node is titled {title!r}" if not hits else f"{len(hits)} nodes are titled {title!r}; use node = \"<id>\"")


def _packages(editor: dict | None) -> dict[str, str]:
    """Node type → the custom-node package the editor recorded for it (cnr_id or aux_id)."""
    out: dict[str, str] = {}
    if not editor:
        return out
    nodes = list(editor.get("nodes") or [])
    for sg in (editor.get("definitions") or {}).get("subgraphs") or []:
        nodes += sg.get("nodes") or []
    for n in nodes:
        props = n.get("properties") or {}
        pkg = props.get("cnr_id") or props.get("aux_id")
        if pkg and pkg != "comfy-core" and n.get("type"):
            out.setdefault(n["type"], pkg)
    return out


def _model_urls(editor: dict | None) -> dict[str, dict]:
    """File name → {url, directory} from nodes' `properties.models` (official templates have them)."""
    out: dict[str, dict] = {}
    if not editor:
        return out
    nodes = list(editor.get("nodes") or [])
    for sg in (editor.get("definitions") or {}).get("subgraphs") or []:
        nodes += sg.get("nodes") or []
    for n in nodes:
        for m in (n.get("properties") or {}).get("models") or []:
            if isinstance(m, dict) and m.get("name"):
                out[m["name"]] = {k: m[k] for k in ("url", "directory") if m.get(k)}
    for m in (editor.get("models") or []):
        if isinstance(m, dict) and m.get("name"):
            out.setdefault(m["name"], {k: m[k] for k in ("url", "directory") if m.get(k)})
    return out


def convert(pack: Pack, catalog: NodeCatalog) -> tuple[Converted | None, list[Issue]]:
    try:
        return to_api(pack.load_graph(), catalog), []
    except ConvertError as e:
        return None, [Issue("error", "convert_failed", e.reason, node=e.node,
                            fix="Save the workflow in ComfyUI, or add an exact API graph as workflow.api.json "
                                "(run it once in ComfyUI and import it from history).")]
    except (OSError, ValueError) as e:
        return None, [Issue("error", "unreadable", f"{type(e).__name__}: {e}")]


def check(pack: Pack, catalog: NodeCatalog, tasks: Tasks, models: dict[str, dict] | None = None,
          conv: Converted | None = None) -> list[Issue]:
    """Every problem with a pack, worst first. `models` maps file names to registry entries
    ({id, source}) when the caller knows them."""
    issues = [Issue("error", "manifest", e) for e in pack.errors]
    if conv is None:
        conv, errs = convert(pack, catalog)
        issues += errs
    if conv is None:
        return issues
    editor = pack.editor()
    pkgs, urls = _packages(editor), _model_urls(editor)
    assets = {p.name for p in pack.assets.iterdir()} if pack.assets else set()
    mapped = _mapped(pack, conv)

    for eid, t in sorted(conv.missing.items()):
        pkg = pkgs.get(t)
        issues.append(Issue("error", "missing_node", f"node type {t!r} isn't installed", node=eid,
                            fix=f"Install the custom-node package {pkg!r} with ComfyUI-Manager, then reload comfy."
                            if pkg else "Find the custom-node package that provides it and install it with ComfyUI-Manager.",
                            data={"type": t, "package": pkg}))
    for eid, n in conv.graph.items():
        t = n["class_type"]
        if not catalog.has(t):
            continue
        for name, value in n["inputs"].items():
            spec = catalog.input(t, name)
            if spec is None or spec.type != "COMBO" or isinstance(value, list) or not isinstance(value, str):
                continue
            if spec.choices is None or value in spec.choices or (eid, name) in mapped:
                continue
            if t in INPUT_LOADERS or spec.options.get("image_upload"):
                if value.rsplit("/", 1)[-1] in assets:
                    continue
                issues.append(Issue("warning", "missing_input_file", f"{t}.{name} loads {value!r}, which isn't in ComfyUI's input folder",
                                    node=eid, fix="Map it as a pack input (image), or put the file in the pack's assets/ folder."))
            elif value.lower().endswith(FILE_EXTS):
                hit = (models or {}).get(value.rsplit("/", 1)[-1])
                src = urls.get(value.rsplit("/", 1)[-1])
                folder = (src or {}).get("directory") or FOLDERS_BY_CLASS.get(t) or FOLDERS.get(name) or "<folder>"
                fix = ("Download it" + (f" from {src['url']}" if src and src.get("url") else "") +
                       f" into data/models/comfyui/{folder}/, or pick a file you have.")
                issues.append(Issue("error", "missing_model", f"{t}.{name}: {value!r} isn't in ComfyUI's model folders", node=eid,
                                    fix=fix, data={"file": value, "input": name, "url": (src or {}).get("url"),
                                                   "directory": folder, "registry": hit}))
            else:
                issues.append(Issue("warning", "invalid_choice", f"{t}.{name} = {value!r} isn't one of its options now", node=eid,
                                    fix=f"Pick one of: {', '.join(map(str, spec.choices[:8]))}"))
    if not any(catalog.is_output(n["class_type"]) or not catalog.has(n["class_type"]) for n in conv.graph.values()):
        issues.append(Issue("error", "no_output", "the graph has no output node (Save Image, Save Video, …)"))
    if pack.manifest is not None:
        issues += _check_manifest(pack, conv, catalog, tasks)
    for eid in conv.broadcast:
        issues.append(Issue("error", "editor_links", f"node {eid} broadcasts values to other nodes' inputs (Anything Everywhere): "
                            "those links exist only in ComfyUI's editor", node=eid,
                            fix="Run it once in ComfyUI and import it from history (the exact graph has the links), "
                                "or connect those inputs directly and save."))
    for n in conv.notes:
        issues.append(Issue("info", "left_out", f"{n['type']}: {n['detail']}", node=n["node"]))
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(issues, key=lambda i: order[i.level])


def _mapped(pack: Pack, conv: Converted) -> set[tuple[str, str]]:
    out = set()
    if pack.manifest:
        for m in pack.manifest.inputs.values():
            eid, _ = locate(conv, m.node, m.title)
            if eid:
                out.add((eid, m.field))
    return out


def _check_manifest(pack: Pack, conv: Converted, catalog: NodeCatalog, tasks: Tasks) -> list[Issue]:
    m = pack.manifest
    out: list[Issue] = []
    task = tasks.get(m.task)
    if task is None:
        out.append(Issue("error", "unknown_task", f"task {m.task!r} isn't in tasks.toml",
                         fix=f"Use one of: {', '.join(sorted(tasks.tasks))}"))
    for name, im in m.inputs.items():
        eid, why = locate(conv, im.node, im.title)
        if eid is None:
            out.append(Issue("error", "input_unmapped", f"input {name!r}: {why}",
                             fix="Point it at a node that exists (comfyui workflows show <id> lists them)."))
            continue
        cls = conv.graph[eid]["class_type"]
        if catalog.has(cls) and catalog.input(cls, im.field) is None and im.field not in conv.graph[eid]["inputs"]:
            out.append(Issue("error", "input_unmapped", f"input {name!r}: {cls} (node {eid}) has no field {im.field!r}", node=eid))
        for extra in im.also:
            node_id, _, fld = extra.partition(".")          # node ids have no dots; fields may
            if node_id not in conv.graph:
                out.append(Issue("error", "input_unmapped", f"input {name!r}: also-target node {node_id} isn't in the graph"))
    for name, om in m.outputs.items():
        eid, why = locate(conv, om.node, om.title)
        if eid is None:
            out.append(Issue("error", "output_unmapped", f"output {name!r}: {why}"))
    if task is not None:
        have = set(m.inputs) | ({"aspect"} if {"width", "height"} <= set(m.inputs) else set())
        for need in task.required:
            if need not in have:
                out.append(Issue("error", "task_input_missing", f"task {task.id} needs an input named {need!r}",
                                 fix=f"Map {need!r} in workflow.toml, or choose another task."))
    return out


def summary(issues: list[Issue]) -> dict[str, Any]:
    return {"ok": not any(i.level == "error" for i in issues),
            "errors": sum(i.level == "error" for i in issues), "warnings": sum(i.level == "warning" for i in issues)}
