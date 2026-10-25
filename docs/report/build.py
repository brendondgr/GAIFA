"""Builds the overnight report's generated parts from the test data (`uv run python docs/report/build.py`).

Reads `docs/report/data/*.json` (eval runs, live runs, test counts) and writes LaTeX snippets to
`docs/report/gen/`, plus thumbnails of the live outputs to `docs/report/img/live/` (fetched from
the hub). Then: `lualatex report.tex` (twice) in `docs/report/`.
"""

from __future__ import annotations

import io
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA, GEN, LIVEIMG = HERE / "data", HERE / "gen", HERE / "img" / "live"
HUB = "http://127.0.0.1:7000"
GROUPS = ["single", "chain", "must-ask", "no-ask", "safety", "context"]
GROUP_NAMES = {"single": "Single generations", "chain": "Chains", "must-ask": "Must ask", "no-ask": "Must not ask",
               "safety": "Refusals and safety", "context": "Context"}
GROUP_SHORT = {"single": "Single", "chain": "Chains", "must-ask": "MustAsk", "no-ask": "NoAsk", "safety": "Safety", "context": "Context"}


def tex(s: object) -> str:
    s = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"), ("→", r"$\rightarrow$"),
                 ("×", r"$\times$"), ("…", r"\ldots{}"), ("—", "---"), ("–", "--"), ("’", "'"), ("“", "``"), ("”", "''")):
        s = s.replace(a, b)
    return re.sub(r"[^\x00-\x7F]", "", s) if False else s


def load(name: str) -> dict | None:
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def short_tool(t: str) -> str:
    return t.replace("comfy_", "").replace("gen3d_", "").replace("tts_", "").replace("hub_", "")


# ---- eval ------------------------------------------------------------------------------------

def eval_runs() -> list[tuple[str, dict]]:
    """(label, data) for each eval file, in a fixed order."""
    order = [("eval-skynet-deferred.json", "31B · v1"), ("eval-skynet-v2.json", "31B · v2"),
             ("eval-skynet-v3.json", "31B · v3 as run"), ("eval-skynet-final.json", "31B · v3 + 2 re-run"),
             ("eval-skynet-v4.json", "31B · final"), ("eval-skynet-after.json", "31B · 5 weakest, re-checked"),
             ("eval-skynet-all-tools.json", "31B · all tools loaded"),
             ("eval-26b-r1.json", "26B · 1 run"), ("eval-26b-v3.json", "26B · final"),
             ("eval-26b-fixcheck.json", "26B · 4 fixed tasks"), ("eval-skynet-fixcheck.json", "31B · 4 fixed tasks")]
    return [(label, d) for f, label in order if (d := load(f))]


def by_group(d: dict) -> dict[str, float]:
    out = {}
    for g in GROUPS:
        rows = [r for r in d["rows"] if r["group"] == g]
        out[g] = round(100 * sum(r["ok"] for r in rows) / len(rows), 1) if rows else 0.0
    return out


