"""`comfyui workflows …`: workflow packs from the command line (plan 11.5).

list, show, check, new and copy work on the files directly, with ComfyUI's cached node list, so
they work while ComfyUI (and even the adapter) is down. run goes through the adapter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from .config import Settings
from . import importer
from .library import Library
from .nodes import NodeCatalog
from .packs import API, EDITOR, PACK_ID, Packs
from .tasks import Tasks

MARK = {"error": "FAIL", "warning": "warn", "info": "note"}


def _library(s: Settings) -> Library:
    packs = Packs(s.workflows, s.comfy_view)
    packs.scan()
    lib = Library(packs, NodeCatalog.load(s.data / "object_info.json"), Tasks.load(),
                  s.hub_url or os.environ.get("AIHUB_URL", "http://127.0.0.1:7000"), s.models)
    asyncio.run(lib.refresh_models(force=True))
    return lib


def cmd_list(lib: Library, args) -> int:
    rows = [lib.brief(p) for p in lib.packs.all()]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no workflows yet: comfyui workflows new <id> --from <file>")
        return 0
    w = max(12, *(len(r["id"]) for r in rows)) + 1
    print(f"{'ID':{w}} {'STATE':7} {'TASK':18} {'ISSUES':8} NAME")
    for r in sorted(rows, key=lambda r: (r["state"], r["task"], r["id"])):
        iss = f"{r['issues']['errors']}e {r['issues']['warnings']}w" if r["issues"]["errors"] or r["issues"]["warnings"] else "-"
        print(f"{r['id']:{w}} {r['state']:7} {r['task']:18} {iss:8} {r['name']}{'  (saved in ComfyUI)' if r['loose'] else ''}")
    return 0


def _get(lib: Library, wid: str):
    p = lib.packs.get(wid)
    if p is None:
        print(f"no workflow {wid!r} (comfyui workflows list)", file=sys.stderr)
    return p


def cmd_show(lib: Library, args) -> int:
    p = _get(lib, args.id)
    if p is None:
        return 1
    d = lib.detail(p)
    if args.json:
        print(json.dumps(d, indent=2, default=str))
        return 0
    print(f"{d['name']}  ({d['id']}, {d['task']}, {d['state']})")
    if d["description"]:
        print(f"  {d['description']}")
    print(f"  files: {', '.join(k for k, v in d['files'].items() if v)}")
    props = d["schema"]["properties"]
    if props:
        print("\ninputs:")
        req = set(d["schema"].get("required", []))
        for k, v in props.items():
            where = d["inputs"].get(k, {})
            target = f"node {where.get('node') or repr(where.get('title'))}.{where.get('field')}" if where else "derived"
            dflt = f" = {v['default']!r}" if "default" in v else ""
            print(f"  {k:12} {v.get('type', ''):8}{'*' if k in req else ' '} {target:28}{dflt}")
    if d["presets"]:
        print("\npresets: " + ", ".join(d["presets"]))
    print("\nnodes:")
    for n in d["nodes"]:
        flag = "" if n["installed"] else "  [not installed]"
        fields = ", ".join(f"{k}={str(v)[:40]!s}" for k, v in list(n["fields"].items())[:4])
        print(f"  {n['id']:>6} {n['type']:28} {n['title'][:30]:30} {fields}{flag}")
    _print_issues(d["issues_list"])
    return 0


def _print_issues(issues: list[dict]) -> None:
    if not issues:
        print("\nno issues")
        return
    print("\nissues:")
    for i in issues:
        where = f" [node {i['node']}]" if i.get("node") else ""
        print(f"  {MARK[i['level']]}  {i['detail']}{where}")
        if i.get("fix"):
            print(f"        fix: {i['fix']}")


def cmd_check(lib: Library, args) -> int:
    ids = [p.id for p in lib.packs.all()] if args.all else args.ids
    if not ids:
        print("give workflow ids, or --all", file=sys.stderr)
        return 2
    bad = 0
    for wid in ids:
        p = _get(lib, wid)
        if p is None:
            bad += 1
            continue
        _, issues = lib.analysed(p)
        state = lib.state(p, issues)
        errors = [i for i in issues if i.level == "error"]
        bad += bool(errors)
        print(f"{wid}: {state}" + (f", {len(errors)} error(s)" if errors else ""))
        for i in issues:
            if i.level != "info" or args.verbose:
                print(f"  {MARK[i.level]}  {i.detail}" + (f" [node {i.node}]" if i.node else ""))
                if i.fix and i.level == "error":
                    print(f"        fix: {i.fix}")
    return 1 if bad else 0


def cmd_new(lib: Library, args) -> int:
    if not PACK_ID.match(args.id):
        print(f"{args.id!r}: use lowercase letters, digits and -, starting with a letter", file=sys.stderr)
        return 2
    d = lib.packs.root / args.id
    if d.exists():
        print(f"workflows/{args.id} already exists", file=sys.stderr)
        return 1
    src = Path(args.source).expanduser()
    ids = [args.id]
    if lib.packs.get(args.source) and lib.packs.get(args.source).dir is None:
        p = lib.packs.adopt(args.source, args.id)         # a draft saved in ComfyUI
        print(f"made workflows/{p.id}/ from the ComfyUI draft {args.source}")
    else:
        try:
            found = importer.read_all(src.name, src.read_bytes())     # JSON, PNG/WebP/video, or a zip
        except OSError as e:
            print(f"can't read {src}: {e}", file=sys.stderr)
            return 1
        except importer.ImportError_ as e:
            print(e.detail, file=sys.stderr)
            return 1
        ids = [args.id if len(found) == 1 else f"{args.id}-{i + 1}" for i in range(len(found))]
        for wid, f in zip(ids, found, strict=True):
            importer.create(lib.packs, lib.catalog, f, wid, src.name)
            files = [k for k, v in {"editor file": EDITOR, "API graph": API}.items() if (lib.packs.root / wid / v).exists()]
            extra = f", {len(f.assets)} asset file(s)" if f.assets else ""
            print(f"made workflows/{wid}/ ({' + '.join(files)}{extra}) from {f.source}")
    lib.packs.scan()
    if args.accept:
        rc = 0
        for wid in ids:
            rc |= cmd_suggest(lib, argparse.Namespace(id=wid, write=True))
        return rc
    print(f"next: comfyui workflows suggest {ids[0]}   (review it, then add --write)")
    return 0


def cmd_suggest(lib: Library, args) -> int:
    p = _get(lib, args.id)
    if p is None:
        return 1
    s, toml = lib.suggest(p)
    if s is None:
        print(f"{args.id} can't be converted; see: comfyui workflows check {args.id}", file=sys.stderr)
        return 1
    if not args.write:
        print(toml, end="")
        for n in s.notes:
            print(f"# note: {n}")
        return 0
    if p.dir is None:
        p = lib.packs.adopt(p.id)
    target = p.dir / "workflow.toml"
    if target.exists():
        print(f"{target} exists; not overwriting it (delete it first to start over)", file=sys.stderr)
        return 1
    target.write_text(toml)
    lib.packs.scan()
    print(f"wrote workflows/{p.id}/workflow.toml")
    return cmd_check(lib, argparse.Namespace(ids=[p.id], all=False, verbose=False))


def cmd_copy(lib: Library, args) -> int:
    p = _get(lib, args.id)
    if p is None or p.dir is None:
        return 1
    if not PACK_ID.match(args.new_id) or (lib.packs.root / args.new_id).exists():
        print(f"{args.new_id!r} is taken or not a valid id", file=sys.stderr)
        return 1
    shutil.copytree(p.dir, lib.packs.root / args.new_id)
    print(f"copied workflows/{p.id} to workflows/{args.new_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="comfyui workflows", description="Workflow packs (docs/workflows.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="every pack and draft")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="one pack: inputs, nodes and issues")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="check packs against the installed nodes and models")
    p.add_argument("ids", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("new", help="a new pack from a workflow file (or a draft saved in ComfyUI)")
    p.add_argument("id")
    p.add_argument("--from", dest="source", required=True, help="an editor .json, an API .json, or a draft's id")
    p.add_argument("--accept", action="store_true", help="write the suggested workflow.toml straight away")
    p = sub.add_parser("suggest", help="draft a workflow.toml from the graph (prints it; --write saves it)")
    p.add_argument("id")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("copy", help="copy a pack to a new id")
    p.add_argument("id")
    p.add_argument("new_id")
    args = ap.parse_args(argv)
    lib = _library(Settings.from_env())
    return {"list": cmd_list, "show": cmd_show, "check": cmd_check, "new": cmd_new, "copy": cmd_copy,
            "suggest": cmd_suggest}[args.cmd](lib, args)


if __name__ == "__main__":
    sys.exit(main())
