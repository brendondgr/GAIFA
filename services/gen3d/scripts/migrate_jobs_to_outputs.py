"""Move old job folders (data/jobs/<id>/) into dated output folders and record them.

    python scripts/migrate_jobs_to_outputs.py --db DB --old OLD_JOBS --outputs OUTPUTS [--dry-run]

For each job in the database whose folder is still `<OLD>/<id>/` (no `dir` yet): move it to
`<OUTPUTS>/<created date>/<id>-<slug>/`, set `dir`, and write `output.json` (GAIFA architecture
§4.7). Then every JSON file in the moved folders has old absolute paths rewritten, including paths
into other jobs' folders (`parts/manifest.json` points at the parent job's mesh). Folders with no job in
the database are left where they are and listed. Safe to run again: moved jobs are skipped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen3d.store import Store, job_folder  # noqa: E402


def rewrite_paths(folder: Path, moves: dict[str, str]) -> int:
    """Replace each old absolute folder path with its new one in every JSON file under `folder`."""
    n = 0
    for p in folder.rglob("*.json"):
        text = new = p.read_text()
        for old, dst in moves.items():
            new = new.replace(old + "/", dst + "/").replace(f'"{old}"', f'"{dst}"')
        if new != text:
            p.write_text(new)
            n += 1
    return n


def migrate(db: Path, old: Path, outputs: Path, dry_run: bool = False) -> dict:
    old, outputs = old.resolve(), outputs.resolve()
    store = Store(db_path=db, jobs_dir=outputs)
    moved, skipped = [], []
    try:
        known = set()
        for job in sorted(store.list_jobs(limit=100_000), key=lambda j: j["created"]):
            jid = job["id"]
            known.add(jid)
            src = old / jid
            row = store._q("SELECT dir FROM jobs WHERE id=?", (jid,))[0]
            if row["dir"] or not src.is_dir():
                skipped.append(jid)
                continue
            folder = job_folder(jid, job.get("title") or job["request"].get("prompt"), job["created"])
            dst = outputs / folder
            moved.append((jid, str(src), str(dst)))
            if dry_run:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            store.update_job(jid, dir=folder)
            store.write_output_json(jid)
        moves = {src: dst for _, src, dst in moved}
        if not dry_run:
            for _, _, dst in moved:
                rewrite_paths(Path(dst), moves)
        orphans = sorted(p.name for p in old.iterdir() if p.is_dir() and p.name not in known) if old.is_dir() else []
    finally:
        store.close()
    return {"moved": moved, "skipped": skipped, "orphans": orphans}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--old", type=Path, required=True, help="the old jobs folder (data/jobs)")
    ap.add_argument("--outputs", type=Path, required=True, help="the new jobs folder (outputs/gen3d)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r = migrate(a.db, a.old, a.outputs, a.dry_run)
    for jid, src, dst in r["moved"]:
        print(f"{'would move' if a.dry_run else 'moved'} {jid}: {src} -> {dst}")
    print(f"{len(r['moved'])} moved, {len(r['skipped'])} already done or without a folder")
    for o in r["orphans"]:
        print(f"left alone (not in the database): {a.old / o}")


if __name__ == "__main__":
    main()
