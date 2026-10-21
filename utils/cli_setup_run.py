"""`aihub setup`'s answers and run (plan 23.9, 23.10): questions, the hub stage, steps with resume,
models (followed until their jobs end), checks and the report. Standard library only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

cli: Any = None   # utils/cli.py, set by cli_setup.cmd_setup

STATE = Path("data") / "state" / "setup" / "run.json"
TERMINAL = {"done", "finished", "ok", "ready", "completed", "failed", "error", "cancelled", "canceled"}
FAILED = {"failed", "error"}
JOB_TIMEOUT_S = 6 * 3600


class Stop(Exception):
    """A run that can't go on: an unanswered question, a failed step, a blocking host check."""

    def __init__(self, reason: str, **data: Any) -> None:
        super().__init__(reason)
        self.reason, self.data = reason, data


@dataclass
class Answers:
    accept: set[str] = field(default_factory=set)              # question ids answered yes
    decline: set[str] = field(default_factory=set)             # … answered no: that setup (and what needs it) is skipped
    done: set[str] = field(default_factory=set)                # interactive steps the person ran themselves
    models: dict[str, list[str]] = field(default_factory=dict)  # setup or mod id → suggestion names; [] = none
    yes: bool = False                                          # the plan is accepted


class Runner:
    """Commands, hub calls and waiting; tests pass a fake."""

    def run(self, cmd: str, cwd: Path, env: dict[str, str] | None = None, stream: bool = True) -> tuple[int, str]:
        import os
        full = {**os.environ, **(env or {})}
        full["PATH"] = f"{Path(cli.CODE) / 'bin'}:{full.get('PATH', '')}"   # `aihub` before ~/.local/bin is on PATH
        if stream:
            return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=full).returncode, ""
        p = subprocess.run(["bash", "-c", cmd], cwd=cwd, env=full, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr)[-4000:]

    def call(self, method: str, path: str, body: Any = None) -> Any:
        return cli.call(method, path, body, timeout=600)

    def hub_up(self) -> bool:
        try:
            cli.call("GET", "/api/system", timeout=3)
            return True
        except Exception:  # noqa: BLE001: down, or not answering yet
            return False

    def sleep(self, s: float) -> None:
        time.sleep(s)


def interactive(args: argparse.Namespace) -> bool:
    return not args.json and sys.stdin.isatty()


def say(args: argparse.Namespace, msg: str) -> None:
    """Progress: on stdout for a person, on stderr under --json (stdout stays one JSON result)."""
    print(msg, file=sys.stderr if args.json else sys.stdout, flush=True)


# ---- answers -------------------------------------------------------------------------------


def read_answers(args: argparse.Namespace) -> Answers:
    a = Answers(yes=bool(args.yes))
    if args.answers:
        data = json.loads(Path(args.answers).read_text())
        a.accept |= set(data.get("accept", []))
        a.decline |= set(data.get("decline", []))
        a.done |= set(data.get("done", []))
        a.models.update({k: list(v) for k, v in data.get("models", {}).items()})
        a.yes = a.yes or bool(data.get("yes"))
    a.accept |= set(getattr(args, "accept", None) or [])
    a.decline |= set(getattr(args, "decline", None) or [])
    a.done |= set(getattr(args, "done", None) or [])
    for spec in args.models or []:
        key, _, names = spec.partition("=")
        a.models[key.strip()] = [n.strip() for n in names.split(",") if n.strip() and n.strip() != "none"]
    return a


def ask(args: argparse.Namespace, answers: Answers, qid: str, text: str) -> bool:
    """A yes/no question: from the answers, or asked; unanswered without a terminal, the run stops."""
    if qid in answers.decline:
        return False
    if qid in answers.accept:
        return True
    if not interactive(args):
        raise Stop("question", id=qid, kind="yes-no", text=text, answer_with=f"--accept {qid} or --decline {qid}")
    yes = input(f"{text} [y/N] ").strip().lower() in ("y", "yes")
    (answers.accept if yes else answers.decline).add(qid)
    return yes


