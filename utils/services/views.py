"""A `Service` as the UI sees it: `ServiceSummary` and `ServiceDetail` (brief §6.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.services.status import slug

if TYPE_CHECKING:
    from utils.services import Service, ServiceManager

GB = 1000**3  # decimal GB, as the UI shows it (and config, manifests and status use)


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
        "stats": [_with_series(svc.id, st) for st in svc.stats],
        "has_page": has_page(svc),
        "page_url": page_url(svc),
        "logo_url": logo_url(svc),
        "chat_url": chat_url(svc),
        "badge": mgr.badges.get(svc.id) or None,
        "main": m.ui.main.model_dump() if m and m.ui.main and has_page(svc) else None,
        "chat_panel": chat_panel(svc),
        "has_outputs": bool(m and m.outputs),
        "native_ui": native,
        "enabled": svc.eff.enabled,
        "autostart": svc.eff.autostart,
        "last_error": svc.last_error,
        "accel": svc.eff.accel,
        "unavailable": mgr.unavailable(svc),
        "manifest_errors": svc.errors,
    }


def _with_series(sid: str, st: dict[str, Any]) -> dict[str, Any]:
    """A numeric stat names the metric it is recorded as (brief §11.7), for tile sparklines."""
    v = st.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return {**st, "series": f"svc.{sid}.stat.{slug(st['label'])}"}
    return st


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


def chat_url(svc: Service) -> str | None:
    """The mod's chat module (plan 44.1): `[ui] chat`, served from its `ui/` folder; null without one (or a missing file)."""
    m = svc.m
    if not (m and m.ui.chat and (svc.mod.dir / m.ui.chat).is_file()):
        return None
    return f"/ui/services/{svc.id}/{m.ui.chat.removeprefix('ui/')}"


def chat_panel(svc: Service) -> dict[str, str] | None:
    """The mod's side panel in Chat (calendar 7.1): `{label, url}`; null without one (or a missing file)."""
    m = svc.m
    p = m.ui.chat_panel if m else None
    if not (p and (svc.mod.dir / p.module).is_file()):
        return None
    return {"label": p.label, "url": f"/ui/services/{svc.id}/{p.module.removeprefix('ui/')}"}


def logo_url(svc: Service) -> str | None:
    """The mod's logo (plan 33.1): `[ui] logo`, else `ui/logo.svg` when it exists; served from its `ui/` folder."""
    m = svc.m
    rel = (m.ui.logo if m else None) or "ui/logo.svg"
    if not (svc.mod.dir / rel).is_file():
        return None
    return f"/ui/services/{svc.id}/{rel.removeprefix('ui/')}"


def has_page(svc: Service) -> bool:
    m = svc.m
    return bool(m and m.ui.page and (svc.mod.dir / m.ui.page).is_file())


def _inside(mgr: ServiceManager, svc: Service) -> bool:
    try:
        svc.mod.dir.relative_to(mgr.paths.root)
        return True
    except ValueError:
        return False
