"""The tool catalog (plan 13.1): every mod's `[tools]`, every running mod's `[agent] tools_source`
functions, and the hub's own tools, as OpenAI-style functions with risk levels.

- **Names** are `<mod>_<tool>` (a `-` in the mod id becomes `_`); hub tools are `hub_<tool>`.
- **Schemas** come from the mod's OpenAPI (`flatten`), read once per process start. The last
  good list of each mod is kept in `hub.db` (`kv`), so a stopped mod's tools stay listed, marked
  `available: false` with the reason (a call starts the mod first).
- **Risk** (plan 25.1): `read`, `write`, `generate`, `network` (reaches the internet), `execute`
  (runs code or commands) or `destructive`. Default: `read` for GET, `destructive` for DELETE or
  `confirm = true`, else `write`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from utils import operations
from utils.tools import options
from utils.tools.grants import GRANT_KEY
from utils.tools.grants import problems as grant_problems
from utils.tools.schema import Route, clean, flatten, mark_files

if TYPE_CHECKING:
    from utils.server import Hub
    from utils.services import Service

log = logging.getLogger("aihub.tools")
KV_PREFIX = "tools:"
RISKS = ("read", "write", "generate", "network", "execute", "destructive")   # plan 25.1
SEARCH_LIMIT = 8
WORD = re.compile(r"[a-z0-9]+")
STOP = {"a", "an", "the", "of", "to", "and", "or", "for", "in", "on", "with", "my", "me", "make", "please", "from", "into", "it", "this", "that"}
SYNONYMS = {"picture": "image", "photo": "image", "pic": "image", "img": "image", "3d": "3d", "mesh": "3d", "model3d": "3d",
            "speech": "speak", "voice": "voice", "tts": "speak", "say": "speak", "narrate": "speak", "animate": "video",
            "movie": "video", "clip": "video", "llm": "llm", "gpu": "memory", "ram": "memory"}


@dataclass
class ToolDef:
    name: str
    mod: str | None                  # None: a hub tool
    tool: str                        # the name inside its mod
    description: str
    parameters: dict[str, Any]
    risk: str = "write"
    ask: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    core: bool = False
    source: str = "manifest"         # manifest | tools_source | hub
    route: Route | None = None
    response: str = "json"
    job: dict[str, str] | None = None  # {"status": op, "cancel": op}
    available: bool = True
    why: str | None = None
    handler: Callable[..., Any] | None = None  # hub tools
    cap_bytes: int | None = None     # results kept whole up to this size (default results.CAP_BYTES; plan 24.4)
    problems: list[str] = field(default_factory=list)
    grant_key: str | None = None     # plan 25.2: what "allow in this chat" covers (utils/tools/grants.py)
    limits: str | None = None        # plan 27.4: the mod's preflight op ("POST /v1/limits"), asked before deciding

    def public(self, full: bool = True, view: str = "full") -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "mod": self.mod or "hub", "risk": self.risk, "core": self.core,
                               "summary": summary_line(self.description), "available": self.available}
        if self.why:
            out["why"] = self.why
        if full:
            params = options.for_model(self.parameters) if view == "model" else self.parameters
            out.update({"description": self.description, "parameters": params, "ask": self.ask,
                        "examples": self.examples, "job": self.job is not None, "source": self.source})
            if self.grant_key:
                out["grant_key"] = self.grant_key
        return out

    def function(self) -> dict[str, Any]:
        """The OpenAI `tools` entry."""
        desc = self.description
        if self.examples:
            desc += "\nExample arguments: " + "; ".join(json.dumps(e, separators=(",", ":")) for e in self.examples[:2])
        return {"type": "function", "function": {"name": self.name, "description": desc, "parameters": options.for_model(self.parameters)}}


def summary_line(desc: str) -> str:
    line = (desc or "").strip().split("\n", 1)[0]
    return line[:157] + "…" if len(line) > 160 else line


def tool_name(mod: str, tool: str) -> str:
    return f"{mod.replace('-', '_')}_{tool}"


def default_risk(method: str, confirm: bool) -> str:
    if confirm or method == "DELETE":
        return "destructive"
    return "read" if method == "GET" else "write"


def _job_ops(status: str | None, cancel: str | None) -> dict[str, str] | None:
    if not status:
        return None
    out = {"status": status}
    if cancel:
        out["cancel"] = cancel
    return out


class Catalog:
    """Built on demand from the services; per-mod parts are cached per process start."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self._mods: dict[str, tuple[Any, list[ToolDef]]] = {}  # service id → (cache key, tools)
        self._hub_tools: list[ToolDef] = []
        self._lock = asyncio.Lock()
        self.errors: dict[str, str] = {}

    def add_hub_tools(self, tools: list[ToolDef]) -> None:
        self._hub_tools = tools

    # ---- building ----------------------------------------------------------------------------

    async def refresh_mod(self, svc: Service) -> None:
        """The on-ready hook: read a mod's tools as soon as it's up, so they're kept for when it stops."""
        if svc.m is None or svc.errors or not (svc.m.tools or svc.m.agent.tools_source):
            return
        async with self._lock:
            await self._mod_tools(svc)

    async def tools(self) -> list[ToolDef]:
        mgr = self.hub.services
        out = list(self._hub_tools)
        if mgr is None:
            return out
        async with self._lock:
            for svc in mgr.list():
                if svc.m is None or svc.errors or not svc.eff.enabled:
                    self._mods.pop(svc.id, None)
                    continue
                out += await self._mod_tools(svc)
            gone = set(self._mods) - {s.id for s in mgr.list()}
            for g in gone:
                self._mods.pop(g, None)
        seen: set[str] = set()
        uniq = []
        for t in out:
            if t.name in seen:
                log.warning("tool %s listed twice; the first one is kept", t.name)
                continue
            seen.add(t.name)
            uniq.append(t)
        return uniq

    async def _mod_tools(self, svc: Service) -> list[ToolDef]:
        assert svc.m
        if not svc.m.tools and not svc.m.agent.tools_source:
            return []
        if svc.up:
            key = operations.cache_key(svc)
            cached = self._mods.get(svc.id)
            if cached and cached[0] == key:
                return cached[1]
            try:
                tools = await self._build(svc)
                self.errors.pop(svc.id, None)
                self._mods[svc.id] = (key, tools)
                await self._persist(svc.id, tools)
                return tools
            except Exception as e:  # noqa: BLE001 - one mod's broken API must not break the catalog
                self.errors[svc.id] = f"{type(e).__name__}: {e}"
                log.warning("tools of %s: %s", svc.id, self.errors[svc.id])
        why = (f"{svc.mod.name} is {svc.state}; a call starts it first" if svc.startable
               else f"{svc.mod.name} can't start: {'; '.join(svc.errors)[:200]}")
        tools = await self._restore(svc)
        for t in tools:
            t.available, t.why = (False, why) if not svc.up else (False, self.errors.get(svc.id, why))
        return tools

    async def _build(self, svc: Service) -> list[ToolDef]:
        assert svc.m
        mgr = self.hub.services
        ops = await operations.fetch(mgr, svc, include_hidden=True) if svc.m.tools else []
        by_key = {f"{o['method']} {o['path']}": o for o in ops}
        out: list[ToolDef] = []
        for name, spec in svc.m.tools.items():
            method, path = spec.op.split(" ", 1)
            op = by_key.get(f"{method} {path.split('?')[0]}")
            if op is None:
                out.append(ToolDef(tool_name(svc.id, name), svc.id, name, spec.description or spec.op, {"type": "object"},
                                   available=False, why=f"{spec.op} isn't in {svc.mod.name}'s API",
                                   problems=[f"{spec.op} not found in the OpenAPI"]))
                continue
            params, route, problems = flatten(op)
            for k in [*spec.hide, *spec.fixed]:
                params.get("properties", {}).pop(k, None)
                if k in params.get("required", []):
                    params["required"].remove(k)
            if not params.get("required"):
                params.pop("required", None)
            route.fixed = dict(spec.fixed)
            desc = spec.description or op["summary"]
            if op.get("description") and op["description"].strip() and op["description"].strip() != desc:
                desc += "\n" + op["description"].strip().split("\n\n", 1)[0][:600]
            risk = spec.risk or default_risk(method, spec.confirm)
            ask = [a for a in spec.ask if a in params.get("properties", {})]
            problems += [f"ask field {a!r} isn't a parameter" for a in spec.ask if a not in ask]
            job = _job_ops(spec.job_status, spec.job_cancel) if spec.job else None
            if job:
                desc += "\nRuns as a job: the call returns when it has finished, with its outputs."
            problems += grant_problems(spec.grant_key, params)
            out.append(ToolDef(tool_name(svc.id, name), svc.id, name, desc, params, risk=risk, ask=ask,
                               examples=list(spec.examples), core=spec.core, route=route, response=op["response"],
                               job=job, problems=problems, grant_key=spec.grant_key,
                               cap_bytes=spec.cap_kb * 1024 if spec.cap_kb else None))
        if svc.m.agent.tools_source:
            out += await self._source(svc)
        for t in out:
            t.limits = svc.m.agent.limits
        return out

    async def _source(self, svc: Service) -> list[ToolDef]:
        assert svc.m and svc.m.agent.tools_source
        method, path = svc.m.agent.tools_source.split(" ", 1)
        r = await self.hub.services.client.request(method, svc.url + path, timeout=15)
        r.raise_for_status()
        body = r.json()
        items = body.get("tools") if isinstance(body, dict) else body
        out = []
        for it in items or []:
            fn = (it or {}).get("function") or {}
            name, op = fn.get("name"), it.get("op")
            if not isinstance(name, str) or not isinstance(op, str) or " " not in op:
                continue
            params = clean(fn.get("parameters") or {"type": "object", "properties": {}})
            mark_files(params)
            m, p = op.split(" ", 1)
            job = it.get("job") if isinstance(it.get("job"), dict) else None
            route = Route(m, p, body="json" if m != "GET" else None, wrap="arguments" if m != "GET" else None)
            if m == "GET":
                route.params = {k: "query" for k in params.get("properties", {})}
            risk = it.get("risk") if it.get("risk") in RISKS else (
                "generate" if job else default_risk(m, False))
            desc = str(fn.get("description") or name)
            if job:
                desc += "\nRuns as a job: the call returns when it has finished, with its outputs."
            ask = [a for a in it.get("ask") or [] if a in params.get("properties", {})]
            gk = it.get("grant_key") if isinstance(it.get("grant_key"), str) and GRANT_KEY.match(it["grant_key"]) else None
            out.append(ToolDef(tool_name(svc.id, name), svc.id, name, desc, params, risk=risk, ask=ask,
                               examples=[e for e in it.get("examples") or [] if isinstance(e, dict)],
                               core=bool(it.get("core")), source="tools_source", route=route, job=job,
                               problems=grant_problems(gk, params), grant_key=gk))
        return out

    # ---- persistence (a stopped mod keeps its tools listed) ----------------------------------

    async def _persist(self, sid: str, tools: list[ToolDef]) -> None:
        db = self.hub.db
        if db is None:
            return
        rows = [{**t.public(), "route": t.route.__dict__ if t.route else None, "response": t.response,
                 "job_ops": t.job, "tool": t.tool, "cap_bytes": t.cap_bytes, "limits": t.limits} for t in tools]
        await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (KV_PREFIX + sid, json.dumps({"ts": time.time(), "tools": rows})))

    async def _restore(self, svc: Service) -> list[ToolDef]:
        db = self.hub.db
        rows: list[dict[str, Any]] = []
        if db is not None:
            row = await db.fetchone("SELECT value FROM kv WHERE key = ?", (KV_PREFIX + svc.id,))
            if row and row["value"]:
                try:
                    rows = json.loads(row["value"]).get("tools") or []
                except ValueError:
                    rows = []
        if rows:
            out = []
            for r in rows:
                route = Route(**r["route"]) if r.get("route") else None
                out.append(ToolDef(r["name"], svc.id, r.get("tool") or r["name"], r.get("description", ""), r.get("parameters") or {},
                                   risk=r.get("risk", "write"), ask=r.get("ask") or [], examples=r.get("examples") or [],
                                   core=bool(r.get("core")), source=r.get("source", "manifest"), route=route,
                                   response=r.get("response", "json"), job=r.get("job_ops"), grant_key=r.get("grant_key"),
                                   cap_bytes=r.get("cap_bytes"), limits=svc.m.agent.limits if svc.m else r.get("limits")))
            return out
        assert svc.m
        return [ToolDef(tool_name(svc.id, n), svc.id, n, s.description or s.op, {"type": "object"},
                        risk=s.risk or default_risk(s.op.split(" ", 1)[0], s.confirm), ask=list(s.ask),
                        examples=list(s.examples), core=s.core,
                        job=_job_ops(s.job_status, s.job_cancel) if s.job else None, grant_key=s.grant_key,
                        cap_bytes=s.cap_kb * 1024 if s.cap_kb else None, limits=svc.m.agent.limits)
                for n, s in svc.m.tools.items()]

    # ---- lookups -----------------------------------------------------------------------------

    async def get(self, name: str) -> ToolDef | None:
        for t in await self.tools():
            if t.name == name:
                return t
        return None

    async def close_matches(self, name: str) -> list[str]:
        import difflib

        return difflib.get_close_matches(name, [t.name for t in await self.tools()], n=3, cutoff=0.5)

    async def search(self, q: str, limit: int = SEARCH_LIMIT) -> list[ToolDef]:
        words = [SYNONYMS.get(w, w) for w in WORD.findall(q.lower()) if w not in STOP]
        if not words:
            return []
        scored = []
        for t in await self.tools():
            name = t.name.lower()
            hay = f"{name} {t.mod or 'hub'} {t.description.lower()}"
            score = 0.0
            for w in words:
                if w in name.split("_") or w in name:
                    score += 3
                if w in hay:
                    score += 1 + hay.count(w) * 0.1
                elif len(w) > 4 and w[:-1] in hay:   # plurals: images → image
                    score += 0.8
            if score:
                scored.append((score, t.name, t))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [t for _, _, t in scored[:limit]]
