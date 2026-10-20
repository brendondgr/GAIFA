"""The hub's own tools (plan 13.1), all `core`: mods, memory, outputs, models and calls; the
reading tools (plan 24.4) are in `doc_tools.py`.

Each handler takes `(hub, args)` and returns JSON. Results name things (mod names, titles) rather
than only ids, and stay small: the agent pages with `limit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.outputs.entries import KINDS
from utils.services import loading
from utils.tools import doc_tools
from utils.tools.catalog import ToolDef

if TYPE_CHECKING:
    from utils.server import Hub

GB = 1e9


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = required
    return s


SERVICE = {"type": "string", "description": "A mod id, e.g. tts, gen3d, comfy, lcpp (hub_list_services lists them)"}


async def list_services(hub: Hub, args: dict[str, Any]) -> Any:
    out = []
    for s in hub.services.list():
        out.append({"id": s.id, "name": s.mod.name, "description": s.m.description if s.m else "", "state": s.state,
                    "load": s.load, "busy": s.busy, "jobs": [{"label": j.get("label"), "state": j.get("state"),
                                                             "progress": j.get("progress")} for j in s.jobs[:3]]})
    return {"services": out}


async def start_service(hub: Hub, args: dict[str, Any]) -> Any:
    svc = await hub.services.start(args["id"], wait=True)
    return {"id": svc.id, "state": svc.state, "error": svc.last_error} if svc.last_error else {"id": svc.id, "state": svc.state}


async def stop_service(hub: Hub, args: dict[str, Any]) -> Any:
    svc = await hub.services.stop(args["id"], wait=True)
    return {"id": svc.id, "state": svc.state}


async def unload_service(hub: Hub, args: dict[str, Any]) -> Any:
    svc = await loading.unload(hub.services, args["id"])
    return {"id": svc.id, "load": svc.load}


async def memory_status(hub: Hub, args: dict[str, Any]) -> Any:
    m = hub.memory.view() if hub.memory and hub.memory.snapshot else await hub.memory.sample(publish=False)
    names = {s.id: s.mod.name for s in hub.services.list()}
    return {"total_gb": round(m["total_bytes"] / GB, 1), "used_gb": round(m["used_bytes"] / GB, 1),
            "available_gb": round(m["available_bytes"] / GB, 1), "reserve_gb": round(m["reserve_bytes"] / GB, 1),
            "by_service": [{"id": s["id"], "name": names.get(s["id"], s["id"]), "used_gb": round(s["used_bytes"] / GB, 1),
                            "estimate_gb": round(s["estimate_bytes"] / GB, 1) if s.get("estimate_bytes") else None,
                            "load": s["load"]} for s in m["by_service"]]}


def output_brief(o: dict[str, Any]) -> dict[str, Any]:
    meta = o.get("meta") or {}
    out = {"output_id": o["id"], "ref": f"output:{o['id']}", "kind": o["kind"], "title": o["title"],
           "service": o["service"], "url": o["url"], "created_ts": round(o["created_ts"])}
    if meta.get("prompt"):
        out["prompt"] = str(meta["prompt"])[:300]
    if o.get("dims"):
        out["dims"] = o["dims"]
    if o.get("duration_s"):
        out["duration_s"] = round(o["duration_s"], 1)
    return out


async def search_outputs(hub: Hub, args: dict[str, Any]) -> Any:
    page = await hub.outputs.list(service=args.get("service"), kind=args.get("kind"), q=args.get("q"),
                                  limit=int(args.get("limit") or 10))
    return {"outputs": [output_brief(o) for o in page["items"]], "total": page["totals"]["count"]}


async def get_output(hub: Hub, args: dict[str, Any]) -> Any:
    oid = str(args["id"]).removeprefix("output:")
    o = await hub.outputs.get(oid)
    out = output_brief(o)
    out["meta"] = {k: v for k, v in (o.get("meta") or {}).items() if k not in ("title",)}
    out["files"] = [f.get("path") for f in o.get("files") or []][:20]
    return out


async def list_models(hub: Hub, args: dict[str, Any]) -> Any:
    reg = hub.registry.list(kind=args.get("kind"), q=args.get("q"))
    return {"models": [{"id": m["id"], "name": m.get("name") or m["id"], "kind": m["kind"], "status": m["status"],
                        "size_gb": round((m.get("size_bytes") or 0) / GB, 1), "used_by": m.get("services") or []}
                       for m in reg["models"][: int(args.get("limit") or 30)]], "total": reg["totals"]["count"]}


async def save_session(hub: Hub, args: dict[str, Any]) -> Any:
    s = await hub.sessions.save(args["name"])
    return {"id": s["id"], "name": s["name"], "summary": s["summary"]}


async def list_sessions(hub: Hub, args: dict[str, Any]) -> Any:
    return {"sessions": [{"id": s["id"], "name": s["name"], "auto": s["auto"], "summary": s["summary"],
                          "saved": round(s["updated_ts"])} for s in await hub.sessions.list()]}


async def restore_session(hub: Hub, args: dict[str, Any]) -> Any:
    r = await hub.sessions.restore(args["name"], dry_run=bool(args.get("dry_run")))
    return {"steps": [s["detail"] for s in r["steps"]], "fits": r["memory"]["fits"], "ok": r.get("ok"),
            "problems": [f"{x['detail']}: {x.get('error')}" for x in r.get("results") or [] if not x["ok"]]}


async def job_status(hub: Hub, args: dict[str, Any]) -> Any:
    return await hub.calls.status(args["call_id"], wait=float(args.get("wait") or 0))


async def set_preference(hub: Hub, args: dict[str, Any]) -> Any:
    """A preference the user stated (plan 21.4): saved active, applied to that tool's cards from now on."""
    from utils.prefs import PrefError
    from utils.tools.modcall import ToolError

    body = {"source": "stated", "state": "active", "value": args.get("value"), "cue": args.get("cue") or ""}
    if args.get("tool"):
        body.update(tool=args["tool"], field=args.get("field"), when=args.get("when") or {})
    try:
        p = await hub.prefs.create(body)
    except PrefError as e:
        raise ToolError(e.code, e.detail, "check the tool's parameters (load it first) and use one of its allowed values") from None
    return {"saved": {k: p[k] for k in ("id", "scope", "tool", "field", "value", "when")}}


