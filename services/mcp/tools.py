"""MCP tools as GAIFA tools (plan mcp-client 1.3, 2.1).

- **Rows** for the hub's `tools_source`: `mcp_<server>_<tool>` (the hub adds `mcp_`), its description led by the
  server's name, its input schema, a risk, and `mcp = false` (GAIFA doesn't pass other servers' tools on to its own
  MCP clients). Only an approved server whose tools still match what was approved gives rows; denied tools never.
- **Risk:** the user's choice for the tool, else `readOnlyHint` → read, `destructiveHint` → destructive, a name or
  description about running code → execute, `openWorldHint` → network, else write.
- **Fingerprint:** a hash per tool over its name, description, input schema and annotations, and one over all of
  them in name order; a change holds the server until the user approves again (the "rug pull").
- **Results:** text joined inside `<untrusted>`, images and audio written as outputs (`<outputs>/<date>/<HHMMSS>-<server>-<tool>.<ext>`
  with a sidecar), structured content kept, an error as the error envelope; everything from a server is data.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

CODE = re.compile(r"\b(exec|execute|eval|run_?code|python|shell|bash|script|command|terminal|subprocess)\b", re.I)
TEXT_CAP = 64_000
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "audio/wav": "wav",
       "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/flac": "flac"}


def tool_hash(t: dict[str, Any]) -> str:
    keep = {k: t.get(k) for k in ("name", "description", "inputSchema", "annotations")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fingerprint(tools: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    per = {t["name"]: tool_hash(t) for t in tools}
    return hashlib.sha256(json.dumps(sorted(per.items())).encode()).hexdigest()[:16], per


def diff(approved: dict[str, str] | None, now: dict[str, str]) -> dict[str, list[str]]:
    a = approved or {}
    return {"added": sorted(set(now) - set(a)), "removed": sorted(set(a) - set(now)),
            "changed": sorted(k for k in set(a) & set(now) if a[k] != now[k])}


def risk_of(t: dict[str, Any], chosen: dict[str, str] | None = None) -> str:
    if (chosen or {}).get(t["name"]):
        return chosen[t["name"]]
    ann = t.get("annotations") or {}
    if ann.get("readOnlyHint") is True:
        return "read"
    if ann.get("destructiveHint") is True:
        return "destructive"
    if CODE.search(t["name"].replace("_", " ")) or CODE.search(t.get("description") or ""):
        return "execute"
    if ann.get("openWorldHint") is True:
        return "network"
    return "write"


def safe_name(s: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")[:48] or "tool"


def rows(spec: dict[str, Any], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The hub's tool rows for one approved server."""
    out, seen = [], set()
    for t in tools:
        if t["name"] in (spec.get("deny") or []):
            continue
        name = f"{safe_name(spec['id'])}_{safe_name(t['name'])}"[:60]
        if name in seen:
            continue
        seen.add(name)
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        desc = f"{spec.get('name') or spec['id']} (MCP server): " + (t.get("description") or t.get("title") or t["name"]).strip()
        if spec.get("note"):
            desc += "\n" + spec["note"]
        out.append({"type": "function", "function": {"name": name, "description": desc[:2000], "parameters": schema},
                    "op": f"POST /v1/call/{spec['id']}/{t['name']}", "risk": risk_of(t, spec.get("risks")), "mcp": False,
                    "group": f"mcp:{spec['id']}"})
    return out


def result(sid: str, tool: str, r: Any, outputs: Path, since: float | None = None) -> dict[str, Any]:
    """A CallToolResult as this mod's answer: {text, outputs, structured}, or raises ValueError for an error result.
    `since`: when the call started; files written under the outputs folder from then on become outputs too."""
    texts, files = [], []
    for c in getattr(r, "content", None) or []:
        kind = getattr(c, "type", "")
        if kind == "text":
            texts.append(c.text)
        elif kind in ("image", "audio"):
            files.append(save(sid, tool, c.data, c.mime_type, outputs))
        elif kind == "resource":
            res = c.resource
            texts.append(getattr(res, "text", None) or f"(a resource: {getattr(res, 'uri', '')})")
        elif kind == "resource_link":
            texts.append(f"(a link: {getattr(c, 'uri', '')})")
    text = "\n".join(texts)
    if getattr(r, "is_error", False):
        raise ValueError(text[:2000] or "the tool reported an error")
    text = text[:TEXT_CAP] + ("\n[…cut]" if len(text) > TEXT_CAP else "")
    for f in written(text, outputs) + (fresh(outputs, since, files) if since is not None else []):
        if f not in files:                          # files the server saved under this mod's outputs (a render)
            files.append(f)
    out: dict[str, Any] = {"text": untrusted(f"mcp:{sid}/{tool}", text) if text else ""}
    if files:
        out["outputs"] = files
    if getattr(r, "structured_content", None):
        out["structured"] = r.structured_content
    return out


def written(text: str, outputs: Path) -> list[str]:
    """Paths in a server's text to files that exist under this mod's outputs folder: they become outputs."""
    root = str(outputs.resolve())
    out = []
    for m in re.finditer(re.escape(root) + r"/[^\s'\"<>)\]]+", text):
        p = Path(m.group(0).rstrip(".,;:"))
        if p.is_file() and p.resolve().is_relative_to(outputs.resolve()) and str(p) not in out:
            out.append(str(p))
    return out[:20]


def fresh(outputs: Path, since: float, skip: list[str] = ()) -> list[str]:  # type: ignore[assignment]
    """Files written under the outputs folder since `since` (a call's start), the ones it saved itself aside: a render
    whose path the code didn't print. Only today's and yesterday's folders and folders changed since are looked at."""
    if not outputs.is_dir():
        return []
    days = {time.strftime("%Y-%m-%d", time.localtime(since - d)) for d in (0, 86400)} | {time.strftime("%Y-%m-%d")}
    out = []
    for d in outputs.iterdir():
        if not d.is_dir() or (d.name not in days and d.stat().st_mtime < since - 1):
            continue
        for p in d.rglob("*"):
            if (p.is_file() and not p.name.startswith(".") and p.suffix not in (".json", ".part")
                    and p.stat().st_mtime >= since - 1 and str(p) not in skip and str(p) not in out):
                out.append(str(p))
    return sorted(out)[:20]


def untrusted(source: str, text: str) -> str:
    """A server's words for the model: data, never instructions (plan mcp-client 2.2), as the agent wraps pages."""
    src = re.sub(r'["<>\n]', "'", source)[:200]
    return f'<untrusted source="{src}">\n{re.sub(r"</\s*untrusted", "</ untrusted", text, flags=re.I)}\n</untrusted>'


def save(sid: str, tool: str, data: str, mime: str, outputs: Path) -> str:
    """An image or a clip from a server, as an output (architecture §4.7)."""
    day = outputs / time.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    ext = EXT.get((mime or "").split(";")[0], "bin")
    name = f"{time.strftime('%H%M%S')}-{safe_name(sid)}-{safe_name(tool)}"
    p, i = day / f"{name}.{ext}", 1
    while p.exists():
        i += 1
        p = day / f"{name}-{i}.{ext}"
    tmp = p.with_name(p.name + ".part")
    tmp.write_bytes(base64.b64decode(data))
    p.with_name(p.stem + ".json").write_text(json.dumps({"title": f"{sid}: {tool}", "source": {"service": "mcp", "server": sid, "tool": tool}}))
    tmp.replace(p)
    return str(p)
