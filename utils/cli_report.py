"""`aihub report` (plan 40.2): a field report, one markdown file (and its JSON) that tells whoever fixes AIHub
exactly what happened on another machine. Standard library only, so it works when the hub doesn't.

    aihub report note "<what happened>" [--cmd "<command>"] [--output <file>] [--setup <id>]
                                        [--severity blocker|major|minor] [--tried "<what was tried>"]
    aihub report [--out <file>]          write data/state/reports/<date>-<host>.md (+ .json, + the hardware recording)
    aihub report clear                   start over: the notes move aside into data/state/reports/

The report has:
- a summary;
- the machine (`aihub hardware`, the tool versions, and a recording that `aihub hardware --from` replays);
- AIHub's commit and any local changes (`git diff`);
- the failed host checks;
- the last `aihub setup` run (data/state/setup/last-run.json), with its variants;
- one section per issue: a failure of that run, or a note, with where it comes from (the setup doc's line),
  the command, folder, environment, exit code, the log's tail, a likely cause (utils/report_hints.py),
  what was tried and the files to look at;
- the mods and their logs;
- the doctor;
- how to reproduce it.

Everything goes through `report_hints.redact`: tokens and keys out, the home folder as ~.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

if __package__:
    from utils import cli_setup_host as host_mod
    from utils import hardware, report_hints, report_md
else:
    import cli_setup_host as host_mod  # type: ignore[no-redef]
    import hardware  # type: ignore[no-redef]
    import report_hints  # type: ignore[no-redef]
    import report_md  # type: ignore[no-redef]

cli: Any = None   # utils/cli.py sets this before calling in
REPORTS = Path("data") / "state" / "reports"
NOTES = REPORTS / "notes.jsonl"
LAST_RUN = Path("data") / "state" / "setup" / "last-run.json"
SETUP_LOGS = Path("data") / "state" / "setup" / "logs"
TAIL = 120
MOD_TAIL = 80
SEVERITY = ("blocker", "major", "minor")
VERSIONS = [("python3", ["python3", "--version"]), ("uv", ["uv", "--version"]), ("git", ["git", "--version"]),
            ("podman", ["podman", "--version"]), ("docker", ["docker", "--version"]), ("node", ["node", "--version"]),
            ("cmake", ["cmake", "--version"]), ("nvcc", ["nvcc", "--version"]), ("ffmpeg", ["ffmpeg", "-version"])]


def _sh(argv: list[str], cwd: Path | None = None, timeout: float = 20) -> str | None:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return (p.stdout or p.stderr).rstrip() if p.returncode == 0 else None


def _tail(path: Path, n: int) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 256 * 1024))
            return f.read().decode(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _root() -> Path:
    return Path(cli.ROOT)


# ---- notes -------------------------------------------------------------------------------------------------


def add_note(root: Path, text: str, cmd: str = "", output: str = "", setup: str = "", severity: str = "major", tried: str = "") -> dict[str, Any]:
    note = {"ts": time.time(), "text": text, "cmd": cmd, "setup": setup, "severity": severity if severity in SEVERITY else "major",
            "tried": tried, "cwd": os.getcwd()}
    if output:
        p = Path(output)
        note["output_file"] = str(p)
        note["output"] = _tail(p, TAIL) if p.exists() else [f"(no such file: {p})"]
    path = root / NOTES
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(note) + "\n")
    return note


def notes(root: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in (root / NOTES).read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


# ---- gathering -------------------------------------------------------------------------------------------------


def machine_section(root: Path, base: Path) -> dict[str, Any]:
    try:
        fixture = os.environ.get("AIHUB_HARDWARE_FIXTURE")      # dev and tests: the recorded machine
        if fixture:
            snap = json.loads(Path(fixture).read_text())
            m = hardware.from_snapshot(snap)
        else:
            m, snap = hardware.record()
    except Exception as e:  # noqa: BLE001: a report must never fail to be written
        return {"error": f"hardware detection failed: {e}"}
    snap_path = base.with_suffix(".hardware.json")
    snap_path.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    tools = {name: (_sh(argv) or "").splitlines()[0][:120] if _sh(argv) else "not found" for name, argv in VERSIONS}
    smi = _sh(["nvidia-smi"])
    return {"machine": m.to_dict(), "snapshot": snap_path.name, "tools": tools,
            "nvidia_smi": (smi or "").splitlines()[:12] if smi else None,
            "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                         "python": platform.python_version()},
            "proc_version": (Path("/proc/version").read_text().strip() if Path("/proc/version").exists() else "")}


def git_section(root: Path) -> dict[str, Any]:
    g = lambda *a: _sh(["git", "-C", str(root), *a])   # noqa: E731
    status = (g("status", "--porcelain") or "").splitlines()
    diff = (g("diff") or "").splitlines()
    subject = g("log", "-1", "--format=%h %s") or ""
    return {"commit": g("rev-parse", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
            "describe": subject[:110] + ("…" if len(subject) > 110 else ""),
            "changed": status[:60], "changed_count": len(status), "diff": diff[:400], "diff_lines": len(diff)}


def host_section(root: Path) -> list[dict[str, Any]]:
    try:
        return [c.dump() for c in host_mod.checks(host_mod.Probe(), root)]
    except Exception as e:  # noqa: BLE001
        return [{"id": "host-checks", "ok": False, "detail": f"couldn't run: {e}", "fix": ""}]


def hub_section() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["services"] = cli.call("GET", "/api/services", timeout=5)
        out["doctor"] = cli.call("GET", "/api/doctor", timeout=60)
    except Exception as e:  # noqa: BLE001: the hub may be down; that's part of the report
        out["error"] = f"the hub wasn't answering at {cli.hub_url()}: {e}"
    return out


FILE_REF = re.compile(r"(?:^|[\s;&|(])((?:\./)?(?:scripts|bin|engines|workers)/[\w./-]+|install(?:-runtime)?\.sh|[\w./-]+\.py)\b")


def files_for(f: dict[str, Any]) -> list[str]:
    """The files a fix likely touches: the setup doc, and files the command runs (inside the mod)."""
    out: list[str] = []
    src = str(f.get("source") or f.get("doc") or "")
    if src:
        out.append(src.split(":")[0])
    mod_dir = str(f.get("cwd") or "")
    for m in FILE_REF.finditer(" " + str(f.get("run") or "")):
        ref = m.group(1).removeprefix("./")
        out.append(f"{mod_dir}/{ref}" if mod_dir and not ref.startswith(("services/", "/")) else ref)
    return list(dict.fromkeys(out))


def issues(root: Path, last: dict[str, Any] | None, noted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    result = (last or {}).get("result") or {}
    failed = list(result.get("failed") or (result.get("report") or {}).get("failed") or [])
    for f in failed:
        step = str(f.get("step") or "")
        log = root / f["log"] if f.get("log") else None
        tail = _tail(log, TAIL) if log and log.exists() else str(f.get("output") or "").splitlines()[-TAIL:]
        text = "\n".join(tail)
        out.append({"kind": "failure", "severity": "blocker" if step not in ("check", "smoke") else "major",
                    "title": f"{f.get('setup')}: {step} failed" + (f" (exit {f['exit']})" if f.get("exit") is not None else ""),
                    "setup": f.get("setup"), "step": step, "source": f.get("source") or f.get("doc"), "run": f.get("run"),
                    "cwd": f.get("cwd"), "exit": f.get("exit"), "env": f.get("env") or {}, "log": f.get("log"), "output": tail,
                    "hints": [{"id": h.id, "cause": h.cause, "fix": h.fix} for h in report_hints.hints(text)],
                    "files": files_for(f)})
    if result.get("stage") == "stopped" and result.get("reason") not in ("failed", None):
        why = {k: v for k, v in result.items() if k not in ("stage", "report", "plan")}
        out.append({"kind": "stop", "severity": "major", "title": f"the setup stopped: {result.get('reason')}",
                    "detail": json.dumps(why, default=str)[:3000], "hints": [], "files": []})
    for n in noted:
        text = "\n".join(n.get("output") or [])
        out.append({"kind": "note", "severity": n.get("severity", "major"), "title": n["text"][:100], "text": n["text"],
                    "setup": n.get("setup"), "run": n.get("cmd"), "cwd": n.get("cwd"), "output": n.get("output") or [],
                    "output_file": n.get("output_file"), "tried": n.get("tried"),
                    "hints": [{"id": h.id, "cause": h.cause, "fix": h.fix} for h in report_hints.hints(text + "\n" + n["text"])],
                    "files": []})
    out.sort(key=lambda i: SEVERITY.index(i["severity"]) if i["severity"] in SEVERITY else 9)
    for k, i in enumerate(out, 1):
        i["id"] = f"ISSUE-{k}"
    return out


def gather(root: Path, base: Path) -> dict[str, Any]:
    try:
        last = json.loads((root / LAST_RUN).read_text())
    except (OSError, ValueError):
        last = None
    noted = notes(root)
    logs = sorted((root / SETUP_LOGS).glob("*.log")) if (root / SETUP_LOGS).is_dir() else []
    data = {"written": time.strftime("%Y-%m-%d %H:%M:%S %z"), "host": socket.gethostname(),
            "machine": machine_section(root, base), "aihub": git_section(root), "host_checks": host_section(root),
            "last_run": last, "issues": issues(root, last, noted), "notes": len(noted),
            "setup_logs": [{"file": p.relative_to(root).as_posix(), "bytes": p.stat().st_size,
                            "end": (_tail(p, 1) or [""])[0]} for p in logs],
            "hub": hub_section()}
    mods = []
    for s in (data["hub"].get("services") or []):
        bad = s.get("state") == "failed" or bool(s.get("last_error")) or bool(s.get("unavailable")) or bool(s.get("manifest_errors"))
        mods.append({"id": s["id"], "state": s.get("state"), "load": s.get("load"), "accel": s.get("accel"),
                     "unavailable": s.get("unavailable"), "last_error": s.get("last_error"), "manifest_errors": s.get("manifest_errors"),
                     "log": _tail(root / "data" / "logs" / f"{s['id']}.log", MOD_TAIL) if bad else []})
    data["mods"] = mods
    return data


# ---- the command ---------------------------------------------------------------------------------------------


def write(root: Path, out: Path | None = None) -> Path:
    """Gather everything, write the markdown, its JSON and the hardware recording; return the markdown's path."""
    host = re.sub(r"[^A-Za-z0-9.-]+", "-", socket.gethostname()) or "machine"
    path = out or root / REPORTS / f"{time.strftime('%Y%m%d-%H%M')}-{host}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gather(root, path)
    home = str(Path.home())
    path.write_text(report_hints.redact(report_md.render(data), home))
    def clean(v: Any) -> Any:      # string by string, so the JSON stays valid
        if isinstance(v, str):
            return report_hints.redact(v, home)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    path.with_suffix(".json").write_text(report_md.to_json(clean(json.loads(report_md.to_json(data)))))
    return path