def models_for(args: argparse.Namespace, answers: Answers, e: Any) -> list[Any]:
    """The suggestions chosen for one setup. A mod id's answer covers each of its setups, which take
    the names that are theirs; a setup id's answer is that setup's alone."""
    known = {s.name: s for s in e.setup.suggest}
    if e.id in answers.models:
        names = answers.models[e.id]
        unknown = [n for n in names if n not in known]
        if unknown:
            raise Stop("unknown-model", setup=e.id, names=unknown, choices=list(known))
        return [known[n] for n in names]
    if e.mod in answers.models:
        return [known[n] for n in answers.models[e.mod] if n in known]
    if not interactive(args):
        raise Stop("question", id=f"{e.id}/models", kind="models", choices=list(known),
                   required=[s.name for s in e.setup.suggest if s.required], answer_with=f'--models "{e.id}=<names>" (or none)')
    print(f"\nModels for {e.title} (to add your own, see its setup doc's Choosing models):")
    for i, s in enumerate(e.setup.suggest, 1):
        print(f"  {i}. {s.name} ({s.size_gb:.2f} GB){' required' if s.required else ''}{' gated' if s.gated else ''}: {s.good_for}")
    default = ",".join(str(i) for i, s in enumerate(e.setup.suggest, 1) if s.required) or "none"
    pick = input(f"Numbers, comma-separated, or none [{default}]: ").strip() or default
    chosen = [] if pick == "none" else [e.setup.suggest[int(x) - 1] for x in pick.split(",") if x.strip().isdigit() and 0 < int(x) <= len(e.setup.suggest)]
    answers.models[e.id] = [s.name for s in chosen]
    return chosen


def check_mod_answers(answers: Answers, envs: list[Any]) -> None:
    """A name given for a mod must belong to one of that mod's chosen setups."""
    by_mod: dict[str, set[str]] = {}
    for e in envs:
        by_mod.setdefault(e.mod, set()).update(s.name for s in e.setup.suggest)
    for key, names in answers.models.items():
        if key in by_mod and key not in {e.id for e in envs}:
            unknown = [n for n in names if n not in by_mod[key]]
            if unknown:
                raise Stop("unknown-model", setup=key, names=unknown, choices=sorted(by_mod[key]))


def dependents(envs: list[Any], skipped: set[str]) -> set[str]:
    """`skipped` plus every chosen setup that needs one of them (`after`), transitively."""
    out = set(skipped)
    grew = True
    while grew:
        grew = False
        for e in envs:
            if e.id not in out and any(x.id in out and (x.id in e.setup.after or (x.mod in e.setup.after and x.mod != e.mod)) for x in envs):
                out.add(e.id)
                grew = True
    return out


# ---- the run ---------------------------------------------------------------------------------


def load_state(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / STATE).read_text())
    except (OSError, ValueError):
        return {"steps": {}, "models": {}}


def save_state(root: Path, state: dict[str, Any]) -> None:
    p = root / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(p)


def doc_of(e: Any, root: Path) -> str:
    return e.path.relative_to(root).as_posix() if e.path.is_relative_to(root) else str(e.path)


def hub_needs(code: Path, runner: Runner) -> list[str]:
    """What the hub stage will do: shown in the plan before anything runs."""
    out = []
    if not (code / ".venv" / "bin" / "python").exists():
        out.append("uv sync (the hub's .venv, about 100 MB)")
    if not runner.hub_up():
        out.append("aihub install (writes ~/.config/systemd/user/aihub.service, links ~/.local/bin/aihub, starts the hub)")
    return out


def hub_stage(code: Path, runner: Runner, stream: bool) -> list[str]:
    done = []
    if not (code / ".venv" / "bin" / "python").exists():
        rc, out = runner.run("uv sync", code, stream=stream)
        if rc:
            raise Stop("failed", step="hub/uv-sync", output=out, doc="docs/setup/hub.md")
        done.append("uv sync")
    if not runner.hub_up():
        rc, out = runner.run("bin/aihub install", code, stream=stream)
        if rc:
            raise Stop("failed", step="hub/install", output=out, doc="docs/setup/hub.md")
        done.append("aihub install")
    return done or ["already installed and running"]


