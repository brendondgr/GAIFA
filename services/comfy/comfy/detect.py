"""Drafting a pack's workflow.toml from its graph (plan 11.6): which fields a person would want to
set, named with the shared input names, plus the outputs, a task guess and a memory estimate.

The rules follow the wires rather than node names where they can:
- **prompt / negative:** from each sampler's `positive` / `negative` input upstream to the first
  node with a typed text field (through ZeroOut, guidance, reference-latent and similar nodes). A
  negative that ends in a ZeroOut is not an input. A later stage with a different text is `prompt_2`.
- **seed, steps, cfg, strength:** on the first stage's sampler (or the RandomNoise / scheduler /
  guider nodes it uses). Other stages' seeds follow the same value (`also`).
- **width / height / frames:** on the node that makes the empty latent; other nodes with the same
  numbers (an input-image resize) follow it.
- **image / mask:** LoadImage nodes (`image`, `image_2`, …); a LoadImageMask, or a LoadImage whose
  mask output is used, is `mask`.
- **fps:** on the video-making node. **outputs:** every save node (previews only if nothing saves).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .check import FILE_EXTS
from .convert import Converted
from .nodes import NodeCatalog

PASS_THROUGH = re.compile(r"ZeroOut|Guidance|ReferenceLatent|CFGNorm|Conditioning(?!Zero)|ControlNetApply|Inpaint|Average|Combine",
                          re.I)
TEXT_FIELDS = ("text", "prompt", "positive", "text_g", "text_l", "t5xxl", "clip_l")
SEED_FIELDS = ("seed", "noise_seed")
FRAME_FIELDS = ("length", "frames", "num_frames", "video_length", "frame_count")
FPS_FIELDS = ("fps", "frame_rate")
VIDEO_SAVE = re.compile(r"Video|Animated|GIF|WEBM|MP4", re.I)
AUDIO_SAVE = re.compile(r"Audio", re.I)
MESH_SAVE = re.compile(r"3D|GLB|Mesh", re.I)
SKIP_OUTPUTS = re.compile(r"Preview|ImageCompare|Display|Show", re.I)


@dataclass
class Suggestion:
    manifest: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    why: dict[str, str] = field(default_factory=dict)        # input name → which node, for the comments


class _Graph:
    def __init__(self, conv: Converted, catalog: NodeCatalog):
        self.g, self.cat, self.titles = conv.graph, catalog, conv.titles
        self.consumers: dict[str, list[tuple[str, str, int]]] = {}
        for eid, n in self.g.items():
            for name, v in n["inputs"].items():
                if isinstance(v, list) and len(v) == 2 and str(v[0]) in self.g:
                    self.consumers.setdefault(str(v[0]), []).append((eid, name, int(v[1])))

    def cls(self, eid: str) -> str:
        return self.g[eid]["class_type"]

    def inputs(self, eid: str) -> dict:
        return self.g[eid]["inputs"]

    def src(self, eid: str, name: str) -> str | None:
        v = self.inputs(eid).get(name)
        return str(v[0]) if isinstance(v, list) and len(v) == 2 and str(v[0]) in self.g else None

    def literal(self, eid: str, name: str) -> bool:
        return name in self.inputs(eid) and not isinstance(self.inputs(eid)[name], list)

    def order(self) -> list[str]:
        """Exec ids sorted upstream-first (a node before the nodes that use it)."""
        seen: dict[str, int] = {}

        def depth(e: str, stack: frozenset = frozenset()) -> int:
            if e in seen:
                return seen[e]
            if e in stack:
                return 0
            ups = [self.src(e, k) for k in self.inputs(e)]
            d = 1 + max((depth(u, stack | {e}) for u in ups if u), default=-1)
            seen[e] = d
            return d
        return sorted(self.g, key=lambda e: (depth(e), _num(e)))

    def string_field(self, eid: str) -> str | None:
        """The typed-text field of a node: a literal multiline STRING (or a known text name)."""
        t = self.cls(eid)
        for name in TEXT_FIELDS:
            if self.literal(eid, name) and isinstance(self.inputs(eid)[name], str):
                spec = self.cat.input(t, name)
                if spec is None or spec.type == "STRING":
                    return name
        for name, v in self.inputs(eid).items():
            spec = self.cat.input(t, name)
            if spec and spec.type == "STRING" and spec.options.get("multiline") and isinstance(v, str):
                return name
        return None

    def text_source(self, eid: str, field_name: str) -> tuple[str, str]:
        """A text field fed by a string node (a primitive) is set on that node instead."""
        up = self.src(eid, field_name)
        if up:
            for name, v in self.inputs(up).items():
                if isinstance(v, str) and (self.cat.input(self.cls(up), name) or None) is not None:
                    return up, name
        return eid, field_name


def _num(e: str) -> list:
    return [int(x) if x.isdigit() else 0 for x in e.split(":")]


def _trace_text(gr: _Graph, start: str | None, depth: int = 0) -> tuple[str, str] | None | str:
    """From a conditioning input upstream to the node holding the text. "zero" when it's zeroed."""
    if start is None or depth > 12:
        return None
    t = gr.cls(start)
    if "ZeroOut" in t:
        return "zero"
    f = gr.string_field(start)
    if f:
        return gr.text_source(start, f)
    if f is None and any(k in gr.inputs(start) for k in TEXT_FIELDS) and not PASS_THROUGH.search(t):
        k = next(k for k in TEXT_FIELDS if k in gr.inputs(start))
        if gr.src(start, k):
            return gr.text_source(start, k)
    for name in ("conditioning", "positive", "conditioning_1", "conditioning_to", "cond", "conditioning_from"):
        up = gr.src(start, name)
        if up:
            return _trace_text(gr, up, depth + 1)
    ups = [gr.src(start, k) for k in gr.inputs(start)]
    ups = [u for u in ups if u and "CONDITIONING" in gr.cat.outputs(gr.cls(u))]
    return _trace_text(gr, ups[0], depth + 1) if ups else None


