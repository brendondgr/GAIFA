"""A mod's OpenAPI document → the brief's `Operation[]` (plan 2.6, brief §6.4).

The API tab and (later) the agent's tools are both built from this. Schemas
are made easy for a generic form to render: local `$ref`s are inlined,
`anyOf: [T, null]` becomes `T` with `nullable: true`, and file fields
(`contentMediaType` in OpenAPI 3.1) get `format: binary`.
"""

from __future__ import annotations

import copy
import fnmatch
import re
import time
from typing import TYPE_CHECKING, Any

import httpx

from utils.manifest import Manifest

if TYPE_CHECKING:
    from utils.services import Service, ServiceManager

METHODS = ("get", "post", "put", "patch", "delete")
ALWAYS_HIDDEN = ("/docs", "/docs/oauth2-redirect", "/redoc")
MAX_DEPTH = 12
VERSION_SEGMENT = re.compile(r"^(v\d+|api)$")


class OpenAPIError(ValueError):
    pass


# --- conversion ---------------------------------------------------------------------


def convert(doc: dict[str, Any], m: Manifest) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise OpenAPIError("not an OpenAPI document (no `paths`)")
    hidden = [h.strip() for h in m.api.hide]
    tools = {spec.op: (name, spec) for name, spec in m.tools.items()}
    ops: list[dict[str, Any]] = []
    ids: set[str] = set()
    for path, item in doc["paths"].items():
        if not isinstance(item, dict) or _auto_hidden(path, m):
            continue
        item = _deref(doc, item)
        shared = item.get("parameters", [])
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            key = f"{method.upper()} {path}"
            if any(fnmatch.fnmatchcase(key, h) for h in hidden):
                continue
            tool = tools.get(key)
            confirm = bool(tool and tool[1].confirm)
            ops.append({
                "id": _unique(_op_id(method, path), ids),
                "method": method.upper(),
                "path": path,
                "summary": str(op.get("summary") or _humanize(op.get("operationId")) or key),
                "description": str(op.get("description") or ""),
                "tag": _tag(op, path),
                "params": _params(doc, [*shared, *op.get("parameters", [])]),
                "body": _body(doc, op.get("requestBody")),
                "response": m.api.responses.get(key) or _response_kind(op.get("responses") or {}),
                "destructive": method == "delete" or confirm,
                "tool": {"name": tool[0], "confirm": confirm} if tool else None,
            })
    return ops


def _auto_hidden(path: str, m: Manifest) -> bool:
    return path in ALWAYS_HIDDEN or path == m.run.openapi


def _op_id(method: str, path: str) -> str:
    return f"{method}_{re.sub(r'[^a-z0-9]+', '_', path.lower()).strip('_') or 'root'}"


def _unique(base: str, seen: set[str]) -> str:
    oid, n = base, 2
    while oid in seen:
        oid, n = f"{base}_{n}", n + 1
    seen.add(oid)
    return oid


def _humanize(operation_id: Any) -> str:
    if not isinstance(operation_id, str):
        return ""
    words = operation_id.split("_")
    # FastAPI ids are "<function>_<path>_<method>"; keep the function part.
    for i, w in enumerate(words):
        if VERSION_SEGMENT.match(w) or w in METHODS:
            words = words[:i]
            break
    return " ".join(words).capitalize()


def _tag(op: dict[str, Any], path: str) -> str:
    tags = op.get("tags")
    if isinstance(tags, list) and tags and isinstance(tags[0], str):
        return tags[0]
    for seg in path.strip("/").split("/"):
        if seg and not VERSION_SEGMENT.match(seg) and not seg.startswith("{"):
            return seg
    return "general"