async def list_preferences(hub: Hub, args: dict[str, Any]) -> Any:
    rows = await hub.prefs.list(state="active", tool=args.get("tool"))
    return {"preferences": [{k: r[k] for k in ("id", "scope", "tool", "field", "value", "when", "source")} for r in rows
                            if r["scope"] != "thread"][:50]}


def tools() -> list[ToolDef]:
    def t(name: str, desc: str, params: dict[str, Any], fn: Any, risk: str = "read", cap: int | None = None) -> ToolDef:
        return ToolDef(f"hub_{name}", None, name, desc, params, risk=risk, core=True, source="hub", handler=fn, cap_bytes=cap)

    kinds = {"type": "string", "enum": list(KINDS)}
    return [
        t("list_services", "List AIHub's mods (speech, 3D, images & video, LLMs…) with their state, whether their models "
          "are loaded, and running jobs.", _obj({}), list_services),
        t("start_service", "Start a mod's process (models load later, on first use).", _obj({"id": SERVICE}, ["id"]),
          start_service, "write"),
        t("stop_service", "Stop a mod's process; its running jobs are cancelled.", _obj({"id": SERVICE}, ["id"]),
          stop_service, "destructive"),
        t("unload_service", "Unload a mod's models from memory, keeping it running.", _obj({"id": SERVICE}, ["id"]),
          unload_service, "write"),
        t("memory_status", "Memory now: total, used and free (GB), and what each mod holds.", _obj({}), memory_status),
        t("search_outputs", "Find earlier outputs (images, videos, audio, 3D models, text, documents) by words, kind or mod, newest first.",
          _obj({"q": {"type": "string", "description": "Words in the title or prompt"}, "kind": kinds, "service": SERVICE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}), search_outputs),
        t("get_output", "One output's details: title, kind, prompt, settings and files.",
          _obj({"id": {"type": "string", "description": "The output id, or output:<id>"}}, ["id"]), get_output),
        *(t(name, desc, _obj(props, ["ref", "query"] if name == "search_document" else ["ref"]), fn, cap=doc_tools.CAP_BYTES)
          for name, desc, props, fn in doc_tools.specs()),
        t("list_models", "The models on disk (registry): kind, size, status and which mods use them.",
          _obj({"kind": {"type": "string"}, "q": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}}), list_models),
        t("save_session", "Save what runs and what's loaded now as a named session (e.g. 'LLM work').",
          _obj({"name": {"type": "string"}}, ["name"]), save_session, "write"),
        t("list_sessions", "The saved sessions (named setups) with what each has running and loaded.", _obj({}), list_sessions),
        t("restore_session", "Switch to a saved session: stops, unloads, starts and loads mods to match it (through the "
          "memory manager). dry_run shows the steps only.",
          _obj({"name": {"type": "string", "description": "The session's name or id"}, "dry_run": {"type": "boolean", "default": False}},
               ["name"]), restore_session, "write"),
        t("set_preference", "Save a lasting preference the user states (\"always use the fast preset for 3D\", \"I prefer 16:9\"): "
          "for a tool's setting give tool, field and value (one of that parameter's allowed values); for anything else give "
          "only value, as a short sentence. It applies to that tool's cards from now on, marked as the user's preference.",
          _obj({"tool": {"type": "string", "description": "The tool, e.g. gen3d_make_3d"},
                "field": {"type": "string", "description": "The parameter, e.g. preset"},
                "value": {"description": "The value, or a sentence when there is no tool"},
                "when": {"type": "object", "description": "Optional: other arguments it depends on, e.g. {\"image\": \"present\"}"},
                "cue": {"type": "string", "description": "When it applies, in a few words"}}, ["value"]), set_preference, "write"),
        t("list_preferences", "The user's saved preferences (active), optionally for one tool.",
          _obj({"tool": {"type": "string"}}), list_preferences),
        t("job_status", "The state of an earlier tool call that is still running (by its call_id), with its result when done.",
          _obj({"call_id": {"type": "string"}, "wait": {"type": "number", "minimum": 0, "maximum": 600,
                                                         "description": "Seconds to wait for it to finish"}}, ["call_id"]),
          job_status),
    ]
