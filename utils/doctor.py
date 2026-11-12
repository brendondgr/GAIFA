"""`GET /api/doctor` and `gaifa doctor` (plan 12.4): checks over the whole install.

- **models:** every registry model's files are on disk (missing, partial or mismatched files fail).
- **manifests:** every mod folder parses and has no config clashes.
- **paths:** no mod's resolved command, cwd or env points outside the project root, except the
  allowlist (architecture §3): `/usr`, `~/.config/tts-engines`, `~/.local/bin` tools and podman
  images. The Stage D items (plan Phase 16: logs in the journal, runtime state in
  `$XDG_RUNTIME_DIR`) are listed as notes, not problems.
- **ports:** each mod's port is free, or held by that mod's own processes.
- **units:** no mod is failed or degraded; an enabled autostart mod is running.
- **disk:** enough free space on the project's disk.
- **offline:** mods run with `HF_HUB_OFFLINE=1` have every registered model they use.

Each check is `{area, level, title, detail, fix?}` with level ok | note | warn | fail.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

from utils import manifest as mf
from utils import proc

GB = 1000**3
DISK_WARN_GB = 50
DISK_FAIL_GB = 10
HOME = Path.home()
ALLOW = [Path("/usr"), HOME / ".config" / "tts-engines", HOME / ".local" / "bin"]
STAGE_D = [Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{getattr(os, 'getuid', lambda: 0)()}")]   # no getuid on Windows (plan 37.6)
PATHLIKE = re.compile(r"(?:^|(?<=[:=\s]))(~/[^:\s]*|~|/[^:\s]*)")
SKIP_ENV = {"PATH", "HOME", "PYTHONUNBUFFERED"}
URL = re.compile(r"[a-z][a-z0-9+.-]*://\S*", re.I)


def check(area: str, level: str, title: str, detail: str = "", fix: str | None = None) -> dict[str, Any]:
    out = {"area": area, "level": level, "title": title, "detail": detail}
    if fix:
        out["fix"] = fix
    return out


def _under(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def outside_paths(values: list[tuple[str, str]], root: Path) -> list[tuple[str, str, str]]:
    """(where, path, allowlisted | stage-d | outside) for each absolute or ~ path in the values
    that isn't inside the project root. A value like `a:b` (PYTHONPATH) is split on `:`."""
    out = []
    root = root.resolve()
    for where, value in values:
        for m in PATHLIKE.finditer(URL.sub(" ", value)):
            raw = m.group(1)
            p = Path(os.path.expanduser(raw))
            p = Path(os.path.normpath(p))
            if _under(p, root) or _under(p, Path(os.path.normpath(root))):
                continue
            kind = ("allowlisted" if any(_under(p, a) for a in ALLOW)
                    else "stage-d" if any(_under(p, s) for s in STAGE_D) else "outside")
            out.append((where, raw, kind))
    return out


