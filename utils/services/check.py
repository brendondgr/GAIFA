"""`aihub check <id>` / `GET /api/services/{id}/check`: a mod self-test (plan 2.10).

Runs every check it can and says exactly what is wrong, so writing a mod is a
quick write → check → fix loop. Each check is `{name, status, detail}` with
status ok | fail | warn | skip; the mod passes when nothing failed. Checks that
need the mod running are skipped (with a hint) when it isn't.
"""

from __future__ import annotations

import fnmatch

import asyncio
import math
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from utils import manifest as mf
from utils import operations
from utils.proc import owner_text, port_listening, port_owner
from utils.services import status as status_mod

if TYPE_CHECKING:
    from utils.services.manager import ServiceManager
    from utils.services.model import Service

WIDGET_KINDS_WITH_T = {"line", "area", "bar"}


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append({"name": name, "status": status, "detail": detail})

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not any(c["status"] == "fail" for c in self.checks),
            "checks": [{**c, "ok": c["status"] != "fail"} for c in self.checks],
        }


async def run(mgr: ServiceManager, svc: Service, start: bool = False, tools: Any = None) -> dict[str, Any]:
    r = Report()
    # 1. manifest
    if svc.errors:
        for e in svc.errors:
            r.add("manifest", "fail", e)
        return r.as_dict()  # nothing else can be trusted
    r.add("manifest", "ok", f"{svc.mod.dir.name}/service.toml is valid")
    m = svc.m
    assert m

    # 2. command, cwd and env (process mods)
    spec = None
    if svc.external:
        r.add("command", "skip", 'kind = "external": AIHub doesn\'t launch it')
    else:
        try:
            spec = mf.launch_spec(svc.mod, mgr.config, mgr.paths, mgr.hub_port)
        except mf.ManifestError as e:
            r.add("command", "fail", str(e))
        if spec:
            exe = spec.argv[0]
            found = exe if os.path.isabs(exe) else shutil.which(exe)
            if not found or not os.path.exists(found):
                hint = " (run `aihub install " + svc.id + "`?)" if m.run.install and ".venv" in exe else ""
                r.add("command", "fail", f"{exe} not found{hint}")
            elif not os.access(found, os.X_OK):
                r.add("command", "fail", f"{found} is not executable (chmod +x)")
            elif not spec.cwd.is_dir():
                r.add("command", "fail", f"working directory {spec.cwd} does not exist")
            else:
                r.add("command", "ok", " ".join(spec.argv))
        if m.run.env_file and not (svc.mod.dir / m.run.env_file).exists():
            r.add("env_file", "warn", f"{m.run.env_file} doesn't exist (optional; secrets go there)")

    # 3. state (optionally start it first)
    if start and not svc.external and svc.state in ("stopped", "failed"):
        try:
            await mgr.start(svc.id, wait=True)
        except Exception as e:  # noqa: BLE001: report anything the start raised
            r.add("start", "fail", getattr(e, "detail", str(e)))
    running = svc.state in ("starting", "ready", "degraded")
    if svc.state == "ready":
        r.add("state", "ok", "ready")
    elif svc.state == "failed":
        r.add("state", "fail", (svc.last_error or "failed").split("\n\nLast log lines:")[0])
    elif svc.state in ("stopped", "stopping"):
        r.add("state", "skip", f"{svc.state}; start it (`aihub start {svc.id}`, or `aihub check {svc.id} --start`) to run the live checks")
    else:
        r.add("state", "warn", svc.state)

    # 4. port
    if running or svc.external:
        r.add("port", "ok", f"{svc.port} (this mod)" if running else f"{svc.port}")
    elif await asyncio.to_thread(port_listening, svc.port):
        owner = await asyncio.to_thread(port_owner, svc.port)
        r.add("port", "fail", f"{svc.port} is in use by {owner_text(owner)}")
    else:
        r.add("port", "ok", f"{svc.port} is free")

    live = running or (svc.external and svc.up)
    # 5. health
    if not live:
        r.add("health", "skip", "not running")
    else:
        h = await mgr.check_health(svc)
        if h["ok"]:
            r.add("health", "ok", f"{m.run.health} answered in {h['latency_ms']} ms")
        else:
            why = f"HTTP {h['status']}" if h.get("status") else (h.get("body") or "no answer")
            r.add("health", "fail", f"{m.run.health}: {why}")

    # 6. OpenAPI → operations
    ops: list[dict[str, Any]] | None = None
    if not m.run.openapi:
        r.add("openapi", "skip", "openapi = none in service.toml; the API tab stays empty")
    elif not live:
        r.add("openapi", "skip", "not running")
    else:
        try:
            ops = await operations.fetch(mgr, svc, include_hidden=True)   # widgets and tools may use hidden routes
            hidden = sum(1 for o in ops if any(fnmatch.fnmatchcase(f"{o['method']} {o['path']}", g) for g in m.api.hide))
            r.add("openapi", "ok", f"{len(ops) - hidden} operations" + (f" (+{hidden} hidden from the API tab)" if hidden else ""))
        except operations.OpenAPIError as e:
            r.add("openapi", "fail", str(e))

    # 7. operations the manifest refers to
    refs = _manifest_ops(m)
    if refs and ops is not None:
        have = {f"{o['method']} {o['path']}" for o in ops}
        missing = [f"{where}: {op}" for where, op in refs if op not in have]
        if missing:
            r.add("operations", "fail", "not in the OpenAPI: " + "; ".join(missing))
        else:
            r.add("operations", "ok", f"{len(refs)} referenced operations exist")
    elif refs:
        r.add("operations", "skip", "needs the OpenAPI")

    # 8. status shape
    if m.run.status:
        if not live:
            r.add("status", "skip", "not running")
        else:
            st, problems = await status_mod.fetch(mgr, svc)
            if st is None:
                r.add("status", "fail", "; ".join(problems))
            elif problems:
                r.add("status", "fail", "; ".join(problems))
            else:
                r.add("status", "ok", f"{len(st['stats'])} stats, {len(st['jobs'])} jobs, loaded={st['loaded']}")

    # 9. widgets
    for w in m.ui.widgets:
        name = f"widget {w.id}"
        if not live:
            r.add(name, "skip", "not running")
            continue
        method, path = w.source.split(" ", 1)
        rng = w.ranges[0] if w.ranges else "24h"
        try:
            resp = await mgr.client.request(method, svc.url + path, params={"range": rng}, timeout=10)
        except httpx.HTTPError as e:
            r.add(name, "fail", f"{w.source}: {type(e).__name__}")
            continue
        if not 200 <= resp.status_code < 300:
            r.add(name, "fail", f"{w.source}?range={rng}: HTTP {resp.status_code}")
            continue
        try:
            data = resp.json()
        except ValueError:
            r.add(name, "fail", f"{w.source}: not JSON")
            continue
        problems = widget_problems(data, w.kind)
        r.add(name, "fail" if problems else "ok", "; ".join(problems) if problems else f"{w.kind} with {len(data.get('series', []))} series")

    # 10. agent tools: their schemas and `x-options` (plan 20.1)
    if tools is not None and (m.tools or m.agent.tools_source) and live:
        from utils.tools.options import spec_problems

        defs = await tools()
        bad = [f"{t.name}: {p}" for t in defs for p in [*t.problems, *spec_problems(t.parameters)]]
        r.add("tools", "fail" if bad else "ok", "; ".join(bad[:8]) if bad else f"{len(defs)} tools")

    # 11. page
    if m.ui.page:
        r.add("page", *page_check(svc.mod.dir / m.ui.page))

    # 11b. the chat module (plan 44.1)
    if m.ui.chat:
        r.add("chat", *chat_check(svc.mod.dir / m.ui.chat))

    # 12. the GPU slot (plan 31.2)
    gpu = gpu_check(m, svc.status if live else None)
    if gpu:
        r.add("gpu", *gpu)
    return r.as_dict()


