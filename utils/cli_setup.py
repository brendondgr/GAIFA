"""`aihub setup` (plan 23.9, 23.10): one setup process for a person and for an agent working for them.

Stages: the hub, the host checks, choosing mods, the plan, the questions, install, models, checks.
A person answers the questions as they come; an agent gets the same plan with `--plan --json`,
passes the person's answers (`--answers`, `--accept`, `--decline`, `--models`, `--done`) and reads
one JSON report. A question with no answer stops a non-interactive run with its id, so nothing is
guessed. Fixes that need root are printed, never run. Runs resume from `data/state/setup/run.json`.
Standard library only. The answers and the run are in cli_setup_run.py.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

cli: Any = None   # utils/cli.py sets this before calling in

if __package__:   # imported as utils.cli_setup (tests); as a script's helper it must not load the utils package
    from utils import cli_setup_host as host_mod
    from utils import cli_setup_run as run_mod
    from utils import setupdocs
else:
    import cli_setup_host as host_mod  # type: ignore[no-redef]
    import cli_setup_run as run_mod  # type: ignore[no-redef]
    import setupdocs  # type: ignore[no-redef]

Stop, Answers, Runner = run_mod.Stop, run_mod.Answers, run_mod.Runner
EXIT = """exit codes: 0 done (or a plan printed); 1 failed, stopped by the host, or unknown; 2 a question needs an answer, or an interactive step needs you.
value questions (the agent's model) come after install, since their choices (the relay's models) exist only then.
under --json stdout is one JSON object: {"stage": "plan" | "report" | "stopped" | "host" | "choose" | "hub", …};
a stop has "reason" ("question", "interactive", "failed", "host", "unknown", "unknown-model", "unknown-value", "cycle") and,
for a question, "id", "kind" (yes-no, models or value), "choices" and "answer_with". A report has done, skipped, failed (each with its doc), checks, next.
progress lines go to stderr. docs: docs/setup/README.md; each mod's services/<id>/setup/*.md"""


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


def sizes(envs: list[setupdocs.Env]) -> tuple[float, float, dict[str, float]]:
    """(environments, required models, images) in GB; an image two setups pull counts once."""
    images: dict[str, float] = {}
    for e in envs:
        images.update(e.setup.images)
    env = sum(e.setup.disk_gb or 0 for e in envs) + sum(images.values())
    req = sum(s.size_gb for e in envs for s in e.setup.suggest if s.required)
    return round(env, 2), round(req, 2), images


def plan(envs: list[setupdocs.Env], checks: list[host_mod.Check], hub: list[str] | None = None, expanded: dict[str, list[str]] | None = None) -> dict[str, Any]:
    steps, questions, suggestions = [], [], []
    for e in envs:
        for n, s in enumerate(e.setup.steps, 1):
            sid = f"{e.id}/{n}"
            steps.append({"id": sid, "setup": e.id, "mod": e.mod, "run": s.run, "what": s.what, "ask": s.ask or None, "interactive": s.interactive})
            if s.ask:
                questions.append({"id": sid, "kind": "yes-no", "text": s.ask, "answer_with": f"--accept {sid} or --decline {sid}"})
        if e.setup.suggest:
            names = [s.name for s in e.setup.suggest]
            questions.append({"id": f"{e.id}/models", "kind": "models", "text": f"Which models for {e.title}?",
                              "choices": names, "required": [s.name for s in e.setup.suggest if s.required],
                              "answer_with": f'--models "{e.id}=<names, comma-separated, or none>"'})
            for s in e.setup.suggest:
                suggestions.append({"setup": e.id, "mod": e.mod, "name": s.name, "size_gb": s.size_gb, "good_for": s.good_for,
                                    "licence": s.licence or None, "required": s.required, "gated": s.gated,
                                    "source": s.repo or f"{e.mod} {s.op}"})
        for c in e.setup.config:
            qid = f"{e.id}/config:{c.key}"
            questions.append({"id": qid, "kind": "value", "text": c.text, "required": c.required, "after_install": True,
                              "choices": "the relay's models, once it runs" if c.choices == "relay-models" else list(c.choices),
                              "answer_with": f'--set "{qid}=<value>"'})
    gpu = any(e.setup.gpu for e in envs)
    env_gb, req_gb, images = sizes(envs)
    return {"setups": [e.id for e in envs], "mods": sorted({e.mod for e in envs}), "expanded": expanded or {}, "gpu": gpu,
            "hub": hub or [], "disk_gb": env_gb, "images": images, "required_models_gb": req_gb,
            "steps": steps, "questions": questions, "suggestions": suggestions,
            "host": [c.dump() for c in checks], "blocking": [c.id for c in host_mod.blocking(checks, gpu)],
            "checks": [{"setup": e.id, "run": e.setup.check} for e in envs if e.setup.check]}


