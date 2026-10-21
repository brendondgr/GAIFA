"""`aihub setup` (plan 23.9): one setup process for a person and for an agent working for them.

Stages: the hub, the host checks, choosing mods, the plan, install, models, checks. A person
answers the questions as they come; an agent gets the same plan with `--plan --json`, passes the
person's answers (`--answers`, `--accept`, `--models`) and reads one JSON report. A question with
no answer stops a non-interactive run with its id, so nothing is guessed. Fixes that need root are
printed, never run. Runs resume from `data/state/setup/run.json`. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

cli: Any = None   # utils/cli.py sets this before calling in

if __package__:   # imported as utils.cli_setup (tests); as a script's helper it must not load the utils package
    from utils import cli_setup_host as host_mod
    from utils import setupdocs
else:
    import cli_setup_host as host_mod  # type: ignore[no-redef]
    import setupdocs  # type: ignore[no-redef]

STATE = Path("data") / "state" / "setup" / "run.json"


class Stop(Exception):
    """A run that can't go on: a missing answer, a failed step, a blocking host check."""

    def __init__(self, reason: str, **data: Any) -> None:
        super().__init__(reason)
        self.reason, self.data = reason, data


@dataclass
class Answers:
    accept: set[str] = field(default_factory=set)            # question ids answered yes
    models: dict[str, list[str]] = field(default_factory=dict)  # setup id (or mod id) → suggestion names; [] = none
    yes: bool = False                                          # the plan is accepted


class Runner:
    """Commands and hub calls; tests pass a fake."""

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


# ---- choosing and ordering ---------------------------------------------------------------


def choices(root: Path) -> tuple[dict[str, setupdocs.Env], list[str]]:
    """The setup docs the wizard offers (those with a summary), by id, and the problems of the rest."""
    envs, problems = setupdocs.load_envs(root)
    return {e.id: e for e in envs if e.setup.summary}, [f"{p}: {m}" for p, m in problems.items()]


def _order(root: Path) -> list[str]:
    try:
        return list(tomllib.loads((root / "config.toml").read_text()).get("services", {}).get("order", []))
    except (OSError, tomllib.TOMLDecodeError):
        return []


def resolve(targets: list[str], offered: dict[str, setupdocs.Env], root: Path) -> list[setupdocs.Env]:
    """Mod ids (all their setup docs) or setup ids, plus what they need (`after`), dependencies first."""
    chosen: dict[str, setupdocs.Env] = {}
    by_mod: dict[str, list[setupdocs.Env]] = {}
    for e in offered.values():
        by_mod.setdefault(e.mod, []).append(e)

    def add(eid: str, why: str) -> None:
        if eid in chosen:
            return
        if eid not in offered:
            raise Stop("unknown", id=eid, why=why, choices=sorted(set(offered) | set(by_mod)))
        chosen[eid] = offered[eid]
        for dep in offered[eid].setup.after:
            for d in [x.id for x in by_mod[dep]] if dep in by_mod and dep not in offered else [dep]:
                add(d, f"{eid} needs it")

    for t in targets:
        for eid in [x.id for x in sorted(by_mod[t], key=lambda x: x.id)] if t in by_mod and t not in offered else [t]:
            add(eid, "asked for")
    rank = {m: i for i, m in enumerate(_order(root))}
    key = lambda e: (rank.get(e.mod, len(rank)), e.mod, e.id)  # noqa: E731
    done: list[setupdocs.Env] = []
    seen: set[str] = set()

    def visit(e: setupdocs.Env, path: tuple[str, ...]) -> None:
        if e.id in seen:
            return
        if e.id in path:
            raise Stop("cycle", ids=list(path) + [e.id])
        deps = [x for x in chosen.values() if x.id != e.id and (x.id in e.setup.after or (x.mod in e.setup.after and x.mod != e.mod))]
        for dep in sorted(deps, key=key):
            visit(dep, path + (e.id,))
        seen.add(e.id)
        done.append(e)

    for e in sorted(chosen.values(), key=key):
        visit(e, ())
    return done


# ---- the plan -----------------------------------------------------------------------------


