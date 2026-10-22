"""The field report as markdown (plan 40.2), written for whoever fixes AIHub: each issue says where it comes
from, what ran, what it printed and what it most likely means. Standard library only. `render(data)` takes
`cli_report.gather`'s dict; redaction happens on the whole text afterwards."""

from __future__ import annotations

import json
from typing import Any

GIB = 2**30
FENCE = "```"


def _code(lines: list[str] | str, lang: str = "") -> list[str]:
    body = lines if isinstance(lines, list) else str(lines).splitlines()
    body = [line.replace(FENCE, "``​`") for line in body]
    return [FENCE + lang, *body, FENCE]


def _machine(d: dict[str, Any]) -> list[str]:
    if "error" in d:
        return [d["error"]]
    m = d["machine"]
    os_ = (m.get("distro") or {}).get("name") or m["os"]
    out = [f"- **System:** {os_}{' (WSL2)' if m.get('wsl') else ''}, kernel `{m.get('kernel')}`, {m.get('arch')}, "
           f"{m.get('cpus')} CPUs, {m.get('ram_bytes', 0) / GIB:.1f} GiB RAM" + (f", inside {m['container']}" if m.get("container") else "")
           + (f", package manager `{m['pkg']}`" if m.get("pkg") else ""),
           f"- **CPU:** {m.get('cpu') or '?'}"]
    for g in m.get("gpus", []):
        mem = {"unified": "shares the system's memory", "dedicated": f"{g.get('vram_bytes', 0) / GIB:.1f} GiB VRAM"}.get(g.get("memory"), "memory unknown")
        rt = ", ".join(f"{k} {v}" if v != "yes" else k for k, v in (g.get("runtimes") or {}).items()) or "none"
        out.append(f"- **GPU {g.get('index')}:** {g.get('name')} (`{g.get('arch') or '?'}`), {mem}, driver `{g.get('driver') or '?'}`, "
                   f"runtimes: {rt}; runs: {', '.join(g.get('accels') or []) or 'nothing'}")
        out += [f"  - problem: {p}" for p in g.get("problems") or []]
    if not m.get("gpus"):
        out.append("- **GPU:** none found")
    out.append(f"- **Accels AIHub can use:** `{', '.join(m.get('accels') or [])}`")
    out.append("- **Tools:** " + ", ".join(f"{k} `{v}`" for k, v in d.get("tools", {}).items()))
    if d.get("nvidia_smi"):
        out += ["", "`nvidia-smi`:", *_code(d["nvidia_smi"])]
    out.append(f"- **Hardware recording:** `{d.get('snapshot')}` (next to this file): `aihub hardware --from <it>` replays this "
               "machine's detection; to make it a test fixture, copy it into `utils/tests/hardware/fixtures/`.")
    return out


def _issue(i: dict[str, Any]) -> list[str]:
    out = [f"### {i['id']} [{i['severity']}]: {i['title']}", ""]
    if i["kind"] == "note":
        out += [f"Recorded by the agent: {i.get('text')}", ""]
    rows = [("Setup", i.get("setup")), ("Step", i.get("step")), ("Source", i.get("source")), ("Folder", i.get("cwd")),
            ("Exit code", i.get("exit")), ("Full log", i.get("log") or i.get("output_file"))]
    out += [f"- **{k}:** `{v}`" for k, v in rows if v not in (None, "", {})]
    if i.get("run"):
        out += ["- **Command:**", *_code(i["run"], "bash")]
    if i.get("env"):
        out += ["- **Environment (the variant's):** " + ", ".join(f"`{k}={v}`" for k, v in i["env"].items())]
    if i.get("detail"):
        out += ["- **Details:**", *_code(i["detail"], "json")]
    if i.get("output"):
        out += [f"- **Output** (last {len(i['output'])} lines):", *_code(i["output"])]
    if i.get("hints"):
        out.append("- **Likely cause:**")
        out += [f"  - {h['cause']}. Look at: {h['fix']}" for h in i["hints"]]
    else:
        out.append("- **Likely cause:** no known pattern matched; read the output above.")
    if i.get("tried"):
        out.append(f"- **Tried:** {i['tried']}")
    if i.get("files"):
        out.append("- **Files to look at:** " + ", ".join(f"`{f}`" for f in i["files"]))
    return out + [""]