GPU_WORDS = re.compile(r"cuda|rocm|hip|gpu|vulkan|mps|xpu", re.I)


def _devices(body: Any, depth: int = 0) -> list[str]:
    """Every `device` string in a status body (a few levels deep)."""
    if depth > 3:
        return []
    if isinstance(body, dict):
        out = [v for k, v in body.items() if k == "device" and isinstance(v, str)]
        return out + [d for v in body.values() for d in _devices(v, depth + 1)]
    if isinstance(body, list):
        return [d for v in body[:20] for d in _devices(v, depth + 1)]
    return []


def gpu_check(m: mf.Manifest, status: Any) -> tuple[str, str] | None:
    """A mod with `[memory]` (it loads models) and no `[gpu]` doesn't wait for the GPU slot: a warning, unless
    its status says it runs on the CPU."""
    if m.gpu:
        return "ok", f"takes the GPU slot: class {m.gpu.cls}, group {m.gpu.group or m.id}"
    if not m.memory:
        return None
    devices = _devices(status)
    if devices and not any(GPU_WORDS.search(d) for d in devices):
        return "ok", f"runs on {', '.join(sorted(set(devices)))}: no GPU slot needed"
    seen = f" (its status says device {', '.join(sorted(set(devices)))})" if devices else ""
    return "warn", (f"loads models but has no [gpu]{seen}: its GPU work doesn't wait for other mods' work. Take the slot "
                    "around it (docs/mods.md \"Taking the GPU\") and add [gpu] class = \"job\" to service.toml")