def plan(envs: list[setupdocs.Env], checks: list[host_mod.Check]) -> dict[str, Any]:
    steps, questions, suggestions = [], [], []
    for e in envs:
        for n, s in enumerate(e.setup.steps, 1):
            sid = f"{e.id}/{n}"
            steps.append({"id": sid, "setup": e.id, "mod": e.mod, "run": s.run, "what": s.what, "ask": s.ask or None})
            if s.ask:
                questions.append({"id": sid, "kind": "yes-no", "text": s.ask})
        if e.setup.suggest:
            names = [s.name for s in e.setup.suggest]
            questions.append({"id": f"{e.id}/models", "kind": "models", "text": f"Which models for {e.title}?",
                              "choices": names, "required": [s.name for s in e.setup.suggest if s.required]})
            for s in e.setup.suggest:
                suggestions.append({"setup": e.id, "mod": e.mod, "name": s.name, "size_gb": s.size_gb, "good_for": s.good_for,
                                    "licence": s.licence or None, "required": s.required, "gated": s.gated,
                                    "source": s.repo or f"{e.mod} {s.op}"})
    gpu = any(e.setup.gpu for e in envs)
    return {"setups": [e.id for e in envs], "mods": sorted({e.mod for e in envs}), "gpu": gpu,
            "disk_gb": round(sum(e.setup.disk_gb or 0 for e in envs), 2),
            "required_models_gb": round(sum(s["size_gb"] for s in suggestions if s["required"]), 2),
            "steps": steps, "questions": questions, "suggestions": suggestions,
            "host": [c.dump() for c in checks], "blocking": [c.id for c in host_mod.blocking(checks, gpu)],
            "checks": [{"setup": e.id, "run": e.setup.check} for e in envs if e.setup.check]}


def plan_text(p: dict[str, Any]) -> str:
    out = [f"Setup plan: {', '.join(p['setups'])}  (environments {p['disk_gb']:.1f} GB, required models {p['required_models_gb']:.1f} GB)", ""]
    for s in p["steps"]:
        out.append(f"  {s['id']:24} {s['run']}")
        out.append(f"  {'':24}   {s['what']}" + (f"  [asks: {s['ask']}]" if s["ask"] else ""))
    if p["suggestions"]:
        out += ["", "Models (you choose; required ones are preselected):"]
        for s in p["suggestions"]:
            out.append(f"  {s['setup']:24} {s['name']} ({s['size_gb']:.2f} GB){' required' if s['required'] else ''}{' gated' if s['gated'] else ''}: {s['good_for']}")
    if p["blocking"]:
        out += ["", f"Host checks to fix first: {', '.join(p['blocking'])} (aihub setup host)"]
    return "\n".join(out)


# ---- answers ---------------------------------------------------------------------------------


def read_answers(args: argparse.Namespace) -> Answers:
    a = Answers(yes=bool(args.yes))
    if args.answers:
        data = json.loads(Path(args.answers).read_text())
        a.accept |= set(data.get("accept", []))
        a.models.update({k: list(v) for k, v in data.get("models", {}).items()})
        a.yes = a.yes or bool(data.get("yes"))
    a.accept |= set(args.accept or [])
    for spec in args.models or []:
        key, _, names = spec.partition("=")
        a.models[key.strip()] = [n.strip() for n in names.split(",") if n.strip() and n.strip() != "none"]
    return a


def _interactive(args: argparse.Namespace) -> bool:
    return not args.json and sys.stdin.isatty()


def ask_yes(args: argparse.Namespace, answers: Answers, qid: str, text: str) -> bool:
    if qid in answers.accept:
        return True
    if not _interactive(args):
        raise Stop("question", id=qid, kind="yes-no", text=text)
    yes = input(f"{text} [y/N] ").strip().lower() in ("y", "yes")
    if yes:
        answers.accept.add(qid)
    return yes


def models_for(args: argparse.Namespace, answers: Answers, e: setupdocs.Env) -> list[setupdocs.block.Suggest]:
    names = answers.models.get(e.id, answers.models.get(e.mod))
    if names is None:
        if not _interactive(args):
            raise Stop("question", id=f"{e.id}/models", kind="models", choices=[s.name for s in e.setup.suggest],
                       required=[s.name for s in e.setup.suggest if s.required])
        print(f"\nModels for {e.title} (see its setup doc's Choosing models to add your own):")
        for i, s in enumerate(e.setup.suggest, 1):
            print(f"  {i}. {s.name} ({s.size_gb:.2f} GB){' required' if s.required else ''}{' gated' if s.gated else ''}: {s.good_for}")
        default = ",".join(str(i) for i, s in enumerate(e.setup.suggest, 1) if s.required) or "none"
        pick = input(f"Numbers, comma-separated, or none [{default}]: ").strip() or default
        names = [] if pick == "none" else [e.setup.suggest[int(x) - 1].name for x in pick.split(",") if x.strip().isdigit() and 0 < int(x) <= len(e.setup.suggest)]
    known = {s.name: s for s in e.setup.suggest}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise Stop("unknown-model", setup=e.id, names=unknown, choices=list(known))
    return [known[n] for n in names]


# ---- the run ------------------------------------------------------------------------------------


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


def doc_of(e: setupdocs.Env, root: Path) -> str:
    return e.path.relative_to(root).as_posix() if e.path.is_relative_to(root) else str(e.path)