def plan_text(p: dict[str, Any]) -> str:
    out = [f"Setup plan: {', '.join(p['setups'])}",
           f"  disk: environments {p['disk_gb']:.1f} GB (images counted once) + required models {p['required_models_gb']:.1f} GB", ""]
    for mod, ids in p["expanded"].items():
        out.append(f"  `{mod}` means {', '.join(ids)}: name one of these to set up only it")
    if p["expanded"]:
        out.append("")
    out.append("The hub: " + ("; ".join(p["hub"]) if p["hub"] else "installed and running"))
    out.append("")
    for s in p["steps"]:
        out.append(f"  {s['id']:24} {s['run']}")
        out.append(f"  {'':24}   {s['what']}" + (f"  [asks: {s['ask']}]" if s["ask"] else "") + ("  [you run it: it prompts]" if s["interactive"] else ""))
    if p["suggestions"]:
        out += ["", "Models (you choose; required ones are preselected):"]
        for s in p["suggestions"]:
            out.append(f"  {s['setup']:24} {s['name']} ({s['size_gb']:.2f} GB){' required' if s['required'] else ''}{' gated' if s['gated'] else ''}: {s['good_for']}")
    values = [q for q in p["questions"] if q["kind"] == "value"]
    if values:
        out += ["", "After install, it asks (the choices exist only then):"] + [f"  {q['id']:24} {q['text']}{'' if q['required'] else ' (optional)'}" for q in values]
    if p["checks"]:
        out += ["", "Then each check: " + "; ".join(c["run"] for c in p["checks"])]
    bad = [c for c in p["host"] if not c["ok"]]
    out += ["", f"Host: {len(p['host']) - len(bad)} checks ok" + (", to fix first: " + ", ".join(c["id"] for c in bad if c["id"] in p["blocking"]) if p["blocking"] else "")
            + ("" if not bad or p["blocking"] else f" ({', '.join(c['id'] for c in bad)}: advice)") + "  (aihub setup host)"]
    return "\n".join(out)


# ---- the command -------------------------------------------------------------------------------


def emit(args: argparse.Namespace, data: dict[str, Any], text: str) -> None:
    print(json.dumps(data, indent=1) if args.json else text, flush=True)