def _manifest_ops(m: mf.Manifest) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if m.memory:
        for key in ("load", "unload"):
            if getattr(m.memory, key):
                refs.append((f"[memory].{key}", getattr(m.memory, key)))
        refs += [("[memory].triggers", t) for t in m.memory.triggers]
    refs += [(f"[tools].{name}", t.op) for name, t in m.tools.items()]
    if m.agent.tools_source:
        refs.append(("[agent].tools_source", m.agent.tools_source))
    refs += [(f"[ui.widgets].{w.id}", w.source) for w in m.ui.widgets]
    return refs


def widget_problems(data: Any, kind: str) -> list[str]:
    """WidgetData (brief §11.7): {unit?, t?, categories?, series: [{name, values}], rows?}."""
    if not isinstance(data, dict):
        return ["WidgetData must be a JSON object"]
    out: list[str] = []
    if kind == "table":
        rows = data.get("rows")
        if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
            out.append("a table widget needs rows: [{column: value}, …]")
        return out
    series = data.get("series")
    if not isinstance(series, list) or not series:
        return ["series must be a non-empty list of {name, values}"]
    t, cats = data.get("t"), data.get("categories")
    if kind in WIDGET_KINDS_WITH_T and t is None and cats is None:
        out.append(f"a {kind} widget needs t (unix seconds) or categories")
    axis = t if t is not None else cats
    if axis is not None and not isinstance(axis, list):
        out.append("t / categories must be a list")
        axis = None
    for i, s in enumerate(series):
        if not isinstance(s, dict) or not isinstance(s.get("name"), str):
            out.append(f"series[{i}] needs a name")
            continue
        vals = s.get("values")
        if not isinstance(vals, list) or not all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)) for v in vals):
            out.append(f"series[{i}] ({s['name']}): values must be numbers or null")
        elif axis is not None and len(vals) != len(axis):
            out.append(f"series[{i}] ({s['name']}): {len(vals)} values for {len(axis)} points")
    return out


def chat_check(path: Path) -> tuple[str, str]:
    """`[ui] chat`: the file exists and exports `setup(chat)` as its default."""
    if not path.is_file():
        return "fail", f"{path.name} is declared in [ui] chat but doesn't exist"
    text = path.read_text(errors="replace")
    if not re.search(r"export\s+default\b", text):
        return "fail", f"{path.name} has no `export default function setup(chat)`"
    return "ok", f"{path.name}: a chat module"


def page_check(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "fail", f"{path.name} is declared in [ui] page but doesn't exist"
    text = path.read_text(errors="replace")
    if path.name.endswith(".dc.html"):
        return ("ok", "Page.dc.html component") if "<x-dc>" in text else ("fail", f"{path.name} has no <x-dc> template")
    problems = []
    if not re.search(r"export\s+default\b", text):
        problems.append("no `export default { tabs, mount }`")
    if not re.search(r"\bmount\s*\(", text):
        problems.append("no mount(el, ctx)")
    if not re.search(r"\btabs\s*:", text):
        problems.append("no tabs: [...] (a single 'Page' tab is used)")
    if re.search(r"\bfetch\s*\(", text):
        problems.append("calls fetch(); use ctx.call / ctx.api so it works with the hub and the mock")
    if not problems:
        return "ok", f"{path.name} exports tabs and mount"
    hard = [p for p in problems if not p.startswith("no tabs") and not p.startswith("calls fetch")]
    return ("fail" if hard else "warn"), "; ".join(problems)
