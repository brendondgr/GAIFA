"""Hub tools for status and fixing things (plan 46.2): the GPU queue, the install checks, and freeing the GPU.
Their results draw as status cards in Chat (web/chat/status/)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.services import loading

if TYPE_CHECKING:
    from utils.server import Hub

GB = 1e9
LLM_ENGINES = ("lcpp", "vllm")      # they may be serving the chat's own model: freed only when named


async def gpu_status(hub: Hub, args: dict[str, Any]) -> Any:
    """Who holds the GPU slot and who waits, with their times."""
    v = hub.gpu.view()
    names = {s.id: s.mod.name for s in hub.services.list()}

    def lease(x: dict[str, Any]) -> dict[str, Any]:
        out = {k: x.get(k) for k in ("id", "service", "label", "state", "elapsed_s", "eta_s", "waited_s") if x.get(k) is not None}
        out["name"] = names.get(x.get("service"), x.get("service"))
        return out

    holder = v.get("holder") or {}
    return {"queue": v.get("queue"), "holder": [lease(x) for x in holder.get("leases") or []],
            "waiting": [lease(x) for x in v.get("waiting") or []],
            "recent": [lease(x) for x in (v.get("recent") or [])[:5]]}


async def doctor(hub: Hub, args: dict[str, Any]) -> Any:
    """`aihub doctor`'s checks: the problems first, each with its fix; the passing ones counted."""
    from utils import doctor as doc

    r = await doc.run(hub)
    order = {"fail": 0, "warn": 1, "note": 2, "ok": 3}
    checks = sorted(r["checks"], key=lambda c: order.get(c["level"], 9))
    return {"ok": r["ok"], "counts": r["counts"], "checks": [c for c in checks if c["level"] != "ok"][:40],
            "passed": [c.get("title") or c.get("area") for c in checks if c["level"] == "ok"][:60]}


async def free_gpu(hub: Hub, args: dict[str, Any]) -> Any:
    """Unload what holds memory: the mods named, or every loaded one but the LLM engines (unless named)."""
    want = set(args.get("services") or [])
    mem = hub.memory.view() if hub.memory and hub.memory.snapshot else await hub.memory.sample(publish=False)
    held = {s["id"]: s["used_bytes"] for s in mem.get("by_service", [])}
    freed, kept, failed = [], [], []
    for svc in hub.services.list():
        if want and svc.id not in want:
            continue
        if svc.load not in ("loaded", "loading") or svc.state not in ("ready", "degraded"):
            continue
        if not want and svc.id in LLM_ENGINES:
            kept.append({"id": svc.id, "name": svc.mod.name, "why": "an LLM engine (it may be serving this chat): name it to unload it"})
            continue
        try:
            ok = await loading.unload_now(hub.services, svc, "freed from Chat")
        except Exception as e:  # noqa: BLE001 - reported per mod
            ok, err = False, str(e)[:200]
        else:
            err = svc.last_error or "it didn't unload"
        if ok:
            freed.append({"id": svc.id, "name": svc.mod.name, "gb": round(held.get(svc.id, 0) / GB, 1)})
        else:
            failed.append({"id": svc.id, "name": svc.mod.name, "error": err})
    unknown = sorted(want - {s.id for s in hub.services.list()})
    return {"freed": freed, "freed_gb": round(sum(f["gb"] for f in freed), 1), "kept": kept, "failed": failed,
            **({"unknown": unknown} if unknown else {})}


def specs(obj: Any, service: dict[str, Any]) -> list[tuple[str, str, dict[str, Any], Any, str]]:
    """(name, description, parameters, handler, risk) for hub_tools.tools()."""
    return [
        ("gpu_status", "The GPU slot now: which job holds it, what waits and how long, and the last few that ran.", obj({}), gpu_status, "read"),
        ("doctor", "Check the whole install (aihub doctor): models on disk, manifests, ports, units, disk, offline mods; "
         "problems first, each with its fix.", obj({}), doctor, "read"),
        ("free_gpu", "Free memory: unload the named mods' models, or every loaded mod's except the LLM engines (lcpp, vllm: "
         "name them to unload them too). Running jobs of an unloaded mod stop.",
         obj({"services": {"type": "array", "items": service, "description": "Mod ids to unload; empty: every loaded one but the LLM engines"}}),
         free_gpu, "write"),
    ]
