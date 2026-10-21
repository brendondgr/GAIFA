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
APPEAR_S = 45                 # how long a download route's job may take to show in the hub's status


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
    values: dict[str, str] = field(default_factory=dict)       # a [[config]] question id (or its key) → value
    providers: list[dict[str, Any]] = field(default_factory=list)  # hosted providers to add to the relay first
    yes: bool = False                                          # the plan is accepted


class Runner:
    """Commands, hub calls and waiting; tests pass a fake."""

    def run(self, cmd: str, cwd: Path, env: dict[str, str] | None = None, stream: bool = True, echo: bool = False) -> tuple[int, str]:
        """`stream`: output straight to the terminal; else captured (its tail returned), and with
        `echo` also copied to stderr as it comes (--json: progress for an agent, stdout stays JSON)."""
        import os
        full = {**os.environ, **(env or {})}
        full["PATH"] = f"{Path(cli.CODE) / 'bin'}:{full.get('PATH', '')}"   # `aihub` before ~/.local/bin is on PATH
        if stream:
            return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=full).returncode, ""
        if not echo:
            p = subprocess.run(["bash", "-c", cmd], cwd=cwd, env=full, capture_output=True, text=True)
            return p.returncode, (p.stdout + p.stderr)[-4000:]
        tail: list[str] = []
        with subprocess.Popen(["bash", "-c", cmd], cwd=cwd, env=full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
            for line in p.stdout or []:
                sys.stderr.write("    " + line)
                tail.append(line)
                del tail[:-200]
        return p.returncode, "".join(tail)[-4000:]

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
        a.values.update({k: str(v) for k, v in data.get("values", {}).items()})
        a.providers += list(data.get("providers", []))
        a.yes = a.yes or bool(data.get("yes"))
    cli_accept, cli_decline = set(getattr(args, "accept", None) or []), set(getattr(args, "decline", None) or [])
    a.accept = (a.accept - cli_decline) | cli_accept      # the command line wins over the answers file
    a.decline = (a.decline - cli_accept) | cli_decline
    a.done |= set(getattr(args, "done", None) or [])
    for spec in getattr(args, "set", None) or []:
        key, _, value = spec.partition("=")
        a.values[key.strip()] = value.strip()
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


def rejoin(names: list[str], known: set[str]) -> list[str]:
    """`--models` splits on commas, but a name may hold one ("Gemma 4 (Q8_0, with vision)"): pieces
    that only make a known name together are put back."""
    out: list[str] = []
    buf = ""
    for part in names:
        cand = f"{buf}, {part}" if buf else part
        if cand in known:
            out.append(cand)
            buf = ""
        elif buf and part in known:       # the piece before was a name of its own (another setup's)
            out += [buf, part]
            buf = ""
        else:
            buf = cand
    if buf:
        out.append(buf)
    return out


def models_for(args: argparse.Namespace, answers: Answers, e: Any) -> list[Any]:
    """The suggestions chosen for one setup. A mod id's answer covers each of its setups, which take
    the names that are theirs; a setup id's answer is that setup's alone."""
    known = {s.name: s for s in e.setup.suggest}
    if e.id in answers.models:
        names = rejoin(answers.models[e.id], set(known))
        unknown = [n for n in names if n not in known]
        if unknown:
            raise Stop("unknown-model", setup=e.id, names=unknown, choices=list(known))
        return [known[n] for n in names]
    if e.mod in answers.models:
        return [known[n] for n in rejoin(answers.models[e.mod], set(known)) if n in known]
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
            unknown = [n for n in rejoin(names, by_mod[key]) if n not in by_mod[key]]
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
    deadline, quiet, last, seen, waited = time.monotonic() + JOB_TIMEOUT_S, 0, "", False, 0.0
    while time.monotonic() < deadline:
        jobs = [j for j in _jobs(runner, mod) if str(j.get("id")) not in before]
        seen = seen or bool(jobs)
        bad = [j for j in jobs if str(j.get("state", "")).lower() in FAILED]
        if bad:
            raise Stop("failed", output=json.dumps(bad[0])[:2000])
        active = [j for j in jobs if str(j.get("state", "")).lower() not in TERMINAL]
        if not active:
            # The hub's status of an idle mod refreshes every 10 s: until the new job has shown up
            # (or 45 s passed, for a route that finished at once), nothing is known yet.
            quiet = quiet + 1 if (seen or waited >= APPEAR_S) else 0
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
        waited += 3
    raise Stop("failed", output=f"{what}: still running after {JOB_TIMEOUT_S // 3600} h")


def download(s: Any, e: Any, root: Path, runner: Runner, args: argparse.Namespace, fetch: bool = True) -> None:
    """One chosen model: through the mod's own route (followed until its job ends), or from Hugging
    Face and then registered with the hub (fetch=False: it's on disk already, only registered).
    Raises Stop("failed", …) with what went wrong."""
    if s.op and not fetch:
        return                            # the mod registered it when it downloaded it
    if s.op:
        rc, out = runner.run(f"aihub start {e.mod}", root, stream=False)
        if rc:
            raise Stop("failed", output=out)
        before = {str(j.get("id")) for j in _jobs(runner, e.mod)}
        method, path = s.op.split()
        try:
            runner.call(method, f"/api/s/{e.mod}{path}", s.body or None)
        except Exception as x:  # noqa: BLE001: the hub's error, or the mod's
            # Refused while an earlier run's download still goes on (a Ctrl-C): wait for it, and
            # the suggestion's skip_if says whether the model is there now.
            if not s.skip_if:
                raise Stop("failed", output=f"{s.op}: {getattr(x, 'detail', x)}") from None
            running = {str(j.get("id")) for j in _jobs(runner, e.mod) if str(j.get("state", "")).lower() not in TERMINAL}
            if running:
                say(args, f"    {s.op} refused ({getattr(x, 'detail', x)}); waiting for the download already running")
                follow_jobs(runner, e.mod, before - running, args, s.name)
            if runner.run(s.skip_if, root / "services" / e.mod, stream=False)[0]:   # or it finished just before
                raise Stop("failed", output=f"{s.op}: {getattr(x, 'detail', x)}") from None
            return
        follow_jobs(runner, e.mod, before, args, s.name)
        return
    rev = f" --revision {s.revision}" if s.revision else ""
    files = "".join(f" {f}" for f in s.files)
    token = Path.home() / ".cache" / "huggingface" / "token"   # `hf auth login`'s, which HF_HOME would hide
    tok = {"HF_TOKEN_PATH": str(token)} if token.is_file() else {}
    if s.dest == "hf-cache":
        cmd, env, reg = f"uvx --from huggingface_hub hf download {s.repo}{files}{rev}", {"HF_HOME": str(root / "data/models/hf-cache"), **tok}, f"hf-cache/hub/models--{s.repo.replace('/', '--')}"
    else:
        cmd, env, reg = f'uvx --from huggingface_hub hf download {s.repo}{files}{rev} --local-dir "data/models/{s.dest}"', tok or None, s.dest
    rc, out = runner.run(cmd, root, env=env, stream=not args.json, echo=args.json) if fetch else (0, "")
    if rc:
        raise Stop("failed", output=out)
    if s.dest == "hf-cache" and len(s.revision) == 40 and all(c in "0123456789abcdef" for c in s.revision):
        # A download pinned to a commit writes no refs/main, and engines that load by `main` offline
        # (Kokoro) would find nothing: point main at the commit fetched.
        ref = root / "data/models/hf-cache/hub" / f"models--{s.repo.replace('/', '--')}" / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        if not ref.exists():
            ref.write_text(s.revision)
    source = {"type": "huggingface", "repo": s.repo, **({"revision": s.revision} if s.revision else {})}
    if s.files and s.dest != "hf-cache":
        # Files into a shared folder (comfyui/): each is its own model, never the whole folder.
        bodies = [{"path": f"{s.dest}/{f}", "name": f"{s.name}: {f.rsplit('/', 1)[-1]}" if len(s.files) > 1 else s.name,
                   "kind": s.kind, "services": [e.mod], "source": source} for f in s.files]
    else:
        bodies = [{"path": reg, "name": s.name, "kind": s.kind, "services": [e.mod], "source": source}]
    for body in bodies:
        try:
            runner.call("POST", "/api/models", body)
        except Exception as x:  # noqa: BLE001: 409 model_exists means it's registered already
            if getattr(x, "code", "") != "model_exists":
                raise Stop("failed", output=f"registering {body['path']}: {getattr(x, 'detail', x)}") from None


def start(s: Any, e: Any, root: Path, runner: Runner, args: argparse.Namespace) -> None:
    """A suggestion's `start_op` after its download: launching the model (lcpp), so it's usable."""
    if not s.start_op:
        return
    runner.run(f"aihub start {e.mod}", root, stream=False)
    method, path = s.start_op.split()
    say(args, f"    starting {s.name}: {s.start_op}")
    try:
        runner.call(method, f"/api/s/{e.mod}{path}", s.start_body or None)
    except Exception as x:  # noqa: BLE001
        raise Stop("failed", output=f"{s.start_op}: {getattr(x, 'detail', x)}") from None


def execute(envs: list[Any], p: dict[str, Any], args: argparse.Namespace, answers: Answers, root: Path, code: Path, runner: Runner) -> dict[str, Any]:
    state = {"steps": {}, "models": {}} if args.from_scratch else load_state(root)
    report: dict[str, Any] = {"hub": [], "done": [], "skipped": [], "failed": [], "checks": [], "next": []}
    by_id = {e.id: e for e in envs}

    def fail(item: dict[str, Any]) -> Stop:
        report["failed"].append(item)
        save_state(root, state)
        return Stop("failed", report=report)

    # A resumed run keeps the earlier run's answers (what's given now wins).
    kept = state.setdefault("answers", {})
    answers.accept |= set(kept.get("accept", [])) - answers.decline
    answers.decline |= set(kept.get("decline", [])) - answers.accept
    for k, v in kept.get("models", {}).items():
        answers.models.setdefault(k, v)
    for k, v in kept.get("values", {}).items():
        answers.values.setdefault(k, v)
    # Every question first (licences, model choices), before the hub stage and any step: a "no"
    # costs nothing, and skips that setup and whatever needs it (an optional step: only itself).
    declined: dict[str, str] = {}
    optional_no: set[str] = set()
    for s in p["steps"]:
        if s["setup"] in dependents(envs, set(declined)):
            continue                      # it's skipped already: its questions don't matter
        if s["ask"] and s["setup"] not in declined and state["steps"].get(s["id"]) != "done" and not ask(args, answers, s["id"], s["ask"]):
            step = by_id[s["setup"]].setup.steps[int(s["id"].rsplit("/", 1)[1]) - 1]
            if step.optional:
                optional_no.add(s["id"])
            else:
                declined[s["setup"]] = s["id"]
    skip = dependents(envs, set(declined))
    for sid in sorted(skip):
        why = declined.get(sid)
        report["skipped"].append(f"{sid}: {'declined ' + why if why else 'needs a declined setup'}")
    live = [e for e in envs if e.id not in skip]
    check_mod_answers(answers, live)
    picked = {e.id: models_for(args, answers, e) for e in live if e.setup.suggest}
    kept.update(accept=sorted(answers.accept), decline=sorted(answers.decline), models={k: [s.name for s in v] for k, v in picked.items()}, values=dict(answers.values))
    save_state(root, state)
    report["hub"] = hub_stage(code, runner, stream=not args.json)
    for s in p["steps"]:
        e = by_id[s["setup"]]
        if e.id in skip:
            continue
        step = e.setup.steps[int(s["id"].rsplit("/", 1)[1]) - 1]
        if state["steps"].get(s["id"]) == "done":
            report["skipped"].append(f"{s['id']}: done in an earlier run")
            report["next"] += [f"{s['id']}: {step.next}"] if step.next else []
            continue
        if s["id"] in optional_no:
            report["skipped"].append(f"{s['id']}: declined (optional)")
            continue
        if step.skip_if and runner.run(step.skip_if, root / "services" / e.mod, stream=False)[0] == 0:
            state["steps"][s["id"]] = "done"
            save_state(root, state)
            report["skipped"].append(f"{s['id']}: nothing to do ({step.skip_if})")
            continue
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
        rc, out = runner.run(s["run"], root / "services" / e.mod, stream=not args.json or step.interactive, echo=args.json)
        if rc:
            raise fail({"setup": e.id, "step": s["id"], "run": s["run"], "output": out, "doc": doc_of(e, root)})
        state["steps"][s["id"]] = "done"
        save_state(root, state)
        report["done"].append(s["id"])
        report["next"] += [f"{s['id']}: {step.next}"] if step.next else []
    if any(e.mod == "relay" or "relay" in e.setup.after for e in live):
        runner.run("aihub start relay", root, stream=False)   # LLM mods publish to it as their models start
    started = False
    for e in live:
        chosen = picked.get(e.id, [])
        if e.setup.suggest and not chosen:
            report["next"].append(f"{e.id}: no models chosen; to add your own, see {doc_of(e, root)} (Choosing models)")
        report["next"] += [f"{e.id}: {s.name}: {s.next}" for s in chosen if s.next]
        missing = [s.name for s in e.setup.suggest if s.required and s not in chosen]
        if chosen and missing:
            report["next"].append(f"{e.id}: {', '.join(missing)} not chosen, and {e.title} can't run without it: its check fails until it's there ({doc_of(e, root)})")
        for s in chosen:
            key = f"{e.id}:{s.name}"
            if state["models"].get(key) == "done":
                report["skipped"].append(f"{key}: done in an earlier run")
                continue
            say(args, f"\n==> {e.id}: model {s.name} ({s.size_gb:.2f} GB)")
            try:
                if state["models"].get(key) == "downloaded":
                    say(args, "    downloaded in an earlier run")
                elif s.skip_if and runner.run(s.skip_if, root / "services" / e.mod, stream=False)[0] == 0:
                    say(args, f"    already there ({s.skip_if})")
                    download(s, e, root, runner, args, fetch=False)
                else:
                    download(s, e, root, runner, args)
                state["models"][key] = "downloaded"
                save_state(root, state)
                start(s, e, root, runner, args)
                started = started or bool(s.start_op)   # launched this run: its model registers on the relay soon
            except Stop as x:
                raise fail({"setup": e.id, "step": f"model:{s.name}", "output": x.data.get("output", ""), "doc": doc_of(e, root)}) from None
            state["models"][key] = "done"
            save_state(root, state)
            report["done"].append(key)
    if __package__:
        from utils import cli_setup_config as config_mod
    else:
        import cli_setup_config as config_mod  # type: ignore[no-redef]
    try:
        config_mod.phase(live, args, answers, root, runner, report, state, started)
    except Stop as x:
        save_state(root, state)
        if x.reason == "failed":
            raise fail({"setup": x.data.get("setup", "config"), "step": x.data.get("step", "config"), "output": x.data.get("output", ""),
                        "doc": x.data.get("doc", "docs/setup/README.md")}) from None
        raise Stop(x.reason, **x.data, report=report) from None
    save_state(root, state)
    for c in p["checks"]:
        e = by_id[c["setup"]]
        if e.id in skip:
            continue
        rc, out = runner.run(c["run"], root / "services" / e.mod, stream=False)   # in the mod's folder, like steps
        report["checks"].append({"setup": e.id, "run": c["run"], "ok": rc == 0, **({"output": out} if rc else {})})
        if rc:
            report["failed"].append({"setup": e.id, "step": "check", "run": c["run"], "output": out, "doc": doc_of(e, root)})
    config_mod.verify(live, root, runner, report)
    if report["failed"]:
        report["next"].append("open each failure's doc (What to look for, Known gaps), fix it, and run aihub setup again: it resumes")
    save_state(root, state)
    return report
