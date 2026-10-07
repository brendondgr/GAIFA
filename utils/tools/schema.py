"""Tool parameter schemas (plan 13.1–13.2): one flat JSON Schema per tool, and argument checks
whose errors tell the model what to fix.

- `flatten(op)` merges an operation's path and query parameters and its JSON (or multipart) body
  into one object schema, and returns how to split arguments back (`Route`).
- `validate(schema, args)` returns a list of problems, each `{field, detail, fix}`. It covers what
  tool schemas use: type, required, enum, minimum/maximum, min/max length and items, closed objects.
- File inputs get `x-kind` (image, video, audio, mesh, file) so the agent and the parameter cards
  know which outputs fit.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from typing import Any

SCHEMA_KEYS = ("properties", "items", "anyOf", "oneOf", "allOf", "additionalProperties")
KIND_WORDS = (("mask", "image"), ("image", "image"), ("photo", "image"), ("picture", "image"), ("video", "video"),
              ("clip", "audio"), ("audio", "audio"), ("voice_file", "audio"), ("mesh", "mesh"), ("model", "mesh"))
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


@dataclass
class Route:
    """How a tool's flat arguments map back onto its HTTP operation."""

    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)  # name → "path" | "query"
    body: str | None = None                                # "json" | "multipart" | None
    body_key: str | None = None                            # a non-object body sent whole from this argument
    files: list[str] = field(default_factory=list)         # multipart fields that are files
    fixed: dict[str, Any] = field(default_factory=dict)    # always sent (manifest `fixed`)
    wrap: str | None = None                                # JSON body sent as {wrap: arguments} (tools_source calls)


def clean(s: Any) -> Any:
    """A schema without `title` keywords (noise for the model); property names are kept."""
    if not isinstance(s, dict):
        return s
    out = {}
    for k, v in s.items():
        if k == "title":
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: clean(pv) for pk, pv in v.items()}
        elif k in ("items", "additionalProperties", "not") and isinstance(v, dict):
            out[k] = clean(v)
        elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
            out[k] = [clean(x) for x in v]
        else:
            out[k] = copy.deepcopy(v)
    return out


def file_kind(name: str, s: dict[str, Any]) -> str | None:
    """`x-kind` for a file input: from its media type, else its name; None if it isn't a file."""
    is_file = s.get("format") in ("binary", "aihub-file") or (
        s.get("type") == "array" and (s.get("items") or {}).get("format") in ("binary", "aihub-file"))
    if not is_file:
        return None
    media = str(s.get("contentMediaType") or (s.get("items") or {}).get("contentMediaType") or "")
    for prefix, kind in (("image/", "image"), ("video/", "video"), ("audio/", "audio"), ("model/", "mesh")):
        if media.startswith(prefix):
            return kind
    for text in (name.lower(), str(s.get("description") or "").lower()):
        for word, kind in KIND_WORDS:
            if word in text:
                return kind
    return "file"


def mark_files(schema: dict[str, Any]) -> list[str]:
    """Add `x-kind` to each file property; returns the file property names."""
    found = []
    for name, p in (schema.get("properties") or {}).items():
        if isinstance(p, dict) and "x-kind" not in p:
            kind = file_kind(name, p)
            if kind:
                p["x-kind"] = kind
        if isinstance(p, dict) and p.get("x-kind"):
            found.append(name)
    return found


def flatten(op: dict[str, Any]) -> tuple[dict[str, Any], Route, list[str]]:
    """An `Operation` (operations.py) → (parameters schema, route, problems)."""
    route = Route(op["method"], op["path"])
    props: dict[str, Any] = {}
    required: list[str] = []
    problems: list[str] = []
    for p in op.get("params") or []:
        s = clean(p.get("schema") or {})
        if p.get("description") and "description" not in s:
            s["description"] = p["description"]
        props[p["name"]] = s
        route.params[p["name"]] = p["in"]
        if p.get("required"):
            required.append(p["name"])
    closed = True
    body = op.get("body")
    if body:
        s = clean(body.get("schema") or {})
        route.body = "multipart" if body.get("content_type") == "multipart/form-data" else "json"
        if s.get("type") == "object" or "properties" in s:
            if not s.get("properties"):
                closed = False  # an open object: every extra argument goes in the body
            for k, v in (s.get("properties") or {}).items():
                if k in props:
                    problems.append(f"body field {k!r} has the same name as a {route.params[k]} parameter; the parameter wins")
                    continue
                props[k] = v
            required += [r for r in s.get("required") or [] if r not in required]
            if s.get("additionalProperties") not in (None, False):
                closed = False
        else:
            props["body"] = s
            route.body_key = "body"
            if body.get("required", True):
                required.append("body")
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    if closed:
        schema["additionalProperties"] = False
    route.files = [n for n in mark_files(schema) if route.body == "multipart"]
    return schema, route, problems


# ---- validation ------------------------------------------------------------------------------


def _type_ok(v: Any, t: Any, s: dict[str, Any]) -> bool:
    if isinstance(t, list):
        return any(_type_ok(v, x, s) for x in t)
    if t == "null":
        return v is None
    if v is None and s.get("nullable"):
        return True
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    if t == "integer" and isinstance(v, float) and v.is_integer():
        return True
    py = TYPES.get(t)
    return True if py is None else isinstance(v, py)


