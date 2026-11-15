"""6.6 and 6.7: the UI contract against the hub itself.

- Every method `web/api.js` calls over HTTP maps to a hub route with that HTTP method.
- The response models match the brief's §6.4 and §11.7 types field for field.
- Every `/api/…` route in `/api/openapi.json` has a summary and a documented response, so the
  spec describes the whole hub (Phase 13 builds the agent's hub tools from it).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from utils import api_models as am
from utils.routes import repos as rr
from utils.routes import sessions as rs
from utils.tools import api as ta
from utils.tests.conftest import REPO

API_JS = (REPO / "web" / "api.js").read_text()
BRIEF = (REPO / "docs" / "design-brief-ui.md").read_text()
_CALL = re.compile(r"""(?:req|send)\(\s*'([A-Z]+)'\s*,\s*[`'"]([^`'"]+)[`'"]""")
_STREAM = re.compile(r"""stream\(\s*[`'"]([^`'"]+)[`'"]""")
_ANY = re.compile(r"""send\(\s*method\s*,\s*`([^`]+)`""")
_URL = re.compile(r"""=>\s*url\(\s*`([^`]+)`""")  # URL builders (outputPageUrl): plain GETs


def _norm(path: str) -> str:
    """`/api/services/${enc(id)}/logs${qs(...)}` and `/api/services/{service_id}/logs` → `/api/services/{}/logs`."""
    path = re.sub(r"\$\{qs\(.*?\)\}", "", path)  # query strings
    path = re.sub(r"\$\{[^}]*$", "", path)  # an expression cut off at a quote: `${makeRoom ? '?make_room=1' : ''}`
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.rstrip("/") or "/"


def js_routes() -> set[tuple[str, str]]:
    body = API_JS[API_JS.index("export function createHttpApi"):API_JS.index("export function createApi")]
    out = {(m, _norm(p)) for m, p in _CALL.findall(body)}
    out |= {("GET", _norm(p)) for p in _STREAM.findall(body)}
    out |= {("ANY", _norm(p)) for p in _ANY.findall(body)}
    out |= {("GET", _norm(p)) for p in _URL.findall(body)}
    return out


def test_js_parser_sees_every_method():
    routes = js_routes()
    assert ("GET", "/api/services/{}/logs") in routes and ("GET", "/api/events") in routes
    assert ("DELETE", "/api/models/{}") in routes and ("PUT", "/api/settings") in routes
    # the proxy call is `send(method, `/api/s/${enc(id)}${p}${qs(query)}`)`: any method
    assert ("ANY", "/api/s/{}{}") in routes
    # plan 24.3: the document calls, and the page image URL builder
    assert {("GET", "/api/outputs/{}/text"), ("GET", "/api/outputs/{}/search"), ("GET", "/api/outputs/{}/page/{}.png")} <= routes
    names = set(re.findall(r"^\s{4}(?:async\s+)?(\w+)(?::|\()", API_JS[API_JS.index("return {", API_JS.index("export function createHttpApi")):API_JS.index("export function createApi")], re.M))
    assert len(routes) >= len(names) - 2  # every method has a route (callService and subscribe included)


async def test_every_api_js_route_exists(client):
    spec = (await client.get("/api/openapi.json")).json()
    have = {(m.upper(), _norm(p)) for p, ops in spec["paths"].items() for m in ops}
    missing = []
    for method, path in sorted(js_routes()):
        if method == "ANY":
            # the proxy: any method on /api/s/{id}/… (left out of the spec): ask it directly
            for m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                r = await client.request(m, "/api/s/nope/x")
                assert r.json()["code"] == "service_not_found", m
            continue
        if (method, path) not in have:
            missing.append(f"{method} {path}")
    assert not missing, f"api.js calls routes the hub doesn't have: {missing}"


# ---- response models vs the brief's TypeScript ----

# brief interface → the pydantic model the hub answers with
MODELS: dict[str, type[BaseModel]] = {
    "Stat": am.Stat, "ServiceSummary": am.ServiceSummary, "Availability": am.Availability, "AvailabilityFix": am.AvailabilityFix, "ServiceDetail": am.ServiceDetail, "ServiceConfig": am.ServiceConfig,
    "Operation": am.Operation, "Memory": am.SystemMemory, "MakeRoomPlan": am.MakeRoomPlan, "Model": am.Model,
    "Discovered": am.Discovered, "Totals": am.ModelTotals, "Disk": am.Disk, "Output": am.Output, "OutputPage": am.OutputPage,
    "OutputText": am.OutputText, "OutputSearch": am.OutputSearch, "OutlineItem": am.OutlineItem, "SearchHit": am.SearchHit,
    "Activity": am.Activity, "Alert": am.Alert, "Job": am.Job, "System": am.SystemInfo, "Overview": am.Overview,
    "Settings": am.Settings, "LogLine": am.LogLine, "Metrics": am.Metrics, "SeriesInfo": am.SeriesInfo,
    "Timeline": am.Timeline, "OutputBucket": am.OutputBucket, "WidgetInfo": am.WidgetInfo, "WidgetData": am.WidgetData,
    "Doctor": am.Doctor, "DoctorCheck": am.DoctorCheck, "Hardware": am.Hardware, "HardwareGpu": am.HardwareGpu,
    "Repos": rr.Repos, "RepoState": rr.RepoState, "RepoProblem": rr.RepoProblem, "RepoUpdate": rr.RepoUpdate,   # plan mod-repos 3.5
    "ToolIndexItem": ta.ToolIndexItem, "Tool": ta.Tool, "ToolOutput": ta.ToolOutput, "ToolCallResult": ta.ToolCallResult,
    "Approval": ta.Approval, "Grant": ta.Grant,
    "Session": rs.Session, "SessionStep": rs.SessionStep, "SessionMemory": rs.SessionMemory, "SessionRestore": rs.Restore,
    "SessionState": rs.SessionState,
}
# fields the hub adds beyond the brief, on purpose. Job's GPU fields (plan 31.3): until brief §6.4's Job lists them
EXTRA: dict[str, set[str]] = {"Job": {"stage", "ahead", "eta_s"}}


def _interfaces(text: str) -> dict[str, tuple[str | None, str]]:
    """`interface Name (extends Base)? { body }` → {name: (base, body)}, with nested braces matched."""
    text = re.sub(r"//[^\n]*", "", text)
    out = {}
    for m in re.finditer(r"interface (\w+)(?: extends (\w+))?\s*\{", text):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out[m[1]] = (m[2], text[m.end():i - 1])
    return out


def _fields(body: str) -> set[str]:
    """Top-level field names of an interface body."""
    names, depth, token = set(), 0, ""
    for ch in body:
        if ch in "{(<[":
            depth += 1
        elif ch in "})>]":
            depth -= 1
        if depth == 0 and ch == ":" and token.strip():
            names.add(token.strip().split()[-1].rstrip("?").strip('"'))
            token = ""
        elif depth == 0 and ch in ";\n,":
            token = ""
        elif depth == 0 and ch != ":":
            token += ch
    return names


def _brief_fields(name: str, ifaces: dict[str, tuple[str | None, str]]) -> set[str]:
    base, body = ifaces[name]
    return _fields(body) | (_brief_fields(base, ifaces) if base else set())


def _model_fields(model: type[BaseModel]) -> set[str]:
    return {f.alias or n for n, f in model.model_fields.items()}


def test_response_models_match_the_brief():
    ifaces = _interfaces(BRIEF)
    assert set(MODELS) <= set(ifaces), set(MODELS) - set(ifaces)
    diffs = {}
    for name, model in MODELS.items():
        want, have = _brief_fields(name, ifaces), _model_fields(model) - EXTRA.get(name, set())
        if want != have:
            diffs[name] = {"brief only": sorted(want - have), "hub only": sorted(have - want)}
    assert not diffs, diffs


# ---- 6.7: the spec documents every hub route ----


def _documented(op: dict[str, Any]) -> bool:
    ok = {k: v for k, v in op["responses"].items() if k.startswith("2")}
    if not ok:
        return False
    for code, resp in ok.items():
        if code == "204":
            continue
        content = resp.get("content") or {}
        if not content:
            return False
        for ctype, media in content.items():
            schema = media.get("schema") or {}
            if ctype != "application/json":
                continue  # files, images and event streams: the content type is the documentation
            target = schema.get("items", schema)
            if "$ref" not in target:
                return False
    return True


async def test_every_route_has_a_summary_and_a_response_model(client):
    spec = (await client.get("/api/openapi.json")).json()
    bad = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, op in ops.items():
            if not op.get("summary"):
                bad.append(f"{method.upper()} {path}: no summary")
            if not _documented(op):
                bad.append(f"{method.upper()} {path}: no response model")
    assert not bad, bad
    assert "/api/s/{id}" in spec["info"]["description"]  # where the mods' own APIs are