def render(data: dict[str, Any]) -> str:
    issues = data.get("issues") or []
    last = data.get("last_run") or {}
    result = last.get("result") or {}
    plan = last.get("plan") or {}
    counts = {s: sum(1 for i in issues if i["severity"] == s) for s in ("blocker", "major", "minor")}
    m = (data.get("machine") or {}).get("machine") or {}
    gpu_names = ", ".join(g.get("name", "?") for g in m.get("gpus", [])) or "no GPU"
    out = [f"# AIHub field report: {data.get('host')}", "",
           f"Written {data.get('written')} by `aihub report` (plan 40.2). Feed this file to Claude in the AIHub repo: every issue "
           "names the setup doc line, the command and the files to change.", "",
           "## Summary", "",
           f"- **Machine:** {(m.get('distro') or {}).get('name') or m.get('os')}{' (WSL2)' if m.get('wsl') else ''}, {gpu_names}; accels `{', '.join(m.get('accels') or [])}`",
           f"- **AIHub:** `{(data.get('aihub') or {}).get('describe') or 'not a git checkout'}`" + (f", **{data['aihub']['changed_count']} local change(s)**" if (data.get("aihub") or {}).get("changed_count") else ", no local changes"),
           f"- **Issues:** {len(issues)} ({counts['blocker']} blocker, {counts['major']} major, {counts['minor']} minor)"]
    if result:
        done = result.get("done") or (result.get("report") or {}).get("done") or []
        out.append(f"- **Last setup run:** `aihub {' '.join(last.get('argv') or [])}` → {result.get('stage')}"
                   + (f" ({result.get('reason')})" if result.get("reason") else "") + f", {len(done)} step(s) done")
    else:
        out.append("- **Last setup run:** none recorded (data/state/setup/last-run.json is missing)")
    out += [f"  - {i['id']} [{i['severity']}] {i['title']}" for i in issues]
    out += ["", "## Machine", "", *_machine(data.get("machine") or {}), ""]
    g = data.get("aihub") or {}
    out += ["## AIHub", "", (f"- **Commit:** `{g.get('commit')}` on `{g.get('branch')}`: {g.get('describe')}" if g.get("commit") else "- **Commit:** none (not a git checkout)")]
    if g.get("changed"):
        out += [f"- **Local changes** ({g['changed_count']}; the agent's workarounds, if any):", *_code(g["changed"])]
        if g.get("diff"):
            out += [f"`git diff` ({g['diff_lines']} lines{', first 400' if g['diff_lines'] > 400 else ''}):", *_code(g["diff"], "diff")]
    out.append("")
    bad = [c for c in data.get("host_checks") or [] if not c.get("ok")]
    out += ["## Host checks", "", f"{len(data.get('host_checks') or []) - len(bad)} ok" + (", these failed:" if bad else ".")]
    out += [f"- `{c['id']}`: {c.get('detail')}" + (f". Fix{' (root)' if c.get('needs_root') else ''}: `{c['fix']}`" if c.get("fix") else "") for c in bad]
    out.append("")
    out += ["## The setup run", ""]
    if not last:
        out.append("No run recorded: run `aihub setup` (data/state/setup/last-run.json is written by each run).")
    if plan:
        out.append(f"Setups: {', '.join(plan.get('setups') or [])}.")
        out += [f"- `{v['setup']}`: {v['label']}" + (" (untested on this kind of machine)" if v.get("untested") else "") + (f": {v['note']}" if v.get("note") else "")
                for v in plan.get("variants") or []]
        out += [f"- `{u['setup']}`: not available: {u['why']}" for u in plan.get("unavailable") or []]
    rep = result.get("report") or result
    for key, label in (("skipped", "Skipped"), ("next", "Left to do")):
        if rep.get(key):
            out += [f"{label}:", *[f"- {x}" for x in rep[key]]]
    for key, label in (("checks", "Checks"), ("smokes", "Smokes")):
        if rep.get(key):
            out += [f"{label}:", *[f"- `{c['setup']}`: {'ok' if c['ok'] else 'FAILED'} (`{c.get('log', '')}`)" for c in rep[key]]]
    out.append("")
    out += ["## Issues", ""]
    for i in issues:
        out += _issue(i)
    if not issues:
        out += ["None recorded.", ""]
    hub = data.get("hub") or {}
    out += ["## Mods", ""]
    if hub.get("error"):
        out += [hub["error"], ""]
    for md in data.get("mods") or []:
        line = f"- `{md['id']}`: {md['state']}, {md['load']}" + (f", runs on {md['accel']}" if md.get("accel") else "")
        line += f"; unavailable: {md['unavailable']}" if md.get("unavailable") else ""
        line += f"; last error: {md['last_error']}" if md.get("last_error") else ""
        line += f"; manifest: {'; '.join(md['manifest_errors'])}" if md.get("manifest_errors") else ""
        out.append(line)
        if md.get("log"):
            out += [f"  `data/logs/{md['id']}.log` (last {len(md['log'])} lines):", *_code(md["log"])]
    out.append("")
    doc = hub.get("doctor") or {}
    if doc:
        worse = [c for c in doc.get("checks", []) if c.get("level") in ("warn", "fail")]
        out += ["## Doctor", "", f"{doc.get('counts')}"]
        out += [f"- [{c['level']}] {c['area']}: {c['title']}" + (f": {c.get('detail')}" if c.get("detail") else "") + (f" (fix: {c['fix']})" if c.get("fix") else "") for c in worse]
        out.append("")
    if data.get("setup_logs"):
        out += ["## Setup logs", "", *[f"- `{x['file']}` ({x['bytes']} bytes): {x['end']}" for x in data["setup_logs"]], ""]
    targets = " ".join((last.get("targets") or [])) or "<mods>"
    accels = " ".join(f"--accel {v['setup']}={v['accel']}" for v in plan.get("variants") or [])
    out += ["## For the fixer", "",
            f"- Reproduce the plan here: `AIHUB_HARDWARE_FIXTURE=<the hardware recording> bin/aihub setup --plan --json {targets}`",
            f"- Rerun on that machine: `{f'bin/aihub setup {targets} {accels}'.rstrip()}` (it resumes after the last step that passed)",
            "- Each issue's **Source** is the setup doc line the command comes from; **Files to look at** are the scripts it runs.",
            "- The whole data behind this file is in the `.json` next to it."]
    return "\n".join(out) + "\n"


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, default=str)
