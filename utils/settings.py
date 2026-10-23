"""The Settings page (brief §6.4 `Settings`, plan 6.3): `config.toml` as the UI sees it, and saving it.

A save may send the whole `Settings` or any part; what is left out stays as it is. Only real
overrides are written: a value equal to AIHub's default removes its key, so saving the whole
form doesn't pin every default into `config.toml` (comments and order survive, via tomlkit).
An unchanged value is never rewritten. Everything applies at once except the hub's port, which needs a restart (`restart_required`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from utils import config as config_mod
from utils.api_models import Settings
from utils.services.model import ServiceError

if TYPE_CHECKING:
    from utils.server import Hub

GB = 1000**3
DEFAULTS = config_mod.Config()
MOD_DEFAULTS = {"enabled": True, "autostart": True}  # manifest.effective()'s defaults


def view(hub: Hub) -> dict[str, Any]:
    cfg = hub.config
    svcs = hub.services.list() if hub.services else []
    # Every installed mod appears in `order` and `priority` (the page reorders what it is given):
    # the configured ids first, then the rest in sidebar order. Unchanged, nothing is written.
    rest = lambda ids: list(ids) + [s.id for s in svcs if s.id not in ids]  # noqa: E731
    return {
        "hub": {"port": cfg.hub.port},
        "memory": {"reserve_gb": cfg.memory.reserve_gb, "auto_make_room": cfg.memory.auto_make_room,
                   "never_unload": list(cfg.memory.never_unload), "priority": rest(cfg.memory.priority)},
        "services": {"order": rest(cfg.services.order),
                     "enabled": {s.id: s.eff.enabled for s in svcs},
                     "autostart": {s.id: s.eff.autostart for s in svcs}},
        "ui": {"theme": cfg.ui.theme, "density": cfg.ui.density, "dashboard": cfg.ui.dashboard.model_dump(),
               "nav": cfg.ui.nav.model_dump()},
        "learning": cfg.learning.model_dump(),
        "speech_input": cfg.speech_input.model_dump(),
        "speech_output": cfg.speech_output.model_dump(),   # plan 49.1
        "judge": cfg.agent.judge.model_dump(),      # config.toml [agent.judge] (plan 30.3)
        "screen": cfg.agent.screen.model_dump(),    # [agent.screen] (plan 30.6)
        "permissions": cfg.agent.permissions.model_dump(),   # [agent.permissions]: tool-name globs (plan 13.2)
        "web": cfg.agent.web.model_dump(),          # [agent.web]: a long page's relevant passages first (webread.py)
        "outputs": cfg.outputs.model_dump(),        # [outputs]: saved web pages' clean-up (plan 30.9)
    }


def _invalid(detail: str, field: str | None = None) -> ServiceError:
    return ServiceError(422, "invalid_config", detail, {"field": field} if field else None)


def _merge(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(current)
    for section, values in patch.items():
        if values is None:
            continue
        if not isinstance(values, dict):
            raise _invalid(f"{section}: must be an object", section)
        merged = dict(out.get(section) or {})
        for key, value in values.items():
            if section == "services" and key in ("enabled", "autostart") and isinstance(value, dict):
                merged[key] = {**merged.get(key, {}), **value}  # per mod: the ones sent change
            else:
                merged[key] = value
        out[section] = merged
    return out


def _or_default(value: Any, default: Any) -> Any:
    return None if value == default else value


async def save(hub: Hub, patch: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    before = view(hub)
    running = hub.port
    try:
        new = Settings.model_validate(_merge(before, patch)).model_dump()
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(p) for p in err["loc"])
        raise _invalid(str(err["msg"]), field) from None  # data.field names the field
    mgr = hub.services
    known = {s.id for s in mgr.list()}
    for key in ("enabled", "autostart"):
        unknown = sorted(set(new["services"][key]) - known)
        if unknown:
            raise _invalid(f"No mod {unknown[0]!r}", f"services.{key}")
    gb = new["memory"]["reserve_gb"]
    if float(gb).is_integer():
        new["memory"]["reserve_gb"] = int(gb)  # written as 13, not 13.0
    if float(new["outputs"]["hidden_keep_days"]).is_integer():
        new["outputs"]["hidden_keep_days"] = int(new["outputs"]["hidden_keep_days"])
    port = new["hub"]["port"]
    clash = next((s for s in mgr.list() if s.port == port), None)
    if clash:
        raise _invalid(f"Port {port} is used by {clash.mod.name}", "hub.port")
    total = hub.memory.sys.get("total_bytes", 0) if hub.memory else 0
    if total and new["memory"]["reserve_gb"] * GB >= total:
        raise _invalid(f"Must be less than this machine's {total / GB:.0f} GB", "memory.reserve_gb")

    # Only keys whose value changed are touched (an unchanged form leaves the file alone);
    # a changed value equal to AIHub's default removes its key instead of pinning it.
    d = DEFAULTS
    defaults = {
        "hub": {"port": d.hub.port},
        "memory": {k: v for k, v in d.memory.model_dump().items() if k in before["memory"]},   # the page's keys (not peak_days)
        "services": {"order": d.services.order},
        "ui": {"theme": d.ui.theme, "density": d.ui.density},
        "learning": d.learning.model_dump(),
        "speech_input": d.speech_input.model_dump(),
        "speech_output": d.speech_output.model_dump(),
        "judge": d.agent.judge.model_dump(),
        "screen": d.agent.screen.model_dump(),
        "permissions": d.agent.permissions.model_dump(),
        "web": d.agent.web.model_dump(),
        "outputs": d.outputs.model_dump(),
    }
    changes: dict[str, Any] = {}
    for section, keys in defaults.items():
        for key, default in keys.items():
            if new[section][key] != before[section][key]:
                changes.setdefault(section, {})[key] = _or_default(new[section][key], default)
    for section in ("judge", "screen", "permissions", "web"):   # they live under [agent] in config.toml
        if section in changes:
            changes.setdefault("agent", {})[section] = changes.pop(section)
    if new["ui"]["dashboard"] != before["ui"]["dashboard"]:
        layout = {k: v for k, v in new["ui"]["dashboard"].items() if v}
        changes.setdefault("ui", {})["dashboard"] = config_mod.Replace(layout or None)
    if new["ui"]["nav"] != before["ui"]["nav"]:   # plan 33.2: only what differs from the defaults is written
        nav = {k: v for k, v in new["ui"]["nav"].items() if v != getattr(d.ui.nav, k)}
        changes.setdefault("ui", {})["nav"] = config_mod.Replace(nav or None)
    for sid in known:
        for key in ("enabled", "autostart"):
            if sid in new["services"][key] and new["services"][key][sid] != before["services"][key].get(sid):
                changes.setdefault("services", {}).setdefault(sid, {})[key] = _or_default(new["services"][key][sid], MOD_DEFAULTS[key])
    if not changes:
        return before, False
    try:
        cfg = config_mod.save(hub.paths.config_file, changes)
    except config_mod.ConfigError as e:
        raise _invalid(str(e)) from None
    # The port applies at the next start; changing it back to the one in use needs no restart.
    restart_required = "port" in changes.get("hub", {}) and cfg.hub.port != running
    was_enabled = {s.id: s.eff.enabled for s in mgr.list()}
    hub.config = cfg
    mgr.reconfigure(cfg)
    for svc in mgr.list():
        if was_enabled.get(svc.id) and not svc.eff.enabled and svc.state != "stopped" and not svc.external:
            await mgr.stop(svc.id)  # disabling applies now
    if hub.activity:
        await hub.activity.add("AIHub settings saved" + (" (restart AIHub to use the new port)" if restart_required else ""))
    return view(hub), restart_required
