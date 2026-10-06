"""The 11.12 transfer test: score imported held-out packs against ComfyUI's own conversion and the
hand-written expectations. Run from services/comfy:

    .venv/bin/python tests/transfer.py <truth dir> [ids…]

<truth dir> holds <id>.truth files: {"output": <app.graphToPrompt().output>} captured in the browser.
Prints one line per workflow and a markdown table for docs/comfy-transfer-report.md.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# COMFY_CODE=<folder holding comfy/>: score another version of the code (the frozen one, for "before")
sys.path[:0] = [os.environ.get("COMFY_CODE") or str(HERE.parent), str(HERE)]

from comfy.check import FILE_EXTS  # noqa: E402
from comfy.config import Settings  # noqa: E402
from comfy.library import Library  # noqa: E402
from comfy.nodes import NodeCatalog  # noqa: E402
from comfy.packs import Packs  # noqa: E402
from comfy.tasks import Tasks  # noqa: E402
from scoring import load_expected, score  # noqa: E402

IDS = ["qwen21-t2i", "qwen21-edit-multi", "qwen21-remove-bg", "klein9b-t2i", "klein9b-edit-base", "klein9b-edit-distilled",
       "scail2-basic", "scail2-gguf", "zimg-v7-basic", "zimage-aio", "lonecat-krea2-pro", "krea2-simple", "krea2-dualmode"]
TIER = {i: (1 if i.startswith("qwen21") else 2 if i.startswith("klein") else 3 if i.startswith(("scail2", "zimg")) else 4) for i in IDS}
IGNORED = {"filename_prefix"}
# Kept here, not imported, so the score doesn't depend on the code it judges.
MUTED, BYPASS = 2, 4
EDITOR_ONLY = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "SetNode", "GetNode", "Fast Groups Bypasser (rgthree)",
               "Fast Groups Muter (rgthree)", "Fast Bypasser (rgthree)", "Fast Muter (rgthree)", "Mute / Bypass Repeater (rgthree)",
               "Mute / Bypass Relay (rgthree)", "Node Collector (rgthree)", "Bookmark (rgthree)", "Label (rgthree)", "Reroute (rgthree)"}
BROADCAST = ("Anything Everywhere", "Prompts Everywhere", "Seed Everywhere")


def conversion(conv, truth: dict | None) -> tuple[str, list[str]]:
    if conv is None:
        return "failed", []
    if truth is None:
        return "no ground truth", []
    diffs = []
    for k in truth.keys() - conv.graph.keys():
        diffs.append(f"missing node {k} ({truth[k].get('class_type')})")
    for k in conv.graph.keys() - truth.keys():
        diffs.append(f"extra node {k} ({conv.graph[k]['class_type']})")
    for k in truth.keys() & conv.graph.keys():
        want, got = truth[k].get("inputs") or {}, conv.graph[k]["inputs"]
        typed = bool(truth[k].get("class_type"))      # ComfyUI can't name a missing node's widgets either
        for name in (want.keys() | got.keys()) - IGNORED:
            a, b = got.get(name), want.get(name)
            if not typed and not (isinstance(a, list) or isinstance(b, list)):
                continue
            if a != b and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b)):
                diffs.append(f"{k} {truth[k].get('class_type')}.{name}: got {str(a)[:40]!r}, want {str(b)[:40]!r}")
    return ("exact" if not diffs else f"{len(diffs)} differences"), diffs


def independent_missing(editor: dict, catalog: NodeCatalog, conv) -> tuple[set[str], set[str]]:
    """Missing node types and model files, worked out separately from check(): node types used by
    live, connected nodes that the catalog lacks; loader file values not in any of its lists."""
    nodes = list(editor.get("nodes") or [])
    for sg in (editor.get("definitions") or {}).get("subgraphs") or []:
        nodes += sg.get("nodes") or []
    defs = {d["id"] for d in (editor.get("definitions") or {}).get("subgraphs") or []}
    types = set()
    for n in nodes:
        t = n.get("type")
        if n.get("mode") in (MUTED, BYPASS) or t in defs or t in EDITOR_ONLY or catalog.has(t) or str(t).startswith(BROADCAST):
            continue
        linked = any(i.get("link") is not None for i in n.get("inputs") or []) or any(o.get("links") for o in n.get("outputs") or [])
        if linked:
            types.add(t)
    files = set()
    if conv is not None:
        lists = {v for n in catalog.info.values() for sec in ("required", "optional")
                 for spec in ((n.get("input") or {}).get(sec) or {}).values()
                 for v in (spec[0] if spec and isinstance(spec[0], list) else (spec[1].get("options") or []) if len(spec) > 1 and isinstance(spec[1], dict) else [])
                 if isinstance(v, str)}
        for n in conv.graph.values():
            for v in n["inputs"].values():
                if isinstance(v, str) and v.lower().endswith(FILE_EXTS) and v not in lists:
                    files.add(v)
    return types, files


def main(truth_dir: Path, ids: list[str]) -> None:
    s = Settings.from_env()
    lib = Library(Packs(s.workflows, s.comfy_view), NodeCatalog.load(s.data / "object_info.json"), Tasks.load(), "", s.models)
    lib.packs.scan()
    rows = []
    for pid in ids:
        p = lib.packs.get(pid)
        if p is None:
            rows.append((pid, "not imported"))
            continue
        tf = truth_dir / f"{pid}.truth"
        truth = json.loads(tf.read_text())["output"] if tf.exists() else None
        conv, issues = lib.analysed(p)
        conv_state, diffs = conversion(conv, truth)
        editor = p.editor() or {}
        miss_types, miss_files = independent_missing(editor, lib.catalog, conv)
        got_types = {(i.data or {}).get("type") for i in issues if i.code == "missing_node"}
        got_files = {(i.data or {}).get("file") for i in issues if i.code == "missing_model"}
        sug, _ = lib.suggest(p) if conv is not None else (None, "")
        exp_file = HERE / "fixtures" / "holdout-expected" / f"{pid}.toml"
        sc = score(sug.manifest, load_expected(exp_file)) if sug and exp_file.exists() else None
        print(f"\n===== {pid} (tier {TIER.get(pid, '?')})")
        print(f"  convert: {conv_state}")
        for d in diffs[:12]:
            print(f"    {d}")
        print(f"  missing nodes: reported {sorted(got_types)}; independent {sorted(miss_types)}"
              f"{'  MATCH' if got_types == miss_types else '  DIFFER'}")
        print(f"  missing models: reported {sorted(got_files)}; independent {sorted(miss_files)}"
              f"{'  MATCH' if got_files == miss_files else '  DIFFER'}")
        for i in issues:
            if i.code not in ("missing_node", "missing_model"):
                print(f"  issue {i.level} {i.code}: {i.detail}")
        if sug:
            print(f"  task: {sug.manifest['task']}   outputs: {[o['node'] for o in sug.manifest['outputs'].values()]}")
            print(f"  inputs: {', '.join(f'{k}={v['node']}.{v['field']}' for k, v in sug.manifest['inputs'].items())}")
        if sc:
            print(f"  score: right {sc['right']} wrong {sc['wrong']} missed {sc['missed']} extra {sc['extra']} "
                  f"task {'ok' if sc['task_ok'] else 'WRONG'} outputs {'ok' if sc['outputs_ok'] else 'WRONG'}")
        rows.append((pid, conv_state, got_types == miss_types and got_files == miss_files, sc, len(issues)))
    print("\n| Workflow | Tier | Converts | Missing pieces right | Inputs right / wrong / missed / extra | Task | Outputs |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        if len(r) == 2:
            print(f"| {r[0]} | | {r[1]} | | | | |")
            continue
        pid, cs, ok, sc, _ = r
        inp = f"{len(sc['right'])} / {len(sc['wrong'])} / {len(sc['missed'])} / {len(sc['extra'])}" if sc else "—"
        print(f"| {pid} | {TIER[pid]} | {cs} | {'yes' if ok else 'no'} | {inp} | {('ok' if sc['task_ok'] else 'wrong') if sc else '—'} | "
              f"{('ok' if sc['outputs_ok'] else 'wrong') if sc else '—'} |")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:] or IDS)