def hub_stage(root: Path, code: Path, runner: Runner, stream: bool) -> dict[str, Any]:
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
    return {"stage": "hub", "done": done or ["already installed and running"]}


def download(s: setupdocs.block.Suggest, e: setupdocs.Env, root: Path, runner: Runner, stream: bool) -> None:
    """One suggested model: through the mod's own route, or Hugging Face then registered with the hub."""
    if s.op:
        runner.run(f"aihub start {e.mod}", root, stream=False)
        method, path = s.op.split()
        runner.call(method, f"/api/s/{e.mod}{path}", s.body or None)
        return
    rev = f" --revision {s.revision}" if s.revision else ""
    files = "".join(f" {f}" for f in s.files)
    if s.dest == "hf-cache":
        cmd, env, reg = f"uvx --from huggingface_hub hf download {s.repo}{files}{rev}", {"HF_HOME": str(root / "data/models/hf-cache")}, f"hf-cache/hub/models--{s.repo.replace('/', '--')}"
    else:
        cmd, env, reg = f'uvx --from huggingface_hub hf download {s.repo}{files}{rev} --local-dir "data/models/{s.dest}"', None, s.dest
    rc, out = runner.run(cmd, root, env=env, stream=stream)
    if rc:
        raise Stop("failed", step=f"{e.id}/model:{s.name}", output=out, doc=doc_of(e, root))
    if s.dest == "hf-cache" and len(s.revision) == 40 and all(c in "0123456789abcdef" for c in s.revision):
        # A download pinned to a commit writes no refs/main, and engines that load by `main` offline
        # (Kokoro) would find nothing: point main at the commit we fetched.
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
            raise Stop("failed", step=f"{e.id}/register:{s.name}", output=str(x), doc=doc_of(e, root)) from None


def execute(envs: list[setupdocs.Env], p: dict[str, Any], args: argparse.Namespace, answers: Answers, root: Path, runner: Runner) -> dict[str, Any]:
    stream = not args.json
    state = {"steps": {}, "models": {}} if args.from_scratch else load_state(root)
    report: dict[str, Any] = {"done": [], "skipped": [], "failed": [], "checks": [], "next": []}
    by_id = {e.id: e for e in envs}
    # Every question first (licences, model choices), so nothing runs until all are answered and a
    # "no" costs nothing: no download or install happens before it.
    for s in p["steps"]:
        if s["ask"] and state["steps"].get(s["id"]) != "done" and not ask_yes(args, answers, s["id"], s["ask"]):
            report["next"].append(f"{s['id']} was declined: {s['ask']}; choose other mods, or answer yes")
            raise Stop("declined", id=s["id"], report=report)
    picked = {e.id: models_for(args, answers, e) for e in envs if e.setup.suggest}
    for s in p["steps"]:
        e = by_id[s["setup"]]
        if state["steps"].get(s["id"]) == "done":
            report["skipped"].append(s["id"])
            continue
        if stream:
            print(f"\n==> {s['id']}: {s['what']}\n    $ {s['run']}", flush=True)
        rc, out = runner.run(s["run"], root / "services" / e.mod, stream=stream)
        if rc:
            report["failed"].append({"setup": e.id, "step": s["id"], "run": s["run"], "output": out, "doc": doc_of(e, root)})
            save_state(root, state)
            raise Stop("failed", report=report)
        state["steps"][s["id"]] = "done"
        save_state(root, state)
        report["done"].append(s["id"])
    for e in envs:
        for s in picked.get(e.id, []):
            key = f"{e.id}:{s.name}"
            if state["models"].get(key) == "done":
                report["skipped"].append(key)
                continue
            if stream:
                print(f"\n==> {e.id}: model {s.name} ({s.size_gb:.2f} GB)", flush=True)
            download(s, e, root, runner, stream)
            state["models"][key] = "done"
            save_state(root, state)
            report["done"].append(key)
    for c in p["checks"]:
        rc, out = runner.run(c["run"], root / "services" / by_id[c["setup"]].mod, stream=False)   # in the mod's folder, like steps
        report["checks"].append({"setup": c["setup"], "run": c["run"], "ok": rc == 0, **({"output": out} if rc else {})})
        if rc:
            report["failed"].append({"setup": c["setup"], "step": "check", "run": c["run"], "output": out, "doc": doc_of(by_id[c["setup"]], root)})
    if report["failed"]:
        report["next"].append("open each failure's doc (What to look for, Known gaps), fix it, and run aihub setup again: it resumes")
    return report


# ---- the command -------------------------------------------------------------------------------


def emit(args: argparse.Namespace, data: dict[str, Any], text: str) -> None:
    print(json.dumps(data, indent=1) if args.json else text, flush=True)