def _samplers(gr: _Graph) -> list[str]:
    """Nodes that take positive/negative conditioning (KSampler, CFGGuider, …), first stage first."""
    def takes(e: str, k: str) -> bool:
        return isinstance(gr.inputs(e).get(k), list)
    found = [e for e in gr.order() if takes(e, "positive") and takes(e, "model")]   # not WanImageToVideo & co
    if not found:
        found = [e for e in gr.order() if takes(e, "positive")]
    if not found:
        found = [e for e in gr.order() if takes(e, "conditioning") and "Guider" in gr.cls(e)]
    return found


def _sampler_field(gr: _Graph, sampler: str, names: tuple[str, ...], hops: int = 2) -> tuple[str, str] | None:
    """A literal field on the sampler, or on a node it uses (RandomNoise, a scheduler, a guider).
    A guider (CFGGuider) is used by a SamplerCustom node, whose noise and sigmas hold the seed and
    steps, so the search starts from the guider's users too."""
    starts = [sampler] + [c for c, _, _ in gr.consumers.get(sampler, []) if "GUIDER" in gr.cat.outputs(gr.cls(sampler))]
    todo, seen = [(e, 0) for e in starts], set()
    while todo:
        e, d = todo.pop(0)
        if e in seen:
            continue
        seen.add(e)
        for n in names:
            if gr.literal(e, n):
                return e, n
            up = gr.src(e, n)
            if up and len(gr.inputs(up)) == 1 and gr.literal(up, next(iter(gr.inputs(up)))):
                return up, next(iter(gr.inputs(up)))      # a primitive int node feeding it
        if d < hops:
            todo += [(u, d + 1) for u in (gr.src(e, k) for k in gr.inputs(e)) if u]
    return None