def _params(doc: dict[str, Any], raw: list[Any]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for p in raw:
        p = _deref(doc, p)
        if not isinstance(p, dict) or p.get("in") not in ("path", "query") or not p.get("name"):
            continue
        param: dict[str, Any] = {
            "name": p["name"],
            "in": p["in"],
            "required": bool(p.get("required")) or p["in"] == "path",
            "schema": _schema(doc, p.get("schema") or {}),
        }
        desc = p.get("description") or param["schema"].get("description")
        if desc:
            param["description"] = str(desc)
        by_key[(p["in"], p["name"])] = param  # operation-level wins over path-level
    return list(by_key.values())


def _body(doc: dict[str, Any], rb: Any) -> dict[str, Any] | None:
    rb = _deref(doc, rb)
    if not isinstance(rb, dict) or not isinstance(rb.get("content"), dict):
        return None
    content = rb["content"]
    for ctype, as_type in (
        ("application/json", "application/json"),
        ("multipart/form-data", "multipart/form-data"),
        ("application/x-www-form-urlencoded", "multipart/form-data"),
    ):
        if ctype in content:
            schema = _schema(doc, (content[ctype] or {}).get("schema") or {})
            return {"content_type": as_type, "schema": schema}
    for ctype in content:
        if ctype.endswith("+json"):
            return {"content_type": "application/json", "schema": _schema(doc, (content[ctype] or {}).get("schema") or {})}
    return None


def _response_kind(responses: dict[str, Any]) -> str:
    ok = sorted(k for k in responses if str(k).startswith("2"))
    if not ok:
        return "json"
    if all(k == "204" for k in ok):
        return "empty"
    types: list[str] = []
    for k in ok:
        c = (responses.get(k) or {}).get("content") or {}
        types += list(c)
    if not types:
        return "empty" if "204" in ok or "202" in ok else "json"
    for t in types:
        if t.startswith("audio/"):
            return "audio"
        if t.startswith("image/"):
            return "image"
        if t.startswith("video/"):
            return "video"
        if t.startswith("model/"):
            return "model3d"
        if t == "text/event-stream":
            return "stream"
        if t in ("application/octet-stream", "application/zip", "application/x-zip-compressed", "application/pdf"):
            return "file"
    return "json"


# --- schemas --------------------------------------------------------------------------


def _deref(doc: dict[str, Any], node: Any, seen: frozenset[str] = frozenset()) -> Any:
    """Follow a top-level local `$ref` (one hop chain), without inlining nested ones."""
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return {}
        seen = seen | {ref}
        node = _resolve(doc, ref)
    return node


def _resolve(doc: dict[str, Any], ref: str) -> Any:
    cur: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or part not in cur:
            return {}
        cur = cur[part]
    return cur


def _schema(doc: dict[str, Any], node: Any, depth: int = 0, stack: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    if isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        name = ref.rsplit("/", 1)[-1]
        if ref in stack or depth > MAX_DEPTH:
            return {"type": "object", "title": name, "description": f"(recursive: {name})"}
        target = _resolve(doc, ref) if ref.startswith("#/") else {}
        extra = {k: v for k, v in node.items() if k != "$ref"}
        return _schema(doc, {**target, **extra}, depth + 1, (*stack, ref))
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in ("properties", "patternProperties", "$defs", "definitions") and isinstance(v, dict):
            out[k] = {pk: _schema(doc, pv, depth + 1, stack) for pk, pv in v.items()}
        elif k in ("items", "additionalProperties", "not", "contains") and isinstance(v, dict):
            out[k] = _schema(doc, v, depth + 1, stack)
        elif k in ("anyOf", "oneOf", "allOf", "prefixItems") and isinstance(v, list):
            out[k] = [_schema(doc, x, depth + 1, stack) for x in v]
        else:
            out[k] = copy.deepcopy(v)
    _nullable(out)
    _allof(out)
    if out.get("type") == "string" and ("contentMediaType" in out or out.get("contentEncoding") == "binary") and not str(out.get("contentMediaType", "")).startswith("text/"):
        out["format"] = "binary"
    return out


def _nullable(s: dict[str, Any]) -> None:
    """`anyOf: [T, {type: null}]` → T plus `nullable: true` (what FastAPI emits for `T | None`)."""
    for key in ("anyOf", "oneOf"):
        alts = s.get(key)
        if not isinstance(alts, list):
            continue
        rest = [a for a in alts if a.get("type") != "null"]
        if len(rest) == 1 and len(rest) < len(alts):
            del s[key]
            for k, v in rest[0].items():
                s.setdefault(k, v)
            s["nullable"] = True


def _allof(s: dict[str, Any]) -> None:
    """A single-entry `allOf` (FastAPI's way to attach a description to a $ref) is merged in."""
    alts = s.get("allOf")
    if isinstance(alts, list) and len(alts) == 1 and isinstance(alts[0], dict):
        del s["allOf"]
        for k, v in alts[0].items():
            s.setdefault(k, v)


# --- fetching and caching -------------------------------------------------------------


async def fetch(mgr: ServiceManager, svc: Service) -> list[dict[str, Any]]:
    """Fetch and convert the mod's OpenAPI. Raises OpenAPIError with a readable reason."""
    assert svc.m
    if not svc.m.run.openapi:
        return []
    url = svc.url + svc.m.run.openapi
    try:
        r = await mgr.client.get(url, timeout=10)
    except httpx.HTTPError as e:
        raise OpenAPIError(f"GET {svc.m.run.openapi}: {type(e).__name__}") from None
    if r.status_code != 200:
        raise OpenAPIError(f"GET {svc.m.run.openapi}: HTTP {r.status_code}")
    try:
        doc = r.json()
    except ValueError:
        raise OpenAPIError(f"GET {svc.m.run.openapi}: not JSON") from None
    return convert(doc, svc.m)


def cache_key(svc: Service) -> tuple[Any, ...]:
    """One OpenAPI read per process start (external mods: per time they became reachable)."""
    if svc.external:
        return ("external", svc.state_since if svc.up else None)
    return (svc.pid, svc.started_ts)


async def refresh(mgr: ServiceManager, svc: Service) -> None:
    """The on-ready hook: fetch once per process start; keep the last good list on failure."""
    key = cache_key(svc)
    if svc.operations is not None and svc.operations_key == key:
        return
    try:
        svc.operations = await fetch(mgr, svc)
        svc.operations_error = None
    except OpenAPIError as e:
        svc.operations_error = str(e)  # the last good list (if any) stays
        return
    svc.operations_key = key
    svc.operations_ts = time.time()


async def get(mgr: ServiceManager, svc: Service) -> list[dict[str, Any]]:
    """For the route: the cached list, fetched now if the mod is up and nothing is cached yet."""
    from utils.services import ServiceError

    if svc.operations is None or (svc.up and svc.operations_key != cache_key(svc)):
        if not svc.up:
            raise ServiceError(503, "service_not_running", f"{svc.mod.name} is not running, and its operations haven't been read yet", {"state": svc.state})
        await refresh(mgr, svc)
        if svc.operations is None:
            raise ServiceError(502, "upstream_error", f"can't read {svc.mod.name}'s API: {svc.operations_error}")
    return svc.operations