def _jobs(runner: Runner, mod: str) -> list[dict[str, Any]]:
    try:
        return list((runner.call("GET", f"/api/services/{mod}") or {}).get("jobs") or [])
    except Exception:  # noqa: BLE001: a moment without status is not a failure
        return []


def follow_jobs(runner: Runner, mod: str, before: set[str], args: argparse.Namespace, what: str) -> None:
    """After a mod's download route: wait until the jobs it started end (a route answers at once and
    downloads in the background); a failed job is a failed step."""
    deadline, quiet, last = time.monotonic() + JOB_TIMEOUT_S, 0, ""
    while time.monotonic() < deadline:
        jobs = [j for j in _jobs(runner, mod) if str(j.get("id")) not in before]
        bad = [j for j in jobs if str(j.get("state", "")).lower() in FAILED]
        if bad:
            raise Stop("failed", output=json.dumps(bad[0])[:2000])
        active = [j for j in jobs if str(j.get("state", "")).lower() not in TERMINAL]
        if not active:
            quiet += 1
            if quiet >= 2:
                return
        else:
            quiet = 0
            p = active[0].get("progress")
            line = f"    {what}: {active[0].get('state')}" + (f" {float(p) * 100:.0f}%" if isinstance(p, (int, float)) else "")
            if line != last:
                say(args, line)
                last = line
        runner.sleep(3)
    raise Stop("failed", output=f"{what}: still running after {JOB_TIMEOUT_S // 3600} h")


def download(s: Any, e: Any, root: Path, runner: Runner, args: argparse.Namespace) -> None:
    """One chosen model: through the mod's own route (followed until its job ends), or from Hugging
    Face and then registered with the hub. Raises Stop("failed", …) with what went wrong."""
    if s.op:
        rc, out = runner.run(f"aihub start {e.mod}", root, stream=False)
        if rc:
            raise Stop("failed", output=out)
        before = {str(j.get("id")) for j in _jobs(runner, e.mod)}
        method, path = s.op.split()
        try:
            runner.call(method, f"/api/s/{e.mod}{path}", s.body or None)
        except Exception as x:  # noqa: BLE001: the hub's error, or the mod's
            raise Stop("failed", output=f"{s.op}: {getattr(x, 'detail', x)}") from None
        follow_jobs(runner, e.mod, before, args, s.name)
        return
    rev = f" --revision {s.revision}" if s.revision else ""
    files = "".join(f" {f}" for f in s.files)
    if s.dest == "hf-cache":
        cmd, env, reg = f"uvx --from huggingface_hub hf download {s.repo}{files}{rev}", {"HF_HOME": str(root / "data/models/hf-cache")}, f"hf-cache/hub/models--{s.repo.replace('/', '--')}"
    else:
        cmd, env, reg = f'uvx --from huggingface_hub hf download {s.repo}{files}{rev} --local-dir "data/models/{s.dest}"', None, s.dest
    rc, out = runner.run(cmd, root, env=env, stream=not args.json)
    if rc:
        raise Stop("failed", output=out)
    if s.dest == "hf-cache" and len(s.revision) == 40 and all(c in "0123456789abcdef" for c in s.revision):
        # A download pinned to a commit writes no refs/main, and engines that load by `main` offline
        # (Kokoro) would find nothing: point main at the commit fetched.
        ref = root / "data/models/hf-cache/hub" / f"models--{s.repo.replace('/', '--')}" / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        if not ref.exists():
            ref.write_text(s.revision)
    body = {"path": reg, "name": s.name, "kind": s.kind, "services": [e.mod],
            "source": {"type": "huggingface", "repo": s.repo, **({"revision": s.revision} if s.revision else {})}}
    try:
        runner.call("POST", "/api/models", body)
    except Exception as x:  # noqa: BLE001: 409 model_exists means it's registered already
        if getattr(x, "code", "") != "model_exists":
            raise Stop("failed", output=f"registering it: {getattr(x, 'detail', x)}") from None