def suggest(conv: Converted, catalog: NodeCatalog, editor: dict | None = None, name: str = "",
            model_sizes: dict[str, int] | None = None) -> Suggestion:
    gr = _Graph(conv, catalog)
    inputs: dict[str, dict] = {}
    why: dict[str, str] = {}
    notes: list[str] = []

    def put(key: str, eid: str, fld: str, **extra) -> None:
        inputs[key] = {"node": eid, "field": fld, **extra}
        why[key] = f'{gr.cls(eid)} "{gr.titles.get(eid, gr.cls(eid))}"'

    # ---- prompts --------------------------------------------------------------------------
    samplers = _samplers(gr)
    prompts: list[tuple[str, str]] = []
    for s in samplers:
        pos = _trace_text(gr, gr.src(s, "positive") or gr.src(s, "conditioning"))
        if isinstance(pos, tuple) and pos not in prompts:
            text = gr.inputs(pos[0]).get(pos[1])
            same = next((p for p in prompts if gr.inputs(p[0]).get(p[1]) == text), None)
            if same:
                key = next(k for k, v in inputs.items() if (v["node"], v["field"]) == same)
                inputs[key].setdefault("also", []).append(f"{pos[0]}.{pos[1]}")
            else:
                prompts.append(pos)
                put("prompt" if len(prompts) == 1 else f"prompt_{len(prompts)}", *pos)
        neg = _trace_text(gr, gr.src(s, "negative"))
        if isinstance(neg, tuple) and neg not in prompts and "negative" not in inputs:
            if (neg[0], neg[1]) != (inputs.get("prompt") or {}).get("node"):
                put("negative", *neg)
    if not samplers:
        notes.append("no sampler with positive/negative inputs: prompts weren't detected")

    # ---- sampler settings (first stage) ---------------------------------------------------
    if samplers:
        first = samplers[0]
        for key, names in (("seed", SEED_FIELDS), ("steps", ("steps",)), ("cfg", ("cfg",))):
            hit = _sampler_field(gr, first, names)
            if hit:
                put(key, *hit, **({"default": -1} if key == "seed" else {}))
        seeds = [_sampler_field(gr, s, SEED_FIELDS) for s in samplers[1:]]
        for h in seeds:
            if h and "seed" in inputs and (h[0], h[1]) != (inputs["seed"]["node"], inputs["seed"]["field"]):
                inputs["seed"].setdefault("also", []).append(f"{h[0]}.{h[1]}")
        for s in samplers:
            lat = gr.src(s, "latent_image") or gr.src(s, "latent")
            d = gr.inputs(s).get("denoise")
            if isinstance(d, (int, float)) and d < 1 and lat and "Encode" in gr.cls(lat) and "strength" not in inputs:
                put("strength", s, "denoise")

    # ---- size and frames --------------------------------------------------------------------
    sized = [e for e in gr.order() if gr.literal(e, "width") and gr.literal(e, "height")
             and isinstance(gr.inputs(e)["width"], int)]
    latents = [e for e in sized if "LATENT" in catalog.outputs(gr.cls(e)) or "Latent" in gr.cls(e)]
    main = (latents or sized or [None])[0]
    if main:
        w, h = gr.inputs(main)["width"], gr.inputs(main)["height"]
        put("width", main, "width")
        put("height", main, "height")
        for e in sized:
            if e != main and gr.inputs(e)["width"] == w and gr.inputs(e)["height"] == h:
                inputs["width"].setdefault("also", []).append(f"{e}.width")
                inputs["height"].setdefault("also", []).append(f"{e}.height")
    for e in ([main] if main else []) + [x for x in gr.order() if x != main]:
        hit = next((f for f in FRAME_FIELDS if gr.literal(e, f) and isinstance(gr.inputs(e)[f], int)), None)
        if hit and "frames" not in inputs and ("Latent" in gr.cls(e) or "Video" in gr.cls(e)):
            put("frames", e, hit)
    for e in gr.order():
        hit = next((f for f in FPS_FIELDS if gr.literal(e, f)), None)
        if hit and ("Video" in gr.cls(e) or "Animated" in gr.cls(e)):
            put("fps", e, hit)
            break

    # ---- images and masks -----------------------------------------------------------------
    n_img = 0
    for e in gr.order():
        t = gr.cls(e)
        if t == "LoadImageMask" and "mask" not in inputs:
            put("mask", e, "image")
            continue
        if t in ("LoadImage", "LoadImageOutput") or (catalog.input(t, "image") and catalog.input(t, "image").options.get("image_upload")):
            uses = gr.consumers.get(e, [])
            if uses and all(slot == 1 for _, _, slot in uses) and "mask" not in inputs:
                put("mask", e, "image")                    # only its MASK output is used
                continue
            n_img += 1
            put("image" if n_img == 1 else f"image_{n_img}", e, "image")

    # ---- outputs ----------------------------------------------------------------------------
    outs: dict[str, dict] = {}
    saves = [e for e in gr.order() if catalog.is_output(gr.cls(e)) and not SKIP_OUTPUTS.search(gr.cls(e))]
    if not saves:
        saves = [e for e in gr.order() if catalog.is_output(gr.cls(e)) and "Preview" in gr.cls(e)]
    for e in saves:
        t = gr.cls(e)
        kind = "video" if VIDEO_SAVE.search(t) else "audio" if AUDIO_SAVE.search(t) else "mesh" if MESH_SAVE.search(t) else "image"
        n = sum(1 for o in outs.values() if o["kind"] == kind)
        outs[kind if n == 0 else f"{kind}_{n + 1}"] = {"node": e, "kind": kind}

    # ---- task, memory, words ----------------------------------------------------------------
    kinds = {o["kind"] for o in outs.values()}
    has_img, has_prompt = "image" in inputs, "prompt" in inputs
    types = " ".join(gr.cls(e) for e in gr.g)
    if "video" in kinds:
        task = "image-to-video" if has_img else "text-to-video"
    elif "image" in kinds and has_img and has_prompt:
        task = "image-edit"
    elif "image" in kinds and has_img and re.search(r"Background|RMBG|Matting", types, re.I):
        task = "remove-background"
    elif "image" in kinds and has_img and re.search(r"Upscale", types):
        task = "upscale"
    elif "image" in kinds and has_prompt:
        task = "text-to-image"
    else:
        task = "custom"
    desc = _description(editor)
    manifest: dict[str, Any] = {"name": desc or name.replace("-", " ").replace("_", " ").strip().capitalize(), "task": task}
    mem = memory_estimate(conv, catalog, model_sizes or {})
    if mem:
        manifest["memory_gb"] = mem
    manifest["inputs"] = inputs
    manifest["outputs"] = outs
    if not outs:
        notes.append("no save node found: add one (Save Image, Save Video) so results are kept")
    return Suggestion(manifest, notes, why)


