"""From a caller's inputs to a patched graph (plan 11.7): defaults, presets, validation, the
derived inputs (aspect + megapixels → width/height, megapixels → a square resolution, seconds → frames), random seeds, and setting
each value on its node field."""

from __future__ import annotations

import copy
import math
import random
import re
from datetime import datetime
from typing import Any

from .check import locate
from .convert import Converted
from .nodes import NodeCatalog
from .packs import Pack

DERIVED = ("aspect", "megapixels", "seconds")
TEMPLATE_WORDS = 8   # a value up to this many words, not naming <image…>, goes into its input's template; longer text is used as it is
SEED_MAX = 2**32 - 1


class InputError(Exception):
    def __init__(self, detail: str, errors: list[str] | None = None):
        super().__init__(detail)
        self.detail, self.errors = detail, errors or [detail]


def split_target(t: str) -> tuple[str, str]:
    """"<node>.<field>": node ids never contain dots, fields may (`format.codec`)."""
    node, _, fld = t.partition(".")
    return node, fld


def _coerce(name: str, v: Any, p: dict, errors: list[str]) -> Any:
    t = p.get("type")
    try:
        if t == "integer":
            if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
                raise ValueError
            v = int(v)
        elif t == "number":
            if isinstance(v, bool):
                raise ValueError
            v = float(v) if not isinstance(v, int) else v
        elif t == "boolean":
            if isinstance(v, str):
                v = v.lower() in ("1", "true", "yes", "on")
            v = bool(v)
        elif t == "string":
            if not isinstance(v, str):
                v = str(v)
        elif t == "array" and not isinstance(v, list):
            v = [v]
    except (TypeError, ValueError):
        errors.append(f"{name}: expected {t}, got {v!r}")
        return v
    if "enum" in p and v not in p["enum"] and isinstance(v, str):
        v = _same_ratio(v, p["enum"])
    if "enum" in p and v not in p["enum"]:
        errors.append(f"{name}: {v!r} isn't one of {', '.join(map(str, p['enum'][:12]))}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in p and v < p["minimum"]:
            errors.append(f"{name}: {v} is below the minimum {p['minimum']}")
        if "maximum" in p and v > p["maximum"]:
            errors.append(f"{name}: {v} is above the maximum {p['maximum']}")
    return v


RATIO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)")


def _same_ratio(v: str, choices: list) -> str:
    """"16:9" ↔ "16:9 (Widescreen)": packs label their aspect choices differently; the one choice
    with the same ratio stands in for the value (anything else is left for the enum check)."""
    m = RATIO.match(v)
    if not m:
        return v
    hits = [c for c in choices if isinstance(c, str) and (cm := RATIO.match(c)) and cm.groups() == m.groups()]
    return hits[0] if len(hits) == 1 else v


def resolve(pack: Pack, schema: dict, values: dict[str, Any] | None, preset: str | None = None,
            rng: random.Random | None = None) -> dict[str, Any]:
    """The full set of values a run uses: defaults < preset < the caller's. Raises InputError."""
    values = {k: v for k, v in (values or {}).items() if v is not None}
    props = schema.get("properties", {})
    errors = [f"{k}: not an input of {pack.id} (inputs: {', '.join(props)})" for k in values if k not in props]
    out: dict[str, Any] = {k: p["default"] for k, p in props.items() if "default" in p}
    asked = dict(values)                          # what the caller or the preset set (derived inputs follow it)
    if preset:
        presets = pack.manifest.presets if pack.manifest else {}
        if preset not in presets:
            errors.append(f"preset {preset!r} doesn't exist (presets: {', '.join(presets) or 'none'})")
        else:
            out.update(pack.manifest.preset_values(preset))
            asked = {**pack.manifest.preset_values(preset), **values}
    out.update({k: v for k, v in values.items() if k in props})
    for k, m in (pack.manifest.inputs.items() if pack.manifest else ()):
        v = values.get(k)
        if m.template and isinstance(v, str) and v.strip() and "<image" not in v and len(v.split()) <= TEMPLATE_WORDS:
            out[k] = m.template.replace("{}", v.strip())     # "the storefront" → the workflow's own instruction around it
    for k in schema.get("required", []):
        if out.get(k) in (None, "", []):
            errors.append(f"{k}: required")
    for k in list(out):
        if k in props:
            out[k] = _coerce(k, out[k], props[k], errors)
    if errors:
        raise InputError("; ".join(errors), errors)
    if "seed" in props and (out.get("seed") is None or out.get("seed") == -1):
        out["seed"] = (rng or random).randint(0, SEED_MAX)
    _derive(out, props, asked, set(pack.manifest.inputs) if pack.manifest else set())
    return out