def write_eval() -> None:
    runs = eval_runs()
    lines = [r"\begin{tabular}{@{}lrrrrr@{}}", r"\toprule",
             r"Run & Tasks & pass@1 & pass\textasciicircum{}3 & Mean time & Infra.\ errors \\", r"\midrule"]
    for label, d in runs:
        s = d["summary"]
        infra = sum(1 for r in d["rows"] for c in r["checks"] if c["check"] == "ran to the end" and not c["ok"])
        lines.append(f"{tex(label)} & {s['tasks']} & {100 * s['pass_1_rate']:.1f}\\% & {s['pass_k']}/{s['tasks']} "
                     f"({100 * s['pass_k_rate']:.0f}\\%) & {s['mean_seconds']:.0f} s & {infra} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (GEN / "eval_summary.tex").write_text("\n".join(lines) + "\n")
    # pass rate by group (pgfplots coordinates)
    coords = []
    for label, d in [(l, d) for l, d in runs if l in ("31B · v1", "31B · final", "31B · all tools loaded", "26B · final", "26B · 1 run")]:
        g = by_group(d)
        coords.append(r"\addplot coordinates {" + " ".join(f"({GROUP_SHORT[k]},{v})" for k, v in g.items()) + "};")
        coords.append(r"\addlegendentry{" + tex(label) + "}")
    (GEN / "eval_groups.tex").write_text("\n".join(coords) + "\n")
    # per-task table for the final runs
    have = dict(runs)
    best31 = "31B · final" if "31B · final" in have else "31B · v3 + 2 re-run"
    best26 = "26B · final" if "26B · final" in have else "26B · 1 run"
    finals = [(l, d) for l, d in runs if l in ("31B · v1", best31, best26)]
    head = " & ".join(tex(l) for l, _ in finals)
    rows = [r"\begin{longtable}{@{}p{2.9cm}p{7.6cm}" + "c" * len(finals) + "@{}}", r"\toprule",
            f"Task & Prompt (turns) & {head} \\\\", r"\midrule", r"\endhead"]
    tasks = {}
    for _, d in finals:
        for r in d["rows"]:
            tasks.setdefault(r["task"], r)
    for g in GROUPS:
        rows.append(r"\multicolumn{" + str(2 + len(finals)) + r"}{@{}l}{\textbf{" + GROUP_NAMES[g] + r"}} \\")
        for tid, r in tasks.items():
            if r["group"] != g:
                continue
            cells = []
            for _, d in finals:
                rs = [x for x in d["rows"] if x["task"] == tid]
                n, k = sum(x["ok"] for x in rs), len(rs)
                mark = r"\textcolor{okgreen}{" if n == k else (r"\textcolor{warnamber}{" if n else r"\textcolor{badred}{")
                cells.append(f"{mark}{n}/{k}}}")
            prompt = r" \newline $\rightarrow$ ".join(r"\emph{" + tex(t) + "}" for t in r["turns"])
            rows.append(f"\\texttt{{{tex(tid)}}} & {prompt} & " + " & ".join(cells) + r" \\")
    rows += [r"\bottomrule", r"\end{longtable}"]
    (GEN / "eval_tasks.tex").write_text("\n".join(rows) + "\n")
    # failures of the final runs, grouped by check
    fails: dict[str, list[str]] = {}
    for label, d in [(l, d) for l, d in finals if l != "31B · v1"]:  # the final runs' failures
        for r in d["rows"]:
            for c in r["checks"]:
                if not c["ok"]:
                    fails.setdefault(f"{r['task']}: {c['check']}", []).append(f"{label} run {r['run']}: {c['why'][:110]}")
    out = [r"\begin{itemize}[leftmargin=*,itemsep=2pt]"]
    for k, v in sorted(fails.items()):
        out.append(r"\item \texttt{" + tex(k.split(':')[0]) + "}: " + tex(k.split(': ', 1)[1]) + r" \newline {\footnotesize\color{muted} " +
                   tex("; ".join(v[:3])) + "}")
    out.append(r"\end{itemize}")
    (GEN / "eval_failures.tex").write_text("\n".join(out) + "\n" if fails else "None.\n")


# ---- live ------------------------------------------------------------------------------------

def fetch(path: str) -> bytes | None:
    try:
        with urllib.request.urlopen(HUB + path, timeout=30) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def thumb(oid: str, kind: str) -> str | None:
    LIVEIMG.mkdir(parents=True, exist_ok=True)
    dst = LIVEIMG / f"{oid}.jpg"
    if dst.exists():
        return dst.name
    data = fetch(f"/api/outputs/{oid}/preview") or (fetch(f"/api/outputs/{oid}/file") if kind == "image" else None)
    if not data:
        return None
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((900, 900))
        im.save(dst, "JPEG", quality=85)
        return dst.name
    except Exception:  # noqa: BLE001
        return None


def write_live() -> None:
    blocks = []
    sets = []
    first, again = load("live-skynet.json"), load("live-skynet-2.json")
    for extra in ("live-buttons.json", "live-fork.json"):
        if (btn := load(extra)):
            again = {"rows": [r for r in (again or {}).get("rows", []) if r["task"] not in {b["task"] for b in btn["rows"]}] + btn["rows"]}
    if first:
        rows = list(first["rows"])
        if again:
            by = {r["task"]: r for r in again["rows"]}
            merged = []
            for r in rows:
                if r["task"] in by:
                    n = dict(by[r["task"]])
                    if not r["ok"]:
                        n["earlier"] = "; ".join(c["check"] for c in r["checks"] if not c["ok"])[:160]
                    merged.append(n)
                else:
                    merged.append(r)
            rows = merged
        vid_rows = {r["task"]: r for r in (load("live-video.json") or {}).get("rows", [])}
        for r in rows:
            if not r["ok"] and r["task"] in vid_rows and vid_rows[r["task"]]["ok"]:
                r["after"] = "Run again in the Video work session below, with the local LLM stopped: it passed."
        sets.append((rows, "Gemma 4 31B"))
    if (vid := load("live-video.json")):
        sets.append((vid["rows"], "Gemma 4 31B, in the Video work session"))
    if (d26 := load("live-26b.json")):
        sets.append((d26["rows"], "Gemma 4 26B"))
    for rows, model in sets:
        for r in rows:
            evs = None
            thread = r.get("thread")
            if thread:
                raw = fetch(f"/api/s/agent/v1/threads/{thread}/events")
                evs = json.loads(raw) if raw else None
            outs, pics = [], []
            for e in evs or []:
                if e["type"] == "tool_result":
                    for o in e["payload"].get("outputs") or []:
                        outs.append(f"#{o['n']} {o['kind']}")
                        t = thumb(o["output_id"], o["kind"]) if o["kind"] in ("image", "video", "model3d") else None
                        if t:
                            pics.append((t, f"\\#{o['n']} {o['kind']}"))
            branch = None
            if r.get("fork_thread") and (raw := fetch(f"/api/s/agent/v1/threads/{r['fork_thread']}/events")):
                fev = json.loads(raw)
                seen = {o["output_id"] for e in evs or [] if e["type"] == "tool_result" for o in e["payload"].get("outputs") or []}
                new = [o for e in fev if e["type"] == "tool_result" for o in e["payload"].get("outputs") or [] if o["output_id"] not in seen]
                last = [e["payload"]["text"] for e in fev if e["type"] == "assistant" and e["payload"].get("text")]
                branch = (r.get("fork_turn") or "", last[-1] if last else "")
                for o in new:
                    t = thumb(o["output_id"], o["kind"]) if o["kind"] in ("image", "video", "model3d") else None
                    if t:
                        pics.append((t, f"branch: {o['kind']}"))
            status = r"\textcolor{okgreen}{PASS}" if r["ok"] else r"\textcolor{badred}{FAIL}"
            bad = [c for c in r["checks"] if not c["ok"]]
            body = [r"\begin{livecase}{" + tex(r["task"]) + " · " + model + " · " + status + f" · {r['seconds']:.0f} s" + "}"]
            body.append(r"\textbf{Prompts:} " + r" $\rightarrow$ ".join(r"\emph{``" + tex(t) + "''}" for t in r["turns"] or ["(buttons, no prompt)"]) + r"\par")
            body.append(r"\textbf{Tools:} \texttt{" + tex(" → ".join(short_tool(t) for t in r["tools"])) + r"}\par")
            if outs:
                body.append(r"\textbf{Outputs:} " + tex(", ".join(outs)) + r"\par")
            if r.get("final"):
                body.append(r"\textbf{Final reply:} {\small " + tex(re.sub(r"\*\*|__|`", "", r["final"])[:420]) + r"}\par")
            if branch:
                body.append(r"\textbf{Branch} (forked after the first reply): \emph{``" + tex(branch[0]) + r"''}"
                            + (r" $\rightarrow$ {\small " + tex(re.sub(r"\*\*|__|`", "", branch[1])[:300]) + "}" if branch[1] else "") + r"\par")
            if bad:
                body.append(r"\textbf{Failed checks:} " + tex("; ".join(f"{c['check']} ({c['why'][:80]})" for c in bad)) + r"\par")
            if r.get("after"):
                body.append(r"{\footnotesize\color{muted} " + tex(r["after"]) + r"}\par")
            if r.get("earlier"):
                body.append(r"{\footnotesize\color{muted} Re-run after the night's fixes; the first attempt failed: " + tex(r["earlier"]) + r".}\par")
            if pics:
                body.append(r"\smallskip\noindent")
                for t, cap in pics[:4]:
                    body.append(r"\begin{minipage}[t]{0.23\linewidth}\centering\includegraphics[width=\linewidth,height=3.2cm,keepaspectratio]{img/live/"
                                + t + r"}\\{\scriptsize " + cap + r"}\end{minipage}\hfill")
            body.append(r"\end{livecase}")
            blocks.append("\n".join(body))
    (GEN / "live.tex").write_text("\n\n".join(blocks) + "\n" if blocks else "No live runs recorded.\n")


def write_tests() -> None:
    d = load("test-counts.json") or {}
    lines = [r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule", r"Suite & Passed & Failed & Skipped & Time \\", r"\midrule"]
    tot = [0, 0, 0, 0]
    for s in d.get("suites", []):
        lines.append(f"{tex(s['name'])} & {s['passed']} & {s['failed']} & {s['skipped']} & {s['seconds']} s \\\\")
        tot = [tot[0] + s["passed"], tot[1] + s["failed"], tot[2] + s["skipped"], tot[3] + s["seconds"]]
    lines += [r"\midrule", f"\\textbf{{All}} & \\textbf{{{tot[0]}}} & {tot[1]} & {tot[2]} & {tot[3]} s \\\\", r"\bottomrule", r"\end{tabular}"]
    (GEN / "tests.tex").write_text("\n".join(lines) + "\n")


def write_glance() -> None:
    tests = load("test-counts.json") or {}
    passed = sum(s.get("passed", 0) for s in tests.get("suites", []))
    runs = dict(eval_runs())
    main = runs.get("31B · final") or runs.get("31B · v3 + 2 re-run") or {}
    b26 = runs.get("26B · final") or runs.get("26B · 1 run") or {}
    lt = lp = 0
    first, again, d26 = load("live-skynet.json"), load("live-skynet-2.json"), load("live-26b.json")
    if first:
        final = {r["task"]: r for r in first["rows"]}
        final.update({r["task"]: r for r in (again or {}).get("rows", [])})
        for extra in ("live-buttons.json", "live-fork.json"):
            final.update({r["task"]: r for r in (load(extra) or {}).get("rows", [])})
        lt, lp = len(final), sum(r["ok"] for r in final.values())
    if d26:
        lt, lp = lt + len(d26["rows"]), lp + sum(r["ok"] for r in d26["rows"])
    if (vid := load("live-video.json")):     # a case re-run in the Video work session counts once, by that run
        new = [r for r in vid["rows"] if not (first and r["task"] in final)]
        if first:
            lp += sum(r["ok"] and not final[r["task"]]["ok"] for r in vid["rows"] if r["task"] in final)
        lt, lp = lt + len(new), lp + sum(r["ok"] for r in new)

    def pk(d: dict) -> str:
        s = d.get("summary")
        return f"{100 * s['pass_k_rate']:.0f}\\%" if s else "--"

    def p1(d: dict) -> str:
        s = d.get("summary")
        return f"{100 * s['pass_1_rate']:.0f}\\%" if s else "--"

    cells = [(f"{passed}", "automated tests passing"), (pk(main), "31B eval, pass\\textasciicircum{}3 (gate 80\\%)"),
             (p1(main), "31B eval, single runs"), (pk(b26), "26B eval, pass\\textasciicircum{}3"),
             (f"{lp}/{lt}", "live cases passed (latest run)"), (str((load("summary.json") or {}).get("bugs", "--")), "bugs found and fixed")]
    out = ["\\noindent"]
    for v, l in cells:
        out.append("\\begin{minipage}[t]{0.158\\linewidth}\\kpi{" + v + "}{" + l + "}\\end{minipage}\\hfill")
    (GEN / "glance.tex").write_text("\n".join(out) + "\n")


def write_timeline() -> None:
    """The night's commits, from git."""
    import subprocess

    out = subprocess.run(["git", "log", "--since=2026-10-06 23:00", "--reverse", "--format=%ad\t%s", "--date=format:%H:%M"],
                         cwd=HERE.parents[1], capture_output=True, text=True).stdout.strip().splitlines()
    rows = [r"\begin{longtable}{@{}l>{\raggedright\arraybackslash}p{14.2cm}@{}}", r"\toprule", r"Time & Commit \\", r"\midrule\endhead"]
    for line in out:
        t, subj = line.split("\t", 1)
        subj = subj.removeprefix("GAIFA ")
        head, _, rest = subj.partition(": ")
        rows.append(f"{t} & \\textbf{{{tex(head)}}} {tex(rest[:230])}{'…' if len(rest) > 230 else ''} \\\\")
    rows += [r"\bottomrule", r"\end{longtable}"]
    (GEN / "timeline.tex").write_text("\n".join(rows) + "\n")


def write_b26() -> None:
    d = load("eval-26b-v3.json") or load("eval-26b-r1.json")
    runs = d["runs"] if d else 0
    (GEN / "b26runs.tex").write_text((f"{runs} time(s) per task" if d else "not at all") + "\n")


def write_p1516() -> None:
    """Sessions switched on the real mods (memory sampled each second), the restart test, the meter
    check, logs and the inventory."""
    out: list[str] = []
    switches = sorted(DATA.glob("session-*.json"), key=lambda p: p.stat().st_mtime)
    if switches:
        out.append(r"\subsection*{Switching sessions on the real mods}")
        out.append(r"Each switch ran its plan through the memory manager while memory was sampled every second. "
                   r"The dashed line is the limit (total minus the 12~GB reserve).")
        rows = [r"\par\medskip\noindent\begin{tabular}{@{}lp{8.4cm}rrr@{}}", r"\toprule", r"Switch to & Steps & Time & Peak & Result \\", r"\midrule"]
        plots = []
        tmax = 10
        for n, f in enumerate(switches, 1):
            d = json.loads(f.read_text())
            name = f.stem.removeprefix("session-").split("-", 1)[-1].replace("_", " ")
            steps = ", ".join(f"{st['action'].replace('_', ' ')} {st['target']}" for st in d["plan"]["steps"]) or "nothing to do"
            res = d["result"]
            ok = res.get("ok")
            t = round(d["samples"][-1]["t"] - d["samples"][0]["t"]) if d["samples"] else 0
            rows.append(f"{n}. {tex(name)} & {tex(steps)} & {t} s & {d['peak_gb']:.0f} GB & "
                        + (r"\textcolor{okgreen}{ok}" if ok else r"\textcolor{badred}{problem}") + r" \\")
            t0 = d["samples"][0]["t"] if d["samples"] else 0
            coords = " ".join(f"({x['t'] - t0:.0f},{x['used_gb']})" for x in d["samples"][::2])
            plots.append((f"{n}. {name}", coords, d["limit_gb"]))
            tmax = max(tmax, t)
        rows += [r"\bottomrule", r"\end{tabular}\par"]
        out += rows
        bad = {f.stem.split("-", 2)[1]: e for f in switches for e in [json.loads(f.read_text())] if not e["result"].get("ok")}
        if bad:
            out.append(r"\par{\footnotesize\color{muted} The switches marked \emph{problem} ran before the fix for bug \#25: their only failed step was "
                       r"``load lcpp'' (lcpp has no load operation; its instance had already been launched). Everything else in them worked.}")
        out.append(r"\begin{center}\begin{tikzpicture}\begin{axis}[width=\linewidth,height=5.2cm,xlabel={seconds into the switch},"
                   r"ylabel={memory used (GB)},ymin=0,ymax=135,xmin=0,legend style={font=\scriptsize,draw=none,at={(0.5,-0.32)},anchor=north,legend columns=4},"
                   r"ymajorgrids,grid style={line},axis line style={line},tick style={line},label style={font=\small},tick label style={font=\small}]")
        colors = ["accent", "purple", "teal", "okgreen", "badred", "muted"]
        for i, (name, coords, limit) in enumerate(plots):
            out.append(rf"\addplot[thick,color={colors[i % 6]}] coordinates {{{coords}}};\addlegendentry{{{tex(name)}}}")
        if plots:
            out.append(rf"\addplot[dashed,color=badred,domain=0:{tmax},samples=2] {{{plots[0][2]}}};\addlegendentry{{limit}}")
        out.append(r"\end{axis}\end{tikzpicture}\end{center}")
    r = load("restart-live.json")
    if r:
        st = {k: v for x in r["steps"] for k, v in x.items()}
        out.append(r"\subsection*{A pending card and a pending question survive restarts}")
        out.append(f"Thread A waited on a parameter card and thread B on a question card. Then the hub and the agent were both restarted "
                   f"({r.get('restart_seconds')} s). After the restart: A was \\emph{{{st['after_restart']['a']}}}, B was \\emph{{{st['after_restart']['b']}}}, "
                   f"and the approval was {'still pending at the hub' if st['after_restart']['approval_pending_at_hub'] else 'gone'}. "
                   f"Approving A and answering B then finished both, with outputs {tex(st['finished']['outputs'])}. Result: "
                   + (r"\ok." if r.get("ok") else r"\bad."))
    m = load("meter-skynet.json")
    if m:
        out.append(r"\subsection*{The context meter against the model's own count}")
        out.append(r"Before each turn, the meter's prediction (last usage, minus thinking, plus an estimate of what was added) "
                   r"is compared with the \code{prompt\_tokens} the 31B then reported:")
        out.append(r"\par\medskip\noindent\begin{tabular}{@{}lrrr@{}}\toprule Turn & Predicted & Actual & Error \\ \midrule")
        for x in m["rows"]:
            out.append(f"\\emph{{{tex(x['turn'])}}} & {x['predicted']:,} & {x['actual']:,} & {x['error_pct']}\\% \\\\")
        out.append(r"\bottomrule\end{tabular}\par")
    inv = load("inventory-live.json")
    fresh = load("fresh-inventory.json")
    if inv:
        out.append(r"\subsection*{What's left outside the folder}")
        out.append(r"\code{gaifa doctor --inventory} on this install:")
        out.append(r"\begin{longtable}{@{}>{\raggedright\arraybackslash}p{5.2cm}lp{1.8cm}>{\raggedright\arraybackslash}p{5.6cm}@{}}\toprule "
                   r"Path & Kind & Used by & Why \\ \midrule\endhead")
        for it in sorted(inv["items"], key=lambda i: ({"outside": 0, "runtime": 1}.get(i["kind"], 2), i["used_by"])):
            col = {"outside": "badred", "runtime": "warnamber"}.get(it["kind"], "okgreen")
            out.append(f"\\code{{{tex(it['path'])}}} & \\textcolor{{{col}}}{{{it['kind']}}} & {tex(it['used_by'])} & {tex(it['reason'])} \\\\")
        out.append(r"\bottomrule\end{longtable}")
        if fresh:
            c = fresh["counts"]
            out.append(f"On a fresh clone of the repository (no \\code{{.env}} files, no installs), the same check finds "
                       f"{c['allowlisted']} allowlisted, {c['runtime']} runtime and {c['outside']} outside item(s): the only outside one is "
                       f"this machine's uv-tool install of the lcpp CLI, not something the folder needs.")
    logs = load("logs-live.json")
    if logs:
        out.append(r"\subsection*{Logs in data/logs}")
        out.append("The shippers wrote these files during the night (sizes at the end): "
                   + tex(", ".join(f"{k} {v / 1e6:.1f} MB" for k, v in sorted(logs.items()))) + ".")
    (GEN / "phase15_16.tex").write_text("\n".join(out) + "\n" if out else "Results pending.\n")
    cov = load("phase15_16.json") or {}
    (GEN / "cov_sessions.tex").write_text(cov.get("cov", "\\ok & \\code{test\\_sessions.py} (2 tests); live switches in Section 8") + "\n")


if __name__ == "__main__":
    GEN.mkdir(parents=True, exist_ok=True)
    write_eval()
    write_live()
    write_tests()
    write_glance()
    write_p1516()
    write_b26()
    write_timeline()
    print("wrote", sorted(p.name for p in GEN.iterdir()))
