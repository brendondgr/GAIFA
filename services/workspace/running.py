"""The running tools (plan 27.6): `workspace_run` (a command in a folder, in the sandbox or on this
machine) and `workspace_python` (Python in the sandbox, with outputs in and files out).

Output reaches the model inside `<untrusted>`: a program's output can carry text from anywhere.
Files `workspace_python` writes outside a folder become outputs in `outputs/workspace/<date>/`
(`<HHMMSS>-<name>`, written as `.part` then renamed, with a sidecar naming the run and the code).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

import limits
from folders import Folders, Refused
from reading import untrusted
from sandbox import DEFAULT_TIMEOUT, MAX_TIMEOUT, Run, Sandbox, SandboxMissing, new_id

OUTPUT_REF = re.compile(r"^(?:output:)?([0-9a-f]{12})$")
SLUG = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILES = 50


def _text(r: Run, label: str) -> dict[str, Any]:
    out: dict[str, Any] = {"run": r.id, "state": r.state, "exit_code": r.exit_code, "seconds": round((r.ms or 0) / 1000, 2),
                           "where": r.where, "network": r.network}
    if r.stdout:
        out["stdout"] = untrusted(f"{label} stdout", r.stdout)
    if r.stderr:
        out["stderr"] = untrusted(f"{label} stderr", r.stderr)
    if r.truncated:
        out["truncated"] = f"output cut to its last 32 KB; the whole run is at GET /api/s/workspace/v1/runs/{r.id}"
    if r.note:
        out["note"] = r.note
    return out


def _timeout(v: Any) -> int:
    try:
        t = int(v or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT
    return max(1, min(MAX_TIMEOUT, t))


async def run_command(folders: Folders, sb: Sandbox, args: dict[str, Any], origin: dict[str, Any], disconnected: Any) -> dict[str, Any]:
    f = folders.get(str(args.get("folder") or ""))
    command = str(args.get("command") or "")
    limits.check_command(command)
    where = args.get("where") or "sandbox"
    net = bool(args.get("network"))
    action = "host" if where == "host" else ("network" if net else "command")
    remote = limits.remote_git(command)
    if remote:
        action = "remote"
    folders.need(f, limits.NEEDS[action], limits._what(action, remote))
    root, _ = folders.resolve(f, ".")
    cwd, rel = folders.resolve(f, args.get("cwd") or ".")
    if not cwd.is_dir():
        raise Refused("not_a_folder", f"{rel} isn't a folder", "", 422)
    r = Run(new_id(), command, where, str(cwd), network=net or remote is not None or where == "host", folder=f.id,
            thread=origin.get("thread"), turn=str(origin["turn"]) if origin.get("turn") is not None else None,
            timeout_s=_timeout(args.get("timeout_s")))
    try:
        if where == "host":
            r = await sb.run_host(r, cwd, disconnected)
        else:
            r = await sb.run(r, cwd, [(root, "rw")], disconnected=disconnected)
    except SandboxMissing as e:
        raise Refused("sandbox_missing", str(e), "ask the user to build the sandbox image on the Workspace page (Sandbox → Build)", 503) from None
    return _text(r, f"{f.id}: {command[:60]}")


async def _fetch_input(hub: str, ref: str, dest: Path) -> Path:
    m = OUTPUT_REF.match(ref.strip())
    if not m:
        raise Refused("bad_input", f"{ref!r} isn't an output reference", "pass outputs as output:<id> (or #n in a chat)", 422)
    oid = m.group(1)
    async with httpx.AsyncClient(base_url=hub, timeout=60, trust_env=False) as c:
        meta = await c.get(f"/api/outputs/{oid}")
        if meta.status_code >= 400:
            raise Refused("unknown_output", f"there is no output {oid}", "find it with hub_search_outputs", 404)
        name = Path(meta.json().get("path") or oid).name or oid
        name = SLUG.sub("-", re.sub(r"^\d{6}-", "", name))[:120] or oid     # the upload's own name, without the hub's time
        data = await c.get(f"/api/outputs/{oid}/file")
        if data.status_code >= 400:
            raise Refused("unknown_output", f"output {oid} has no file", "", 404)
    p = dest / name
    if p.exists():
        p = dest / f"{oid}-{name}"
    p.write_bytes(data.content)
    return p


def _save_outputs(work: Path, before: set[str], outputs: Path, code: str, run: Run) -> list[str]:
    """New files in the work folder → outputs/workspace/<date>/<HHMMSS>-<name> (+ sidecar)."""
    day = outputs / time.strftime("%Y-%m-%d")
    stamp = time.strftime("%H%M%S")
    saved: list[str] = []
    for p in sorted(work.rglob("*")):
        rel = str(p.relative_to(work))
        if not p.is_file() or rel in before or rel.startswith(("inputs/", ".")) or rel == "main.py" or "/." in rel:
            continue
        if len(saved) >= MAX_FILES:
            break
        day.mkdir(parents=True, exist_ok=True)
        dest = day / f"{stamp}-{SLUG.sub('-', rel.replace('/', '-'))[:120]}"
        n = 2
        while dest.exists():
            dest = day / f"{stamp}-{n}-{SLUG.sub('-', rel.replace('/', '-'))[:120]}"
            n += 1
        part = dest.with_name(dest.name + ".part")
        shutil.copyfile(p, part)
        os.replace(part, dest)
        side = {"title": rel, "source": "workspace_python", "run": run.id, "code": code[:4000], "thread": run.thread}
        dest.with_name(dest.name + ".json").write_text(json.dumps(side, indent=1))
        saved.append(str(dest))
    return saved


async def run_python(folders: Folders, sb: Sandbox, state: Path, outputs: Path, hub: str, args: dict[str, Any],
                     origin: dict[str, Any], disconnected: Any) -> dict[str, Any]:
    code = str(args.get("code") or "")
    if not code.strip():
        raise Refused("empty_code", "the code is empty", "", 422)
    net = bool(args.get("network"))
    f = folders.get(str(args["folder"])) if args.get("folder") else None
    if f is not None:
        folders.need(f, "run_net" if net else "run", "Python with internet" if net else "running Python")
    elif net:
        raise Refused("level", "Python with internet needs a folder at Run + network", "pass such a folder, or no network")
    rid = new_id()
    work = state / "python" / rid
    (work / "inputs").mkdir(parents=True)
    (work / "out").mkdir()
    try:
        names = [(await _fetch_input(hub, str(ref), work / "inputs")).name for ref in args.get("inputs") or []]
        (work / "main.py").write_text(code)
        before = {str(p.relative_to(work)) for p in work.rglob("*")}
        mounts: list[tuple[Path, str]] = [(work, "rw")]
        cwd = work
        if f is not None:
            root, _ = folders.resolve(f, ".")
            mounts.append((root, "rw"))
            cwd = root
        env = {"AIHUB_INPUTS": str(work / "inputs"), "AIHUB_OUT": str(work / "out")}
        r = Run(rid, f"python {work / 'main.py'}", "sandbox", str(cwd), network=net, folder=f.id if f else None,
                thread=origin.get("thread"), turn=str(origin["turn"]) if origin.get("turn") is not None else None,
                timeout_s=_timeout(args.get("timeout_s")))
        try:
            r = await sb.run(r, cwd, mounts, env, disconnected)
        except SandboxMissing as e:
            raise Refused("sandbox_missing", str(e), "ask the user to build the sandbox image on the Workspace page (Sandbox → Build)", 503) from None
        files = _save_outputs(work, before, outputs, code, r)
        r.outputs = files
        sb.records.save(r)
        out = _text(r, "python")
        if names:
            out["inputs"] = [f"inputs/{n}" for n in names]
        elif r.exit_code not in (0, None) and ("FileNotFoundError" in r.stderr or "No such file" in r.stderr):
            out["note"] = ("inputs/ is empty: pass the files the code reads in `inputs` (attached ones as \"#1\", or output:<id>); "
                           "they appear as inputs/<their name>")
        if files:
            out["files"] = files
        elif f is None:
            out["files"] = []
            out.setdefault("note", "no files were written; files saved in the working directory (or $AIHUB_OUT) become outputs")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
