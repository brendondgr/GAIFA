"""`gaifa backup <folder>` (plan 12.5): the state that can't be rebuilt, in one dated archive.

- every `*.db` in the databases folder, copied with SQLite's online backup (consistent while the
  hub and mods keep writing; WAL files are folded in)
- the models registry (`registry.json`), `config.toml`, each mod's `services/<id>/.env`, and the small
  JSON files mods keep their settings in (`data/state/<id>/*.json` up to 1 MB: the workspace folders and
  their levels, and the like)

Model weights, outputs and venvs are not included: they are large and can be fetched, kept or
rebuilt. The archive holds secrets (the `.env` files), so it is written owner-only (0600).
Standard library only, like cli.py.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path


STATE_MAX_BYTES = 1024 * 1024   # small JSON settings only; labs and caches under data/state/ stay out


def _paths(root: Path) -> tuple[Path, Path]:
    """The databases folder and the registry file, after config.toml's [paths]."""
    paths = {}
    try:
        paths = tomllib.loads((root / "config.toml").read_text()).get("paths", {})
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return root / paths.get("databases", "data/databases"), root / paths.get("models", "data/models") / "registry.json"


def _db_copy(src: Path, dst: Path) -> None:
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    with sqlite3.connect(dst) as d:
        d.execute("PRAGMA journal_mode=DELETE")       # a single self-contained file
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise RuntimeError(f"{src.name}: integrity check of the copy failed: {ok}")


def backup(root: Path, dest: Path, now: float | None = None) -> tuple[Path, list[dict]]:
    """Write `<dest>/gaifa-backup-<YYYY-MM-DD-HHMMSS>.tar.gz`. Returns its path and what's in it."""
    now = now or time.time()
    dbs, registry = _paths(root)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"gaifa-backup-{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(now))}.tar.gz"
    items: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="gaifa-backup-") as tmp:
        staged: list[tuple[Path, str]] = []
        for db in sorted(dbs.glob("*.db")):
            copy = Path(tmp) / db.name
            _db_copy(db, copy)
            staged.append((copy, f"databases/{db.name}"))
        for p, arc in [(registry, "registry.json"), (root / "config.toml", "config.toml")]:
            if p.is_file():
                staged.append((p, arc))
        for env in sorted((root / "services").glob("*/.env")):
            staged.append((env, f"services/{env.parent.name}/.env"))
        for st in sorted((root / "data" / "state").glob("*/*.json")):   # mods' saved settings (workspace folders, …)
            if st.is_file() and st.stat().st_size <= STATE_MAX_BYTES:
                staged.append((st, f"state/{st.parent.name}/{st.name}"))
        part = out.with_name(out.name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tar:
            for p, arc in staged:
                tar.add(p, arcname=arc, recursive=False)
                items.append({"path": arc, "bytes": p.stat().st_size})
            meta = json.dumps({"made": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "root": str(root),
                               "files": items}, indent=1).encode()
            info = tarfile.TarInfo("backup.json")
            info.size, info.mtime, info.mode = len(meta), int(now), 0o600
            tar.addfile(info, io.BytesIO(meta))
        part.replace(out)
    return out, items


def cmd_backup(args: argparse.Namespace, root: Path) -> int:
    dest = Path(args.folder).expanduser().resolve()
    try:
        out, items = backup(root, dest)
    except (OSError, sqlite3.Error, RuntimeError) as e:
        print(f"gaifa backup: {e}")
        return 1
    for it in items:
        print(f"  {it['path']:<40} {it['bytes'] / 1e6:8.1f} MB")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, owner-only: it holds the mods' .env secrets)")
    return 0