def _is_file_ref(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {"$file"} and isinstance(v["$file"], str)


def _check(s: dict[str, Any], v: Any, where: str, out: list[dict[str, str]]) -> None:
    if not isinstance(s, dict) or not s:
        return
    if s.get("x-kind") and _is_file_ref(v):
        return
    for key in ("anyOf", "oneOf"):
        alts = s.get(key)
        if isinstance(alts, list) and alts:
            if not any(not _errors(a, v, where) for a in alts if isinstance(a, dict)):
                out.append({"field": where, "detail": f"{where}: doesn't match any allowed form",
                            "fix": f"use one of: {', '.join(str(a.get('type') or a.get('enum') or a) for a in alts)}"})
            return
    t = s.get("type")
    if t and not _type_ok(v, t, s):
        out.append({"field": where, "detail": f"{where}: expected {t if isinstance(t, str) else ' or '.join(t)}, got {type(v).__name__}",
                    "fix": f"send {where} as a {t}" + (f", e.g. {s['default']!r}" if "default" in s else "")})
        return
    if v is None:
        return
    if "enum" in s and v not in s["enum"]:
        close = difflib.get_close_matches(str(v), [str(e) for e in s["enum"]], n=1)
        out.append({"field": where, "detail": f"{where}: {v!r} isn't one of the allowed values",
                    "fix": (f"did you mean {close[0]!r}? " if close else "") + f"allowed: {', '.join(map(repr, s['enum'][:30]))}"})
        return
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            out.append({"field": where, "detail": f"{where}: {v} is below the minimum {s['minimum']}", "fix": f"use {s['minimum']} or more"})
        if "maximum" in s and v > s["maximum"]:
            out.append({"field": where, "detail": f"{where}: {v} is above the maximum {s['maximum']}", "fix": f"use {s['maximum']} or less"})
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            out.append({"field": where, "detail": f"{where}: too short", "fix": f"at least {s['minLength']} characters"})
        if "maxLength" in s and len(v) > s["maxLength"]:
            out.append({"field": where, "detail": f"{where}: too long ({len(v)} characters)", "fix": f"at most {s['maxLength']} characters"})
    if isinstance(v, list):
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append({"field": where, "detail": f"{where}: {len(v)} items", "fix": f"at most {s['maxItems']} items"})
        if "minItems" in s and len(v) < s["minItems"]:
            out.append({"field": where, "detail": f"{where}: {len(v)} items", "fix": f"at least {s['minItems']} items"})
        if isinstance(s.get("items"), dict):
            for i, x in enumerate(v[:200]):
                _check(s["items"], x, f"{where}[{i}]", out)
    if isinstance(v, dict) and (s.get("type") == "object" or "properties" in s):
        _object(s, v, where, out)


def _object(s: dict[str, Any], v: dict[str, Any], where: str, out: list[dict[str, str]]) -> None:
    props = s.get("properties") or {}
    prefix = f"{where}." if where else ""
    for r in s.get("required") or []:
        if r not in v or v[r] is None and not (props.get(r) or {}).get("nullable"):
            p = props.get(r) or {}
            hint = f"; allowed: {', '.join(map(repr, p['enum'][:12]))}" if "enum" in p else (f" ({p['description']})" if p.get("description") else "")
            out.append({"field": prefix + r, "detail": f"{prefix}{r} is required", "fix": f"add {prefix}{r}{hint}"})
    for k, x in v.items():
        if k in props:
            _check(props[k], x, prefix + k, out)
        elif s.get("additionalProperties") is False:
            close = difflib.get_close_matches(k, list(props), n=1)
            out.append({"field": prefix + k, "detail": f"{prefix}{k} isn't a parameter of this tool",
                        "fix": (f"did you mean {close[0]!r}? " if close else "") + f"parameters: {', '.join(props) or '(none)'}"})
        elif isinstance(s.get("additionalProperties"), dict):
            _check(s["additionalProperties"], x, prefix + k, out)


def _errors(s: dict[str, Any], v: Any, where: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    _check(s, v, where, out)
    return out


def validate(schema: dict[str, Any], args: Any) -> list[dict[str, str]]:
    """Problems with `args` against a tool's parameters schema (empty when they're fine)."""
    if not isinstance(args, dict):
        return [{"field": "", "detail": "arguments must be a JSON object", "fix": "send the arguments as {\"name\": value, …}"}]
    out: list[dict[str, str]] = []
    _object(schema, args, "", out)
    return out


def defaults(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """The arguments with each missing top-level property's `default` filled in (for the cards)."""
    out = dict(args)
    for k, p in (schema.get("properties") or {}).items():
        if k not in out and isinstance(p, dict) and "default" in p:
            out[k] = copy.deepcopy(p["default"])
    return out


def coerce(schema: dict[str, Any], args: Any) -> Any:
    """Forgive what small models get slightly wrong, before validation: a near-miss argument name
    (`aspect_ratio` for `aspect`), "16:9" for the one enum value "16:9 (Widescreen)", "8" for an
    integer, "true" for a boolean, a case-only enum mismatch."""
    if not isinstance(args, dict):
        return args
    out = dict(args)
    props = schema.get("properties") or {}
    for k in list(out):
        if k not in props and props:
            close = [c for c in difflib.get_close_matches(k, list(props), n=2, cutoff=0.6) if c not in out]
            stem = [c for c in props if c not in out and (k.startswith(c + "_") or c.startswith(k + "_"))]
            pick = stem if len(stem) == 1 else close
            if len(pick) == 1:      # aspect_ratio → aspect, voice_name → name … only when unambiguous
                out[pick[0]] = out.pop(k)
    for k, v in list(out.items()):
        p = props.get(k)
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if isinstance(v, str) and "enum" in p and v not in p["enum"]:
            low = v.strip().lower()
            hits = [e for e in p["enum"] if isinstance(e, str) and (e.lower() == low or e.lower().startswith(low + " "))]
            if len(hits) == 1:
                out[k] = hits[0]
        elif isinstance(v, str) and t in ("integer", "number"):
            try:
                out[k] = int(v) if t == "integer" else float(v)
            except ValueError:
                pass
        elif isinstance(v, str) and t == "boolean" and v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
    return out
