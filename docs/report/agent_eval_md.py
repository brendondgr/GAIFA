"""Fills docs/agent-eval.md's results from docs/report/data/ (run after the evals; idempotent)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "docs" / "report" / "data"


def s(f):
    p = D / f
    return json.loads(p.read_text()) if p.exists() else None


rows = []
for f, label in [("eval-skynet-deferred.json", "Gemma 4 31B, first run (v1)"), ("eval-skynet-v2.json", "31B, v2 (leaked-reasoning fix)"),
                 ("eval-skynet-final.json", "31B, v3 (+2 tasks re-run)"), ("eval-skynet-v4.json", "31B, final code"),
                 ("eval-skynet-after.json", "31B, 5 weakest tasks re-checked"), ("eval-skynet-all-tools.json", "31B, all tools loaded"),
                 ("eval-26b-r1.json", "Gemma 4 26B, 1 run (local)"), ("eval-26b-v3.json", "26B, 3 runs (local)"),
                 ("eval-26b-fixcheck.json", "26B, the 4 tasks fixed after its eval, re-checked"),
                 ("eval-skynet-fixcheck.json", "31B, the same 4 tasks on the fixed code")]:
    d = s(f)
    if d:
        x = d["summary"]
        rows.append(f"| {label} | {x['tasks']} × {d['runs']} | {100 * x['pass_1_rate']:.1f}% | {x['pass_k']}/{x['tasks']} "
                    f"({100 * x['pass_k_rate']:.0f}%) | {x['mean_seconds']:.0f} s |")
table = "| Run | Tasks × runs | pass@1 | pass^k | Mean time |\n|---|---|---|---|---|\n" + "\n".join(rows)
final: dict = {}
order = [("live-skynet.json", "31B"), ("live-skynet-2.json", "31B, re-run after fixes"), ("live-buttons.json", "31B, re-run after fixes"),
         ("live-fork.json", "31B, re-run after fixes"), ("live-video.json", "31B, Video work session"), ("live-26b.json", "26B")]
for f, m in order:
    for r in (s(f) or {}).get("rows", []):
        key = (r["task"], "26B" if m == "26B" else "31B")
        final[key] = (m, r)
live = [f"| {t} | {m} | {'pass' if r['ok'] else 'fail'} | {r['seconds']:.0f} s | {', '.join(r['tools'])[:90]} |" for (t, _), (m, r) in final.items()]
ltable = "| Live case | Model (latest run) | Result | Time | Tools |\n|---|---|---|---|---|\n" + "\n".join(live)
other = """**Other live checks:**
- **Pending card and question survive restarts.** A pending parameter card and a pending question both survived `aihub restart` plus `aihub restart agent`, then finished (`evals/restart_live.py`): pass.
- **Context meter.** It was within 1.1% of the 31B's own prompt-token count (`evals/meter_check.py`).
- **Compaction.** In a thread capped at 6k tokens, 5 clears and a model-written summary still answered a question about the first turn (`evals/compact_live.py`): pass.
- **Sessions.** "LLM work", "3D work" and "Video work" were saved on the real mods, and switching between them peaked at 46 GB of a 118 GB limit; the 26B relaunched with its settings (`evals/sessions_live.py`).
- **MCP.** Claude Code listed 41 AIHub tools and called two. Its `tts_speak` call became a denied approval, and nothing ran."""
p = ROOT / "docs" / "agent-eval.md"
md = p.read_text()
block = "<!-- RESULTS -->\n" + table + "\n\n" + ltable + "\n\n(Each live case shows its latest run; the report lists every earlier failure and its cause.)\n\n" + other + "\n<!-- /RESULTS -->"
md = re.sub(r"<!-- RESULTS -->.*?<!-- /RESULTS -->", block, md, flags=re.S) if "<!-- /RESULTS -->" in md else md.replace("<!-- RESULTS -->", block)
p.write_text(md)
print("ok")
