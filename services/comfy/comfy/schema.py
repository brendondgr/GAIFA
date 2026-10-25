"""A pack's inputs as JSON Schema (the Run form, the API, the agent's tools). Types, defaults and
ranges come from the node catalog and the graph; workflow.toml overrides any of them."""

from __future__ import annotations

from typing import Any

from .check import locate
from .convert import Converted
from .nodes import NodeCatalog
from .packs import Pack
from .tasks import Tasks

JSON_TYPES = {"INT": "integer", "FLOAT": "number", "STRING": "string", "BOOLEAN": "boolean", "COMBO": "string"}
FILE_LOADERS = {"LoadImage", "LoadImageMask", "LoadVideo", "LoadAudio", "VHS_LoadVideo", "VHS_LoadVideoPath"}
FILE = {"type": "string", "format": "gaifa-file",
        "description": "A GAIFA output id (output:<id>), an uploaded file name, or a URL path under /api/outputs/"}


def input_schema(pack: Pack, conv: Converted | None, catalog: NodeCatalog, tasks: Tasks) -> dict:
    m = pack.manifest
    props: dict[str, Any] = {}
    required: list[str] = []
    if m is None:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    task = tasks.get(m.task)
    for name, im in m.inputs.items():
        if im.hidden:
            continue
        shared = tasks.inputs.get(name) or {}
        eid = locate(conv, im.node, im.title)[0] if conv else None
        node = conv.graph.get(eid) if conv and eid else None
        cls = node["class_type"] if node else None
        spec = catalog.input(cls, im.field) if cls and catalog.has(cls) else None
        current = node["inputs"].get(im.field) if node else None
        kind = im.type or shared.get("type") or (
            "file" if cls in FILE_LOADERS or (spec and spec.options.get("image_upload")) else
            JSON_TYPES.get(spec.type) if spec else None) or "string"
        if kind == "file":
            p: dict[str, Any] = dict(FILE)
            if name.startswith("video") or (cls and "Video" in cls):
                p["x-kind"] = "video"
        elif kind == "files":
            p = {"type": "array", "items": dict(FILE)}
        else:
            p = {"type": kind}
            choices = im.choices or (spec.choices if spec and spec.type == "COMBO" else None)
            if choices and kind == "string":
                p["enum"] = list(choices)
            lo = im.min if im.min is not None else (spec.options.get("min") if spec else None)
            hi = im.max if im.max is not None else (spec.options.get("max") if spec else None)
            if kind in ("integer", "number"):
                if lo is not None:
                    p["minimum"] = lo
                if hi is not None and hi < 2**53:
                    p["maximum"] = hi
                st = im.step if im.step is not None else (spec.options.get("step") if spec else None)
                if st:
                    p["x-step"] = st                   # a UI hint; multipleOf misfires on floats
            if name == "seed":
                p["minimum"] = -1
            if im.multiline or (spec and spec.options.get("multiline")):
                p["x-multiline"] = True
        default = im.default if im.default is not None else (current if not isinstance(current, list) else None)
        if name == "seed" and im.default is None:
            default = -1
        if default is not None and kind not in ("file", "files"):
            p["default"] = default
        p["title"] = im.label or name.replace("_", " ").capitalize()
        desc = im.description or shared.get("description") or (spec.options.get("tooltip") if spec else None)
        if desc:
            p["description"] = desc
        props[name] = p
        if im.required or (task and name in task.required) or (kind in ("file", "files") and im.required is not False):
            required.append(name)
    names = set(m.inputs)
    if {"width", "height"} <= names and "aspect" not in names:
        a = tasks.inputs.get("aspect") or {}
        props["aspect"] = {"type": "string", "title": "Aspect", "enum": a.get("choices") or ["1:1"], "description": a.get("description", "")}
        props["megapixels"] = {"type": "number", "title": "Megapixels", "minimum": 0.1, "maximum": 4, "default": 1.0,
                               "description": (tasks.inputs.get("megapixels") or {}).get("description", "")}
    if "resolution" in names and not names & {"megapixels", "width"}:      # a square working size (Qwen-Image 2.1's encoder)
        props["megapixels"] = {"type": "number", "title": "Megapixels", "minimum": 0.1, "maximum": 4,
                               "description": "Result size in megapixels (1.0 = 1024×1024); sets the working size. "
                                              "Smaller is faster and keeps less detail."}
    if "frames" in names and "seconds" not in names:
        props["seconds"] = {"type": "number", "title": "Seconds", "minimum": 0.5, "maximum": 30,
                            "description": (tasks.inputs.get("seconds") or {}).get("description", "")}
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = sorted(set(required), key=list(props).index)
    return out
