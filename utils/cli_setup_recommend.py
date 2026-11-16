"""The mods recommended for chat (plan capability-enablement 8.1): which are recommended (`recommended = true` in a mod's
own setup block), which are set up already (the mod's command exists, as the hub decides it), and what a chat loses
without one (its manifest's `[agent] provides`, which completes "I can't …"). Standard library and setupdocs only."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

if __package__:   # imported as utils.cli_setup_recommend; as a script's helper it must not load the utils package
    from utils.setupdocs.envs import recommended
else:
    from setupdocs.envs import recommended  # type: ignore[no-redef]


def recommended_mods(root: Path, offered: dict[str, Any]) -> list[str]:
    """The recommended mods among those offered here, by id."""
    mods = sorted({e.mod for e in offered.values()})
    return [m for m in mods if recommended(root / "services" / m)]


def for_chat(root: Path, offered: dict[str, Any]) -> list[str]:
    """What `--recommended` and Enter take: the recommended mods, and the agent (required for a chat) when it isn't set up."""
    rec = recommended_mods(root, offered)
    agent = "agent" in {e.mod for e in offered.values()} and not is_set_up(root, "agent")
    return (["agent"] if agent else []) + rec


def _manifest(root: Path, mod: str) -> dict[str, Any]:
    try:
        return tomllib.loads((root / "services" / mod / "service.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def is_set_up(root: Path, mod: str) -> bool:
    """The mod's command (or what `[run] installed` names) exists: the hub's own test (manager.installed)."""
    run = _manifest(root, mod).get("run") or {}
    if run.get("external"):
        return True
    cmd = run.get("command") or []
    first = cmd[0] if isinstance(cmd, list) and cmd else (cmd.split()[0] if isinstance(cmd, str) and cmd else "")
    names = list(run.get("installed") or ([first] if first else []))
    if not names:
        return True
    d = root / "services" / mod
    for exe in names:
        exe = str(Path(exe).expanduser()) if exe.startswith("~") else exe
        if "/" in exe and ((Path(exe) if Path(exe).is_absolute() else d / exe).exists()):
            return True
        if "/" not in exe:                         # a command on PATH counts as there, as for the hub
            return True
    return False


def provides(root: Path, mod: str) -> str:
    return str((_manifest(root, mod).get("agent") or {}).get("provides") or "").strip()


def left_out(root: Path, chosen_mods: set[str], offered: dict[str, Any]) -> list[dict[str, str]]:
    """Recommended mods neither chosen now nor set up before, each with what a chat can't do without it."""
    return [{"mod": m, "provides": provides(root, m)} for m in recommended_mods(root, offered)
            if m not in chosen_mods and not is_set_up(root, m)]


def next_lines(missing: list[dict[str, str]]) -> list[str]:
    return [f"{x['mod']}: recommended for chat and not set up" + (f": without it, a chat can't {x['provides']}" if x["provides"] else "")
            + f" (gaifa setup {x['mod']})" for x in missing]
