"""A `Service` as the UI sees it: `ServiceSummary` and `ServiceDetail` (brief §6.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.services import Service, ServiceManager

GB = 1024**3


def summary(mgr: ServiceManager, svc: Service) -> dict[str, Any]:
    m = svc.m
    estimate_gb = svc.memory_estimate_gb if svc.memory_estimate_gb is not None else (m.memory.estimate_gb if m and m.memory else None)
    native = m.ui.native if m else None
    if native and native.startswith("/"):
        native = svc.url + native
    return {
        "id": svc.id,
        "name": svc.mod.name,
        "description": m.description if m else str(svc.mod.raw.get("description") or ""),
        "icon": m.icon if m else "box",
        "version": m.version if m else None,
        "kind": m.run.kind if m else "process",
        "port": svc.port,
        "url": svc.url,
        "state": svc.state,
        "state_since": svc.state_since,
        "load": svc.load,
        "idle_s": svc.idle_s,
        "busy": svc.busy,
        "memory": {
            "used_bytes": mgr.memory.used.get(svc.id, 0) if mgr.memory else 0,
            "estimate_bytes": round(estimate_gb * GB) if estimate_gb is not None else None,
            "peak_bytes": mgr.memory.peaks.get(svc.id) if mgr.memory else None,
        },
        "stats": svc.stats,
        "has_page": has_page(svc),
        "page_url": page_url(svc),
        "has_outputs": bool(m and m.outputs),
        "native_ui": native,
        "enabled": svc.eff.enabled,
        "autostart": svc.eff.autostart,
        "last_error": svc.last_error,
        "manifest_errors": svc.errors,
    }


def detail(mgr: ServiceManager, svc: Service) -> dict[str, Any]:
    out = summary(mgr, svc)
    out.update(
        {
            "pid": svc.pid,
            "started_ts": svc.started_ts,
            "command": svc.command or mgr._command(svc),
            "folder": mgr.paths.rel(svc.mod.dir) if _inside(mgr, svc) else str(svc.mod.dir),
            "outputs_dir": mgr.paths.rel(mgr.paths.outputs / svc.id) if svc.m and svc.m.outputs else None,
            "models": mgr.registry.used_by(svc.id) if mgr.registry else [],  # registry ids (plan 3.4)
            "health": svc.health,
            "manifest": svc.mod.raw,
            "config": svc.eff.as_dict(),
            "jobs": svc.jobs,
            "in_flight": svc.in_flight,
            "last_request_ts": svc.last_request_ts,
        }
    )
    return out


def page_url(svc: Service) -> str | None:
    """Where the shell loads the page: a page module, or a `Page.dc.html` under `/Mod_<id>.dc.html`."""
    if not has_page(svc):
        return None
    page = svc.m.ui.page  # type: ignore[union-attr]
    if page.endswith(".dc.html"):
        return f"/Mod_{svc.id}.dc.html"
    return f"/ui/services/{svc.id}/{page.removeprefix('ui/')}"


def has_page(svc: Service) -> bool:
    m = svc.m
    return bool(m and m.ui.page and (svc.mod.dir / m.ui.page).is_file())


def _inside(mgr: ServiceManager, svc: Service) -> bool:
    try:
        svc.mod.dir.relative_to(mgr.paths.root)
        return True
    except ValueError:
        return False