def cmd_report(args: argparse.Namespace) -> int:
    root = _root()
    if args.action == "note":
        if not args.text:
            print("aihub report note: say what happened, in quotes", flush=True)
            return 2
        n = add_note(root, args.text, args.cmd or "", args.output or "", args.setup or "", args.severity, args.tried or "")
        print(f"noted ({n['severity']}): {n['text'][:80]}  → {(root / NOTES).relative_to(root)}")
        return 0
    if args.action == "clear":
        p = root / NOTES
        if p.exists():
            dest = p.with_name(f"notes-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
            p.rename(dest)
            print(f"notes moved to {dest.relative_to(root)}")
        else:
            print("no notes")
        return 0
    path = write(root, Path(args.out) if args.out else None)
    shown = path.relative_to(root) if path.is_relative_to(root) else path
    print(f"wrote {shown}\n  (+ {shown.with_suffix('.json').name}, {shown.with_suffix('.hardware.json').name})")
    return 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("report", help="a field report for whoever fixes AIHub: the machine, the last setup run, every failure with "
                                      "its doc line, command, log and likely cause, the mods and the doctor (plan 40.2)")
    p.add_argument("action", nargs="?", default="write", choices=["write", "note", "clear"], help="write (default), note, or clear the notes")
    p.add_argument("text", nargs="?", help="note: what happened, in your words")
    p.add_argument("--cmd", help="note: the command that showed it")
    p.add_argument("--output", metavar="FILE", help="note: a file with its output (its last lines are kept)")
    p.add_argument("--setup", help="note: the setup or mod it's about")
    p.add_argument("--severity", default="major", choices=list(SEVERITY), help="note: blocker, major (default) or minor")
    p.add_argument("--tried", help="note: what was tried")
    p.add_argument("--out", metavar="FILE", help="write: where (default data/state/reports/<date>-<host>.md)")
    p.set_defaults(fn=cmd_report)