def execute(envs: list[Any], p: dict[str, Any], args: argparse.Namespace, answers: Answers, root: Path, code: Path, runner: Runner) -> dict[str, Any]:
    state = {"steps": {}, "models": {}} if args.from_scratch else load_state(root)
    report: dict[str, Any] = {"hub": [], "done": [], "skipped": [], "failed": [], "checks": [], "next": []}
    by_id = {e.id: e for e in envs}

    def fail(item: dict[str, Any]) -> Stop:
        report["failed"].append(item)
        save_state(root, state)
        return Stop("failed", report=report)

    # Every question first (licences, model choices), before the hub stage and any step: a "no"
    # costs nothing, and skips that setup and whatever needs it.
    declined: dict[str, str] = {}
    for s in p["steps"]:
        if s["ask"] and s["setup"] not in declined and state["steps"].get(s["id"]) != "done" and not ask(args, answers, s["id"], s["ask"]):
            declined[s["setup"]] = s["id"]
    skip = dependents(envs, set(declined))
    for sid in sorted(skip):
        why = declined.get(sid)
        report["skipped"].append(f"{sid}: {'declined ' + why if why else 'needs a declined setup'}")
    live = [e for e in envs if e.id not in skip]
    check_mod_answers(answers, live)
    picked = {e.id: models_for(args, answers, e) for e in live if e.setup.suggest}
    report["hub"] = hub_stage(code, runner, stream=not args.json)
    for s in p["steps"]:
        e = by_id[s["setup"]]
        if e.id in skip:
            continue
        if state["steps"].get(s["id"]) == "done":
            report["skipped"].append(f"{s['id']}: done in an earlier run")
            continue
        step = e.setup.steps[int(s["id"].rsplit("/", 1)[1]) - 1]
        if step.interactive and s["id"] in answers.done:
            state["steps"][s["id"]] = "done"
            save_state(root, state)
            report["done"].append(f"{s['id']} (run by you)")
            continue
        if step.interactive and not interactive(args):
            save_state(root, state)
            raise Stop("interactive", id=s["id"], run=s["run"], cwd=f"services/{e.mod}", text=s["what"],
                       answer_with=f"run it yourself in services/{e.mod}, then again with --done {s['id']}", report=report)
        say(args, f"\n==> {s['id']}: {s['what']}\n    $ {s['run']}")
        rc, out = runner.run(s["run"], root / "services" / e.mod, stream=not args.json or step.interactive)
        if rc:
            raise fail({"setup": e.id, "step": s["id"], "run": s["run"], "output": out, "doc": doc_of(e, root)})
        state["steps"][s["id"]] = "done"
        save_state(root, state)
        report["done"].append(s["id"])
    for e in live:
        chosen = picked.get(e.id, [])
        if e.setup.suggest and not chosen:
            report["next"].append(f"{e.id}: no models chosen; to add your own, see {doc_of(e, root)} (Choosing models)")
        for s in chosen:
            key = f"{e.id}:{s.name}"
            if state["models"].get(key) == "done":
                report["skipped"].append(f"{key}: done in an earlier run")
                continue
            say(args, f"\n==> {e.id}: model {s.name} ({s.size_gb:.2f} GB)")
            try:
                download(s, e, root, runner, args)
            except Stop as x:
                raise fail({"setup": e.id, "step": f"model:{s.name}", "output": x.data.get("output", ""), "doc": doc_of(e, root)}) from None
            state["models"][key] = "done"
            save_state(root, state)
            report["done"].append(key)
    for c in p["checks"]:
        e = by_id[c["setup"]]
        if e.id in skip:
            continue
        rc, out = runner.run(c["run"], root / "services" / e.mod, stream=False)   # in the mod's folder, like steps
        report["checks"].append({"setup": e.id, "run": c["run"], "ok": rc == 0, **({"output": out} if rc else {})})
        if rc:
            report["failed"].append({"setup": e.id, "step": "check", "run": c["run"], "output": out, "doc": doc_of(e, root)})
    if report["failed"]:
        report["next"].append("open each failure's doc (What to look for, Known gaps), fix it, and run aihub setup again: it resumes")
    save_state(root, state)
    return report