def _models(hub: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    reg = hub.registry
    if reg is None:
        return [check("models", "warn", "models registry", "not loaded")], {}
    views = {v["id"]: v for v in reg.list()["models"]}
    bad = [v for v in views.values() if v["status"] in ("missing", "partial", "checksum_mismatch")]
    out = [check("models", "fail", f"model {v['id']}: {v['status']}", "; ".join(v["problems"][:3]),
                 f"gaifa models show {v['id']}") for v in bad]
    if not bad:
        n = len(views)
        unver = sum(v["status"] == "unverified" for v in views.values())
        out.append(check("models", "ok", f"models registry: {n} models, every file present",
                         f"{unver} not checksummed yet (gaifa models verify --all)" if unver else "all verified"))
    return out, views


def _manifests(hub: Any) -> list[dict[str, Any]]:
    svcs = hub.services.list() if hub.services else []
    out = [check("manifests", "fail", f"{s.id}: invalid", "; ".join(s.errors)[:400], f"gaifa check {s.id}")
           for s in svcs if s.errors]
    if not out:
        out.append(check("manifests", "ok", f"{len(svcs)} mod manifests valid", ", ".join(s.id for s in svcs)))
    return out


def _paths(hub: Any) -> list[dict[str, Any]]:
    out = []
    root = hub.paths.root
    for s in hub.services.list() if hub.services else []:
        if s.errors or s.m is None:
            continue
        try:
            spec = mf.launch_spec(s.mod, hub.config, hub.paths, hub.port)
        except mf.ManifestError as e:
            out.append(check("paths", "fail", f"{s.id}: can't resolve its command", str(e)))
            continue
        values = [(f"command[{i}]", a) for i, a in enumerate(spec.argv)] + [("cwd", str(spec.cwd))]
        values += [(f"env {k}", v) for k, v in spec.env.items() if k not in SKIP_ENV]
        found = outside_paths(values, root)
        bad = [f for f in found if f[2] == "outside"]
        allowed = [f"{w}: {p}" for w, p, k in found if k == "allowlisted"]
        later = [f"{w}: {p}" for w, p, k in found if k == "stage-d"]
        if bad:
            out.append(check("paths", "warn", f"{s.id}: {len(bad)} path(s) outside the project",
                             "; ".join(f"{w}: {p}" for w, p, _ in bad),
                             "move it inside services/<id>/ or data/, or add it to the allowlist (plan 12.4)"))
        else:
            note = "; ".join(allowed) if allowed else ""
            out.append(check("paths", "ok", f"{s.id}: everything inside the project" + (" or allowlisted" if allowed else ""), note))
        if later:
            out.append(check("paths", "note", f"{s.id}: runtime paths on tmpfs (cleared at reboot)", "; ".join(later)))
    return out


async def _ports_units(hub: Any) -> list[dict[str, Any]]:
    out = []
    for s in hub.services.list() if hub.services else []:
        port = s.port
        listening = await asyncio.to_thread(proc.port_listening, port)
        if s.up and not s.external:
            owner = await asyncio.to_thread(proc.port_owner, port)
            pids = set(await hub.backend.pids(s.id)) if hasattr(hub.backend, "pids") else set()
            if owner and owner.get("pid") in pids:
                out.append(check("ports", "ok", f"{s.id}: port {port} held by the mod", f"pid {owner['pid']}"))
            elif owner:
                out.append(check("ports", "warn", f"{s.id}: port {port} held by another process",
                                 proc.owner_text(owner), f"stop that process, or move {s.id} to a free port (Settings)"))
            else:
                out.append(check("ports", "warn", f"{s.id}: nothing listens on port {port}", f"state {s.state}"))
        elif not s.up and listening and not s.external:
            owner = await asyncio.to_thread(proc.port_owner, port)
            out.append(check("ports", "fail", f"{s.id}: port {port} is taken while the mod is stopped",
                             proc.owner_text(owner), f"stop that process, or move {s.id} to a free port (Settings)"))
        else:
            out.append(check("ports", "ok", f"{s.id}: port {port} " + ("external" if s.external else "free")))
        if s.state == "failed":
            out.append(check("units", "fail", f"{s.id}: failed", s.last_error or "", f"gaifa logs {s.id}"))
        elif s.state == "degraded":
            out.append(check("units", "warn", f"{s.id}: degraded (health checks failing)", s.last_error or "", f"gaifa logs {s.id}"))
        elif s.state == "stopped" and s.eff.enabled and s.eff.autostart and s.startable and not _installed(hub, s):
            out.append(check("units", "note", f"{s.id}: not installed", "it starts with the hub once it's set up", f"gaifa setup {s.id}"))
        elif s.state == "stopped" and s.eff.enabled and s.eff.autostart and s.startable:
            out.append(check("units", "warn", f"{s.id}: stopped, but set to start with the hub", "", f"gaifa start {s.id}"))
        else:
            out.append(check("units", "ok", f"{s.id}: {s.state}"))
    return out


def _listen_addrs(port: int) -> set[str]:
    import psutil

    try:
        return {c.laddr.ip for c in psutil.net_connections(kind="inet") if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port}
    except (psutil.Error, OSError):
        return set()


def _network(hub: Any) -> list[dict[str, Any]]:
    """Plan lan-access 1.4: the hub on the network only when opened to it, and mods never beyond loopback."""
    from utils.lan.addresses import is_loopback

    out = []
    lan = getattr(hub, "lan", None)
    if lan is not None and lan.cfg.enabled:
        if not lan.auth.has_password():
            out.append(check("network", "warn", "opened to the network, but no password is set", "devices can't sign in", "gaifa lan password"))
        elif not lan.listening:
            out.append(check("network", "warn", "opened to the network, but not listening on it yet", "", "gaifa restart"))
        else:
            out.append(check("network", "note", "open to your network", f"{', '.join(lan.urls()[:2])}; {len(lan.auth.devices())} device(s) signed in",
                             "gaifa lan off"))
    else:
        out.append(check("network", "ok", "GAIFA answers this machine only"))
    for s in hub.services.list() if hub.services else []:
        if s.up and not s.external:
            wide = sorted(ip for ip in _listen_addrs(s.port) if not is_loopback(ip))
            if wide:
                out.append(check("network", "warn", f"{s.id}: listens beyond this machine ({', '.join(wide)}:{s.port})",
                                 "a mod should listen on 127.0.0.1 only; other devices reach it through the hub", f"fix {s.id}'s server to bind 127.0.0.1"))
    return out


def _installed(hub: Any, s: Any) -> bool:
    mgr = getattr(hub, "services", None)
    return mgr.installed(s) if mgr is not None and hasattr(mgr, "installed") else True


def _disk(hub: Any) -> list[dict[str, Any]]:
    du = shutil.disk_usage(hub.paths.root)
    free = du.free / GB
    level = "fail" if free < DISK_FAIL_GB else "warn" if free < DISK_WARN_GB else "ok"
    return [check("disk", level, f"{free:.0f} GB free of {du.total / GB:.0f} GB", str(hub.paths.root),
                  None if level == "ok" else "free space: old outputs (Outputs page) or unused models (Models page)")]


def _judge(hub: Any) -> list[dict[str, Any]]:
    """`config.toml [agent.judge]` still naming a chat model (before plan web-approvals): it's ignored, and the judge
    is d3-lite in the decide mod (the user's rule: a decision model only)."""
    try:
        judge = ((tomllib.loads(hub.paths.config_file.read_text()).get("agent") or {}).get("judge") or {})
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if judge.get("backend", "decide") == "decide":
        return []
    stale = ", ".join(f"{k} = {judge[k]!r}" for k in ("backend", "model", "url") if k in judge)
    return [check("config", "warn", "config.toml names a chat model for the Auto judge; it's ignored",
                  f"[agent.judge] {stale}: the judge is a decision model (decide mod, d3-lite)",
                  "remove backend, model and url from [agent.judge] (or pick the model in Settings → Permissions)")]


def _offline(hub: Any, views: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in hub.services.list() if hub.services else []:
        if s.errors or s.m is None:
            continue
        try:
            env = mf.launch_spec(s.mod, hub.config, hub.paths, hub.port).env
        except mf.ManifestError:
            continue
        if env.get("HF_HUB_OFFLINE") not in ("1", "true", "True", "yes"):
            continue
        used = [v for v in views.values() if s.id in v["services"]]
        bad = [v for v in used if v["status"] in ("missing", "partial", "checksum_mismatch")]
        if not used:
            out.append(check("offline", "warn", f"{s.id}: runs offline but uses no registered model",
                             "its files can't be checked", "gaifa models scan --add"))
        elif bad:
            out.append(check("offline", "fail", f"{s.id}: runs offline without {len(bad)} model(s)",
                             ", ".join(f"{v['id']} ({v['status']})" for v in bad), "download them, or gaifa models show <id>"))
        else:
            out.append(check("offline", "ok", f"{s.id}: runs offline; all {len(used)} model(s) present",
                             ", ".join(v["id"] for v in used)))
    return out


def _stage_d(hub: Any) -> list[dict[str, Any]]:
    """Logs and mods' runtime state, inside the project since plan 16.1 and 16.2; leftovers from before are noted."""
    ids = [s.id for s in hub.services.list()] if hub.services else []
    logs = hub.paths.logs
    shipped = sorted(p.stem for p in logs.glob("*.log")) if logs.is_dir() else []
    out = [check("paths", "ok", f"logs: in {logs.relative_to(hub.paths.root)}/ ({len(shipped)} files; the systemd journal keeps a second copy)",
                 ", ".join(shipped))]
    for base in STAGE_D:
        for i in ids:
            if (base / i).exists():
                out.append(check("paths", "note", f"{i}: leftover runtime state in {base / i}",
                                 "from before data/state/ (plan 16.2); tmpfs, so it's gone at the next reboot"))
    return out


def _repos(hub: Any) -> list[dict[str, Any]]:
    """The mods that are their own repositories (plan mod-repos 3.4): the same problems and fixes as their alerts."""
    from utils import repos
    level = {"error": "fail", "warn": "warn", "info": "note"}
    out = []
    for st in repos.list_states(hub.paths.root):
        if not st.problems:
            out.append(check("repos", "ok", f"{st.id}: at its pin {(st.pinned or '')[:10]}", f"{st.url} {st.branch}"))
        for p in st.problems:
            out.append(check("repos", level[p.level], p.title, p.detail, p.fix or None))
    return out


async def run(hub: Any) -> dict[str, Any]:
    models, views = await asyncio.to_thread(_models, hub)
    checks = (models + _manifests(hub) + _paths(hub) + _stage_d(hub) + await _ports_units(hub)
              + await asyncio.to_thread(_network, hub) + _disk(hub) + _judge(hub) + _offline(hub, views) + await asyncio.to_thread(_repos, hub))
    counts = {k: sum(c["level"] == k for c in checks) for k in ("ok", "note", "warn", "fail")}
    return {"ts": time.time(), "ok": counts["fail"] == 0, "counts": counts, "checks": checks}