def cmd_setup(args: argparse.Namespace, runner: Runner | None = None, probe: host_mod.Probe | None = None) -> int:
    runner, probe = runner or Runner(), probe or host_mod.Probe()
    root, code = Path(cli.ROOT), Path(cli.CODE)
    targets = list(args.targets or [])
    try:
        if targets[:1] == ["hub"]:
            r = hub_stage(root, code, runner, stream=not args.json)
            emit(args, r, "hub: " + ", ".join(r["done"]))
            return 0
        offered, problems = choices(root)
        if targets[:1] == ["host"]:
            found = host_mod.checks(probe, root)
            emit(args, {"stage": "host", "host": [c.dump() for c in found]}, host_mod.text(found))
            return 0 if all(c.ok or c.id == "linger" for c in found) else 1
        if not targets:
            if not _interactive(args):
                emit(args, {"stage": "choose", "choices": [{"id": e.id, "mod": e.mod, "summary": e.setup.summary, "gpu": e.setup.gpu, "disk_gb": e.setup.disk_gb} for e in offered.values()], "problems": problems},
                     "\n".join(f"  {e.id:24} {e.setup.summary}" for e in offered.values()))
                return 0
            ids = sorted(offered, key=lambda i: (offered[i].mod, i))
            for n, i in enumerate(ids, 1):
                e = offered[i]
                print(f"  {n:2}. {i:24} {'GPU ' if e.setup.gpu else '    '}{(e.setup.disk_gb or 0):5.1f} GB  {e.setup.summary}")
            pick = input("Which? numbers or ids, comma-separated: ")
            targets = [ids[int(x) - 1] if x.strip().isdigit() else x.strip() for x in pick.split(",") if x.strip()]
        envs = resolve(targets, offered, root)
        needs = {n for e in envs for n in e.setup.needs}
        found = host_mod.checks(probe, root, needs, sum(e.setup.disk_gb or 0 for e in envs))
        p = plan(envs, found)
        if args.plan:
            emit(args, {"stage": "plan", **p}, plan_text(p))
            return 0
        if p["blocking"]:
            raise Stop("host", checks=[c.dump() for c in found if c.id in p["blocking"]])
        answers = read_answers(args)
        if not answers.yes:
            if not _interactive(args):
                raise Stop("question", id="plan", kind="yes-no", text="Run this plan?", plan=p)
            print(plan_text(p))
            if input("\nRun it? [y/N] ").strip().lower() not in ("y", "yes"):
                return 1
        hub = hub_stage(root, code, runner, stream=not args.json)
        report = {"stage": "report", "hub": hub["done"], **execute(envs, p, args, answers, root, runner)}
        ok = not report["failed"]
        emit(args, report, ("Done: " if ok else "Not done: ") + f"{len(report['done'])} steps, {len(report['failed'])} failed" +
             "".join(f"\n  failed {f['step']}: see {f['doc']}" for f in report["failed"]))
        return 0 if ok else 1
    except Stop as s:
        data = {"stage": "stopped", "reason": s.reason, **s.data}
        lines = {"question": f"stopped: question {s.data.get('id')} needs an answer (--accept / --models / --answers)",
                 "host": "stopped: fix the host first:\n" + host_mod.text([host_mod.Check(**c) for c in s.data.get("checks", [])]),
                 "unknown": f"stopped: no setup doc {s.data.get('id')!r}; choose from: {', '.join(s.data.get('choices', []))}"}
        emit(args, data, lines.get(s.reason, f"stopped: {s.reason} {json.dumps({k: v for k, v in s.data.items() if k != 'report'})[:600]}"))
        return 2 if s.reason == "question" else 1


def add_parser(sub: Any) -> None:
    p = sub.add_parser("setup", help="set up AIHub: the hub, the host checks, the mods you choose, their models, their checks (docs/setup/)")
    p.add_argument("targets", nargs="*", metavar="mod", help="mods or setup ids; `hub` or `host` for one stage; none: choose from a list")
    p.add_argument("--plan", action="store_true", help="print the plan (steps, questions, models, host) and stop")
    p.add_argument("--json", action="store_true", help="one JSON result per stage; never prompts (for agents)")
    p.add_argument("--yes", action="store_true", help="accept the plan without asking")
    p.add_argument("--answers", metavar="FILE", help='answers as JSON: {"accept": [question ids], "models": {"<setup or mod id>": [names]}, "yes": true}')
    p.add_argument("--accept", action="append", metavar="ID", help="answer yes to a question (repeatable)")
    p.add_argument("--models", action="append", metavar="ID=NAMES", help="models for a setup or mod: names comma-separated, or none (repeatable)")
    p.add_argument("--from-scratch", action="store_true", help="forget which steps a previous run finished")