NOT_A_TITLE = ("status", "note", "tip", "http", "how to", "warning", "todo", "usage")


def _description(editor: dict | None) -> str:
    """The workflow's title from its notes: the first heading that isn't a status or tip line."""
    for n in (editor or {}).get("nodes") or []:
        if n.get("type") in ("MarkdownNote", "Note") and n.get("widgets_values"):
            for line in str(n["widgets_values"][0]).splitlines():
                if not re.match(r"^\s*#\s", line):            # top-level headings only
                    continue
                line = re.sub(r"[#*_`>]+", "", line).strip()
                if len(line) > 6 and line[0].isalnum() and not line.lower().startswith(NOT_A_TITLE):
                    return line[:120]
    return ""


def memory_estimate(conv: Converted, catalog: NodeCatalog, sizes: dict[str, int]) -> float | None:
    """The model files the graph loads, × 1.2 for activations, in GB (one decimal)."""
    total, seen = 0, set()
    for n in conv.graph.values():
        for name, v in n["inputs"].items():
            if isinstance(v, str) and v.lower().endswith(FILE_EXTS) and v not in seen:
                seen.add(v)
                total += sizes.get(v.rsplit("/", 1)[-1], 0)
    return round(total * 1.2 / 1e9, 1) if total else None


def model_sizes(models_dir: Path | None) -> dict[str, int]:
    out: dict[str, int] = {}
    if models_dir and models_dir.is_dir():
        for p in models_dir.rglob("*"):
            if p.suffix.lower() in FILE_EXTS:
                try:
                    out[p.name] = p.stat().st_size
                except OSError:
                    pass
    return out


def to_toml(s: Suggestion, estimate: bool = True) -> str:
    """workflow.toml text, with a comment naming each input's node. A suggested memory_gb is an
    estimate, written as a comment so it doesn't pin the amount (runs measure it)."""
    m = s.manifest
    lines = [f'name = {_q(m.get("name", ""))}', f'task = {_q(m.get("task", "custom"))}']
    if m.get("description"):
        lines.append(f'description = {_q(m["description"])}')
    if m.get("tags"):
        lines.append(f'tags = {_v(m["tags"])}')
    if m.get("memory_gb") and estimate:
        lines.append(f'# memory_gb = {m["memory_gb"]}    # estimated from the model files; each run measures it, so set it only to override')
    elif m.get("memory_gb"):
        lines.append(f'memory_gb = {m["memory_gb"]}')
    for key, v in m.get("inputs", {}).items():
        lines += ["", f"[inputs.{key}]" + (f"          # {s.why[key]}" if key in s.why else "")]
        lines += [f"{k} = {_v(x)}" for k, x in v.items()]
    for key, v in m.get("outputs", {}).items():
        lines += ["", f"[outputs.{key}]"] + [f"{k} = {_v(x)}" for k, x in v.items()]
    for key, v in (m.get("presets") or {}).items():
        lines += ["", f"[presets.{key}]"] + [f"{k} = {_v(x)}" for k, x in v.items()]
    if m.get("set"):
        lines += ["", "[set]"] + [f"{_q(k)} = {_v(x)}" for k, x in m["set"].items()]
    return "\n".join(lines) + "\n"


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _v(x: Any) -> str:
    if x is None:
        return '""'
    if isinstance(x, dict):
        return "{ " + ", ".join(f"{_q(k)} = {_v(v)}" for k, v in x.items()) + " }"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, list):
        return "[" + ", ".join(_v(i) for i in x) + "]"
    return _q(x)
