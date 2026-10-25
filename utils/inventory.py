"""`gaifa doctor --inventory` (plan 16.3): every path outside the project that anything uses, with
its reason.

The final allowlist: the hub's systemd unit file, podman images and containers, system tools
(`/usr`), the `~/.local/bin` wrappers, `~/.config/tts-engines`, and the systemd journal (a second
copy of the logs). Anything else is `outside`; runtime leftovers in `$XDG_RUNTIME_DIR` are
`runtime` (tmpfs, gone at the next reboot).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from utils import doctor
from utils import manifest as mf

IMAGE = re.compile(r"\b(?:docker\.io|ghcr\.io|quay\.io|localhost)/[\w./-]+(?::[\w.-]+)?")


def _item(path: str, kind: str, used_by: str, reason: str) -> dict[str, str]:
    return {"path": path, "kind": kind, "used_by": used_by, "reason": reason}


def inventory(hub: Any) -> dict[str, Any]:
    root = hub.paths.root.resolve()
    home = Path.home()
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(it: dict[str, str]) -> None:
        key = (it["path"], it["used_by"])
        if key not in seen:
            seen.add(key)
            items.append(it)

    # 1. what each mod's command, cwd and environment point at
    for s in hub.services.list() if hub.services else []:
        if s.errors or s.m is None:
            continue
        try:
            spec = mf.launch_spec(s.mod, hub.config, hub.paths, hub.port)
        except mf.ManifestError:
            continue
        values = [(f"command[{i}]", a) for i, a in enumerate(spec.argv)] + [("cwd", str(spec.cwd))]
        values += [(f"env {k}", v) for k, v in spec.env.items() if k not in doctor.SKIP_ENV]
        for where, raw, kind in doctor.outside_paths(values, root):
            kind = {"stage-d": "runtime"}.get(kind, kind)
            reason = "system tool" if raw.startswith("/usr") else (
                "speech engine registry (LocalTTS's engines.json)" if "tts-engines" in raw else f"{where}")
            add(_item(raw, kind, s.id, reason))
        for where, v in values:
            for img in IMAGE.findall(v):
                add(_item(img, "allowlisted", s.id, f"podman image ({where})"))
        for c in (s.m.memory.containers if s.m.memory else []):
            add(_item(f"podman container {c}", "allowlisted", s.id, "the container the mod runs its models in"))
    # 2. the hub's unit and the wrappers in ~/.local/bin
    unit = home / ".config" / "systemd" / "user" / "gaifa.service"
    if unit.exists():
        add(_item(str(unit).replace(str(home), "~"), "allowlisted", "hub", "the hub's systemd unit (gaifa install)"))
    bindir = home / ".local" / "bin"
    if bindir.is_dir():
        for p in sorted(bindir.iterdir()):
            target = os.path.realpath(p) if p.is_symlink() else None
            text = ""
            if not p.is_symlink() and p.is_file() and p.stat().st_size < 20000:
                try:
                    text = p.read_text(errors="ignore")
                except OSError:
                    text = ""
            ours = (target and target.startswith(str(root))) or str(root) in text
            if not ours and not (target and "uv/tools" in target and p.name in {s.id for s in hub.services.list()}):
                continue
            add(_item(f"~/.local/bin/{p.name}", "allowlisted", "hub" if p.name == "gaifa" else p.name,
                      f"command-line wrapper → {target.replace(str(home), '~') if target else 'a script into the project'}"))
            if target and not Path(target).resolve().is_relative_to(root) and not target.startswith("/usr"):
                tool = Path(target).parents[1]
                add(_item(str(tool).replace(str(home), "~"), "outside", p.name,
                          "installed as a uv tool (a copy of the mod's CLI); reinstall from the mod folder"))
    # 3. runtime leftovers and the journal
    for base in doctor.STAGE_D:
        for s in hub.services.list() if hub.services else []:
            if (base / s.id).exists():
                add(_item(str(base / s.id), "runtime", s.id, "runtime state from before data/state/ (tmpfs: gone at the next reboot)"))
    add(_item("systemd journal (gaifa-*.service)", "allowlisted", "hub", "a second copy of the logs; data/logs/ is the first"))
    counts = {k: sum(i["kind"] == k for i in items) for k in ("allowlisted", "runtime", "outside")}
    return {"ok": counts["outside"] == 0, "counts": counts, "items": items}