def _derive(out: dict, props: dict, given: dict, mapped: set[str] = frozenset()) -> None:
    """aspect + megapixels → width/height (multiples of 16), megapixels alone → `resolution` (a square
    working size, multiples of 32) for packs that map one, seconds → frames (kept 4k+1 when the
    workflow's own frame count is, as Wan's are). Only when the caller (or preset) asked, and only for
    names the pack doesn't map to a field itself (a resolution picker takes aspect + megapixels as they are)."""
    if "aspect" in mapped or "megapixels" in mapped:
        pass
    elif "aspect" in props and ("aspect" in given or "megapixels" in given):
        w0, h0 = out.get("width") or 1024, out.get("height") or 1024
        if "aspect" in given or out.get("aspect"):
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(out.get("aspect") or "1:1"))
            a, b = (float(m.group(1)), float(m.group(2))) if m else (w0, h0)
        else:
            a, b = w0, h0
        mp = float(out.get("megapixels") or (w0 * h0) / 1e6)
        h = math.sqrt(mp * 1e6 * b / a)
        out["width"], out["height"] = _r16(h * a / b), _r16(h)
    elif "resolution" in mapped and "width" not in mapped and given.get("megapixels"):
        # Qwen-Image 2.1's encoder reads its images at about resolution × resolution (multiples of 32),
        # and 1.0 MP = 1024 × 1024 as in its ResolutionSelector, so megapixels means the same in its packs.
        out["resolution"] = max(32, int(round(1024 * math.sqrt(float(out["megapixels"])) / 32)) * 32)
    for k in ("aspect", "megapixels"):
        if k not in mapped:
            out.pop(k, None)
    if "seconds" in props and given.get("seconds") and "seconds" not in mapped:
        fps = float(out.get("fps") or 16)
        frames = max(1, round(float(given["seconds"]) * fps))
        if int(props.get("frames", {}).get("default") or 0) % 4 == 1:
            frames = 4 * round((frames - 1) / 4) + 1
        out["frames"] = frames
    if "seconds" not in mapped:
        out.pop("seconds", None)


def _r16(x: float) -> int:
    return max(16, int(round(x / 16)) * 16)


def patch(pack: Pack, conv: Converted, values: dict[str, Any], catalog: NodeCatalog, slug: str,
          now: datetime | None = None) -> dict:
    """The graph with the values set, and every saving node's filename_prefix set to
    `<YYYY-MM-DD>/<HHMMSS>-<slug>` so results land in dated folders."""
    g = copy.deepcopy(conv.graph)
    m = pack.manifest
    for name, im in (m.inputs.items() if m else []):
        if name not in values:
            continue
        eid, _ = locate(conv, im.node, im.title)
        if eid is None:
            continue
        targets = [(eid, im.field)] + [split_target(t) for t in im.also]
        for node, fld in targets:
            if node in g:
                g[node]["inputs"][fld] = values[name]
    now = now or datetime.now()
    savers = [k for k, n in g.items() if catalog.is_output(n["class_type"]) and "filename_prefix" in n["inputs"]
              and not n["class_type"].startswith("Preview")]
    for i, k in enumerate(sorted(savers, key=lambda x: [int(p) if p.isdigit() else 0 for p in x.split(":")])):
        g[k]["inputs"]["filename_prefix"] = f"{now:%Y-%m-%d}/{now:%H%M%S}-{slug}" + (f"-{i + 1}" if len(savers) > 1 else "")
    return g


def slugify(text: str, fallback: str = "comfy") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40].strip("-")
    return s or fallback
