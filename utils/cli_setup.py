"""`gaifa setup` (plan 23.9, 23.10): one setup process for a person and for an agent working for them.

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
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

cli: Any = None   # utils/cli.py sets this before calling in

if __package__:   # imported as utils.cli_setup (tests); as a script's helper it must not load the utils package
    from utils import cli_setup_host as host_mod
    from utils import cli_setup_repos as repos_mod
    from utils import cli_setup_run as run_mod
    from utils import cli_setup_variant as variant_mod
    from utils import setupdocs
else:
    import cli_setup_host as host_mod  # type: ignore[no-redef]
    import cli_setup_repos as repos_mod  # type: ignore[no-redef]
    import cli_setup_run as run_mod  # type: ignore[no-redef]
    import cli_setup_variant as variant_mod  # type: ignore[no-redef]
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


def needs_of(e: setupdocs.Env, values: dict[str, str] | None = None) -> list[str]:
    """What a setup needs first: its `after`, and what its choices' answers add (capability-enablement 6.2: the relay
    unless Chat uses a server of yours), the default answer when none is given."""
    adds = [d for c in e.setup.choose for d in c.option((values or {}).get(f"{e.id}/choose:{c.id}")).adds]
    return [*e.setup.after, *[d for d in adds if d not in e.setup.after]]


def resolve(targets: list[str], offered: dict[str, setupdocs.Env], root: Path, values: dict[str, str] | None = None) -> list[setupdocs.Env]:
    """Mod ids (all their setup docs) or setup ids, plus what they need (`after`, a choice's `adds`), dependencies first."""
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
        for dep in needs_of(offered[eid], values):
            for d in [x.id for x in by_mod[dep]] if dep in by_mod and dep not in offered else [dep]:
                add(d, f"{eid} needs it")

    for t in targets:
        # What you ask for: a mod id means all of that mod's setups, even where one setup shares its id
        # (gen3d's base); inside `after`, a setup id wins (an engine needs the base, not its siblings).
        for eid in [x.id for x in sorted(by_mod[t], key=lambda x: x.id)] if t in by_mod else [t]:
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
        need = needs_of(e, values)
        deps = [x for x in chosen.values() if x.id != e.id and (x.id in need or (x.mod in need and x.mod != e.mod))]
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
        for ch in e.setup.choose:                 # capability-enablement 6.2: asked before anything is installed
            questions.append({"id": f"{e.id}/choose:{ch.id}", "kind": "choice", "text": ch.text, "default": ch.default,
                              "choices": [o.value for o in ch.options], "labels": {o.value: o.label for o in ch.options},
                              "adds": {o.value: o.adds for o in ch.options if o.adds},
                              "answer_with": f'--set "{e.id}/choose:{ch.id}=<{"|".join(o.value for o in ch.options)}>" (default {ch.default})'})
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
            qid = f"{e.id}/config:{c.key}" + (f"@{c.when}" if c.when else "")
            questions.append({"id": qid, "kind": "value", "text": c.text, "required": c.required, "after_install": True,
                              **({"when": c.when} if c.when else {}), **({"secret": True} if c.secret else {}),
                              "choices": "the relay's models, once it runs" if c.choices == "relay-models" else
                              "the server's models, once its URL is given" if c.choices == "endpoint-models" else
                              c.choices if c.choices in ("folder", "text") else list(c.choices),
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
    if p.get("variants"):
        out += ["", "Variants (gaifa hardware; --accel <setup>=<accel> to pick another):"]
        for v in p["variants"]:
            out.append(f"  {v['setup']:24} {v['label']}" + ("  [untested on this kind of machine]" if v["untested"] else "") + (f"  ({v['note']})" if v["note"] else ""))
    if (p.get("checkouts") or {}).get("done"):
        out += ["", "Checked out (their own repositories): " + ", ".join(p["checkouts"]["done"])]
    if p.get("unavailable"):
        out += ["", "Not available on this machine:"] + [f"  {u['setup']:24} {u['why']}" for u in p["unavailable"]]
    if p["checks"]:
        out += ["", "Then each check: " + "; ".join(c["run"] for c in p["checks"])]
    if p.get("smokes"):
        out += ["Then each smoke (real work): " + "; ".join(s["run"] for s in p["smokes"])]
    bad = [c for c in p["host"] if not c["ok"]]
    out += ["", f"Host: {len(p['host']) - len(bad)} checks ok" + (", to fix first: " + ", ".join(c["id"] for c in bad if c["id"] in p["blocking"]) if p["blocking"] else "")
            + ("" if not bad or p["blocking"] else f" ({', '.join(c['id'] for c in bad)}: advice)") + "  (gaifa setup host)"]
    return "\n".join(out)


# ---- the command -------------------------------------------------------------------------------


_last: dict[str, Any] = {}     # plan 40.1: what this run saw, saved with its outcome (data/state/setup/last-run.json)


def save_last_run(data: dict[str, Any]) -> None:
    """The run's outcome, its plan, variants and machine, for `gaifa report` (plan 40.2). Never fails the run."""
    try:
        p = Path(cli.ROOT) / run_mod.LAST_RUN
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({**_last, "ts": time.time(), "argv": sys.argv[1:], "result": data}, indent=1, default=str))
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        pass


def emit(args: argparse.Namespace, data: dict[str, Any], text: str) -> None:
    if data.get("stage") in ("report", "stopped"):
        save_last_run(data)
    print(json.dumps(data, indent=1) if args.json else text, flush=True)


def cmd_setup(args: argparse.Namespace, runner: Runner | None = None, probe: host_mod.Probe | None = None) -> int:
    run_mod.cli = cli
    runner, probe = runner or Runner(), probe or host_mod.Probe()
    root, code = Path(cli.ROOT), Path(cli.CODE)
    targets = list(args.targets or [])
    if getattr(args, "prompt", False):        # capability-enablement 3.2: the text for your own coding agent
        if __package__:
            from utils.setup_prompt import coding_agent_prompt
        else:                                  # loaded by bin/gaifa from utils/ (cli._setup)
            from setup_prompt import coding_agent_prompt  # type: ignore[no-redef]
        print(coding_agent_prompt(root, targets), end="")
        return 0
    try:
        if targets[:1] == ["hub"]:
            done = run_mod.hub_stage(code, runner, stream=not args.json)
            emit(args, {"stage": "hub", "done": done}, "hub: " + ", ".join(done))
            return 0
        # plan mod-repos 4.3: the submodule mods' setup docs are inside them, so the chosen ones are checked out first
        subs: dict[str, list[Any]] = {"done": [], "failed": []}
        if targets[:1] != ["host"]:
            subs = repos_mod.checkout(root, targets)
            for sid in subs["done"]:
                print(f"checked out services/{sid} (its own repository)", file=sys.stderr)
        _last["checkouts"] = subs
        offered, problems = choices(root)
        if targets[:1] == ["host"]:
            found = host_mod.checks(probe, root)
            emit(args, {"stage": "host", "host": [c.dump() for c in found]}, host_mod.text(found) + "\n(GPU checks matter only for mods that use the GPU)")
            return 1 if host_mod.blocking(found, gpu=False) else 0
        if not targets:
            if not run_mod.interactive(args):
                emit(args, {"stage": "choose", "choices": [{"id": e.id, "mod": e.mod, "summary": e.setup.summary, "gpu": e.setup.gpu, "disk_gb": e.setup.disk_gb, "after": e.setup.after} for e in offered.values()], "problems": problems,
                            "unavailable": subs["failed"]},
                     "\n".join(f"  {e.id:24} {e.setup.summary}" for e in offered.values()))
                return 0
            ids = sorted(offered, key=lambda i: (offered[i].mod, i))
            for n, i in enumerate(ids, 1):
                e = offered[i]
                print(f"  {n:2}. {i:24} {'GPU ' if e.setup.gpu else '    '}{(e.setup.disk_gb or 0):5.1f} GB  {e.setup.summary}")
            pick = input("Which? numbers or ids, comma-separated: ")
            targets = [ids[int(x) - 1] if x.strip().isdigit() else x.strip() for x in pick.split(",") if x.strip()]
        lost = [t for t in targets if any(repos_mod.wanted([t], f["mod"]) and t not in offered for f in subs["failed"])]
        if lost:
            targets = [t for t in targets if t not in lost]
            if not targets:
                raise Stop("unavailable", unavailable=subs["failed"])
        early = run_mod.read_answers(args)
        if run_mod.interactive(args):           # capability-enablement 6.2: a choice that changes what is set up comes first
            for t in targets:
                for e in [x for x in offered.values() if x.mod == t or x.id == t]:
                    for ch in e.setup.choose:
                        qid = f"{e.id}/choose:{ch.id}"
                        if qid not in early.values:
                            print(f"\n{ch.text}")
                            for i, o in enumerate(ch.options, 1):
                                print(f"  {i}. {o.label}" + (" (default)" if o.value == ch.default else ""))
                            pick = input("Number, or Enter for the default: ").strip()
                            early.values[qid] = ch.options[int(pick) - 1].value if pick.isdigit() and 0 < int(pick) <= len(ch.options) else ch.default
            args.set = [*(getattr(args, "set", None) or []), *[f"{k}={v}" for k, v in early.values.items() if "/choose:" in k]]
        envs = resolve(targets, offered, root, early.values)
        machine = probe.machine()
        _last.clear()
        _last.update(machine=machine.to_dict(), targets=targets)
        resolved = envs
        envs, unavailable = variant_mod.choose(envs, machine, variant_mod.overrides(getattr(args, "accel", None)))
        gone = run_mod.dependents(resolved, {u["setup"] for u in unavailable}) - {u["setup"] for u in unavailable}
        unavailable += [{"setup": i, "mod": next(e.mod for e in resolved if e.id == i), "why": "it needs a setup this machine can't run"} for i in sorted(gone)]
        envs = [e for e in envs if e.id not in gone]
        unavailable += subs["failed"]
        if not envs:
            raise Stop("unavailable", unavailable=unavailable, hardware=machine.to_dict()["accels"])
        expanded = {t: [e.id for e in envs if e.mod == t] for t in targets if len([e for e in envs if e.mod == t]) > 1}   # a mod id means all its setups
        env_gb, req_gb, _ = sizes(envs)
        found = host_mod.checks(probe, root, {n for e in envs for n in e.setup.needs}, env_gb + req_gb)
        p = plan(envs, found, run_mod.hub_needs(code, runner), expanded)
        p["variants"] = [variant_mod.describe(e, machine) for e in envs]
        p["unavailable"] = unavailable
        p["checkouts"] = subs
        p["smokes"] = [{"setup": e.id, "run": e.setup.smoke} for e in envs if e.setup.smoke] if getattr(args, "smoke", False) else []
        applies(p, envs, root, runner)          # capability-enablement 5.3: steps whose ask_if says they don't apply here
        _last["plan"] = p
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
                 "unknown": f"stopped: no setup doc {s.data.get('id')!r}; choose from: {', '.join(s.data.get('choices', []))}",
                 "unavailable": "stopped: nothing chosen runs on this machine:\n" + "\n".join(f"  {u['setup']}: {u['why']}" for u in s.data.get("unavailable", []))}
        emit(args, data, lines.get(s.reason, f"stopped: {s.reason} {json.dumps({k: v for k, v in s.data.items() if k != 'report'})[:600]}"))
        return 2 if s.reason in ("question", "interactive") else 1


def applies(p: dict[str, Any], envs: list[Any], root: Path, runner: Any) -> None:
    """Run each step's `ask_if` (capability-enablement 5.3): a step it says doesn't apply here loses its question and is
    marked `skip` with the command's output as the reason (the run reports it as skipped)."""
    by_id = {e.id: e for e in envs}
    drop: set[str] = set()
    for s in p["steps"]:
        e = by_id.get(s["setup"])
        step = e.setup.steps[int(s["id"].rsplit("/", 1)[1]) - 1] if e else None
        if not step or not step.ask_if:
            continue
        rc, out = runner.run(step.ask_if, root / "services" / e.mod, stream=False)
        if rc != 0:
            s["skip"] = (out or "").strip().splitlines()[-1][:300] if (out or "").strip() else "not needed here"
            s["ask"] = None
            drop.add(s["id"])
    p["questions"] = [q for q in p["questions"] if q["id"] not in drop]


def add_parser(sub: Any) -> None:
    p = sub.add_parser("setup", help="set up GAIFA: the hub, the host checks, the mods you choose, their models, their checks (docs/setup/)",
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
    p.add_argument("--accel", action="append", metavar="ID=ACCEL", help="the variant for a setup or mod: rocm, cuda, xpu, mps, vulkan or cpu (repeatable; default: the best this machine has)")
    p.add_argument("--prompt", action="store_true", help="print a prompt to paste into your own coding agent (Claude Code, Codex) so it sets these mods up for you")
    p.add_argument("--smoke", action="store_true", help="after the checks, run each setup's smoke: real work (an image, a sentence spoken) that proves the GPU path")
