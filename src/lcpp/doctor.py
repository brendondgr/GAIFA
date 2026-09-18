"""``lcpp doctor`` — check everything lcpp depends on, daemon or no daemon.

Stdlib only (it runs from the CLI) and read-only: it reports, it never fixes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from lcpp import proc, settings
from lcpp.catalog import Catalog
from lcpp.client import ApiError, Client, DaemonDown
from lcpp.paths import Paths

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def run(client: Client) -> int:
    paths = Paths.default()
    results: list[tuple[str, str, str]] = []

    def add(status: str, what: str, detail: str = "") -> None:
        results.append((status, what, detail))

    try:
        s = settings.load(paths)
        add(OK, "settings", str(paths.settings_file))
    except (settings.SettingsError, OSError) as e:
        add(FAIL, "settings", str(e))
        s = settings.DEFAULTS

    binary = paths.resolve(s["llama"]["binary"])
    if binary.is_file() and os.access(binary, os.X_OK):
        add(OK, "llama-server", str(binary.resolve()))
    else:
        add(FAIL, "llama-server", f"not found or not executable: {binary}")

    try:
        cat = Catalog.load(paths)
        bad = {m.id: cat.problems(m) for m in cat.models.values()}
        broken = {k: v for k, v in bad.items() if v}
        if broken:
            for mid, probs in broken.items():
                add(WARN, f"model {mid}", probs[0])
        add(OK if not broken else WARN, "catalog", f"{len(cat.models)} models, {len(broken)} with missing files")
    except (ValueError, OSError) as e:
        add(FAIL, "catalog", str(e))

    for tool in ("systemd-run", "systemctl", "journalctl"):
        if not shutil.which(tool):
            add(FAIL, tool, "not on PATH (instances run as systemd user units)")

    unit = Path.home() / ".config/systemd/user/lcpp.service"
    enabled = subprocess.run(["systemctl", "--user", "is-enabled", "lcpp.service"],
                             capture_output=True, text=True).stdout.strip()
    if unit.exists():
        add(OK if enabled == "enabled" else WARN, "service", f"lcpp.service is {enabled or 'unknown'}"
            + ("" if enabled == "enabled" else " — it will not start at boot (lcpp service install)"))
    else:
        add(WARN, "service", "lcpp.service not installed (lcpp service install)")

    try:
        health = client.get("/api/health")
        add(OK, "daemon", f"{client.base} — {health['instances']} instance(s)")
        relay = client.get("/api/relay")["status"]
        if relay["reachable"]:
            add(OK, "relay", f"{relay['url']} ({relay['latency_ms']} ms)")
        else:
            add(WARN, "relay", f"{relay['url']} unreachable: {relay['error']}")
    except DaemonDown:
        port = s["daemon"]["port"]
        owner = None if proc.port_free(port) else proc.port_owner(port)
        add(FAIL, "daemon", f"not answering at {client.base}"
            + (f"; port {port} is held by {owner}" if owner else " (lcpp service start)"))
    except ApiError as e:
        add(FAIL, "daemon", e.detail)

    for status, what, detail in results:
        print(f"[{status}] {what:<14} {detail}")
    return 1 if any(r[0] == FAIL for r in results) else 0