def cmd_setup(args: argparse.Namespace, runner: Runner | None = None, probe: host_mod.Probe | None = None) -> int:
    run_mod.cli = cli
    runner, probe = runner or Runner(), probe or host_mod.Probe()
    root, code = Path(cli.ROOT), Path(cli.CODE)
    targets = list(args.targets or [])
    try:
        if targets[:1] == ["hub"]:
            done = run_mod.hub_stage(code, runner, stream=not args.json)
            emit(args, {"stage": "hub", "done": done}, "hub: " + ", ".join(done))
            return 0
        offered, problems = choices(root)
        if targets[:1] == ["host"]:
            found = host_mod.checks(probe, root)
            emit(args, {"stage": "host", "host": [c.dump() for c in found]}, host_mod.text(found) + "\n(GPU checks matter only for mods that use the GPU)")
            return 1 if host_mod.blocking(found, gpu=False) else 0
        if not targets:
            if not run_mod.interactive(args):
                emit(args, {"stage": "choose", "choices": [{"id": e.id, "mod": e.mod, "summary": e.setup.summary, "gpu": e.setup.gpu, "disk_gb": e.setup.disk_gb, "after": e.setup.after} for e in offered.values()], "problems": problems},
                     "\n".join(f"  {e.id:24} {e.setup.summary}" for e in offered.values()))
                return 0
            ids = sorted(offered, key=lambda i: (offered[i].mod, i))
            for n, i in enumerate(ids, 1):
                e = offered[i]
                print(f"  {n:2}. {i:24} {'GPU ' if e.setup.gpu else '    '}{(e.setup.disk_gb or 0):5.1f} GB  {e.setup.summary}")
            pick = input("Which? numbers or ids, comma-separated: ")
            targets = [ids[int(x) - 1] if x.strip().isdigit() else x.strip() for x in pick.split(",") if x.strip()]
        envs = resolve(targets, offered, root)
        expanded = {t: [e.id for e in envs if e.mod == t] for t in targets if t not in offered and len([e for e in envs if e.mod == t]) > 1}
        env_gb, req_gb, _ = sizes(envs)
        found = host_mod.checks(probe, root, {n for e in envs for n in e.setup.needs}, env_gb + req_gb)
        p = plan(envs, found, run_mod.hub_needs(code, runner), expanded)
        if args.plan:
            emit(args, {"stage": "plan", **p}, plan_text(p))
            return 0
        if p["blocking"]:
            raise Stop("host", checks=[c.dump() for c in found if c.id in p["blocking"]])
        answers = run_mod.read_answers(args)
        if not answers.yes:
            if not run_mod.interactive(args):
                raise Stop("question", id="plan", kind="yes-no", text="Run this plan?", answer_with="--yes", plan=p)
            print(plan_text(p))
            if input("\nRun it? [y/N] ").strip().lower() not in ("y", "yes"):
                return 1
        report = {"stage": "report", **run_mod.execute(envs, p, args, answers, root, code, runner)}
        ok = not report["failed"]
        emit(args, report, ("Done: " if ok else "Not done: ") + f"{len(report['done'])} steps and models, {len(report['failed'])} failed" +
             "".join(f"\n  failed {f['step']}: see {f['doc']}" for f in report["failed"]) +
             "".join(f"\n  skipped {s}" for s in report["skipped"] if "declined" in s or "needs a declined" in s) +
             "".join(f"\n  next: {n}" for n in report["next"]))
        return 0 if ok else 1
    except Stop as s:
        data = {"stage": "stopped", "reason": s.reason, **s.data}
        lines = {"question": f"stopped: question {s.data.get('id')} needs an answer ({s.data.get('answer_with', '--answers')})",
                 "interactive": f"stopped: {s.data.get('id')} prompts, so run it yourself in {s.data.get('cwd')}:\n    {s.data.get('run')}\nthen: {s.data.get('answer_with')}",
                 "host": "stopped: fix the host first:\n" + host_mod.text([host_mod.Check(**c) for c in s.data.get("checks", [])]),
                 "unknown": f"stopped: no setup doc {s.data.get('id')!r}; choose from: {', '.join(s.data.get('choices', []))}"}
        emit(args, data, lines.get(s.reason, f"stopped: {s.reason} {json.dumps({k: v for k, v in s.data.items() if k != 'report'})[:600]}"))
        return 2 if s.reason in ("question", "interactive") else 1


def add_parser(sub: Any) -> None:
    p = sub.add_parser("setup", help="set up AIHub: the hub, the host checks, the mods you choose, their models, their checks (docs/setup/)",
                       epilog=EXIT, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("targets", nargs="*", metavar="mod", help="mods or setup ids; `hub` or `host` for one stage; none: choose from a list")
    p.add_argument("--plan", action="store_true", help="print the plan (the hub, steps, questions, models, checks, host) and stop")
    p.add_argument("--json", action="store_true", help="one JSON result on stdout, progress on stderr; never prompts (for agents)")
    p.add_argument("--yes", action="store_true", help="accept the plan without asking")
    p.add_argument("--answers", metavar="FILE", help='answers as JSON: {"yes": true, "accept": [ids], "decline": [ids], "done": [ids], "models": {"<setup or mod id>": [names]}, "values": {"<id or key>": "value"}, "providers": [{"name", "base_url", "key", "models": [names]}]}')
    p.add_argument("--accept", action="append", metavar="ID", help="answer yes to a question (repeatable)")
    p.add_argument("--decline", action="append", metavar="ID", help="answer no: that setup, and what needs it, is skipped (repeatable)")
    p.add_argument("--models", action="append", metavar="ID=NAMES", help="models for a setup (or each setup of a mod): names comma-separated, or none (repeatable)")
    p.add_argument("--done", action="append", metavar="ID", help="an interactive step you ran yourself (repeatable)")
    p.add_argument("--set", action="append", metavar="ID=VALUE", help="a value question's answer, by its id or config key, e.g. agent/config:services.agent.env.AGENT_MODEL=gpt-4o (repeatable)")
    p.add_argument("--from-scratch", action="store_true", help="forget which steps a previous run finished")
