"""12.5: `aihub backup <folder>`: an online copy of every database plus the registry, config.toml
and the mods' .env files, in a dated owner-only archive."""

from __future__ import annotations

import json
import sqlite3
import stat
import tarfile

from utils import cli


def test_backup_archives_live_databases_and_settings(root, tmp_path):
    dbs = root / "data" / "databases"
    dbs.mkdir(parents=True)
    live = sqlite3.connect(dbs / "hub.db")
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE t (x)")
    live.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    live.commit()                                       # still open, rows in the WAL: an online copy
    (root / "data" / "models").mkdir(parents=True)
    (root / "data" / "models" / "registry.json").write_text('{"version": 1, "models": {}}')
    (root / "config.toml").write_text("[hub]\nport = 7000\n")
    (root / "services" / "relay").mkdir()
    (root / "services" / "relay" / ".env").write_text("SECRET=1\n")
    (root / "services" / "tts").mkdir()                 # no .env: nothing to add
    dest = tmp_path / "backups"

    assert cli.main(["backup", str(dest)]) == 0
    live.close()
    [out] = dest.glob("aihub-backup-*.tar.gz")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
        assert names == ["backup.json", "config.toml", "databases/hub.db", "registry.json", "services/relay/.env"]
        tar.extractall(tmp_path / "x", filter="data")
    copy = sqlite3.connect(tmp_path / "x" / "databases" / "hub.db")
    assert copy.execute("SELECT count(*) FROM t").fetchone()[0] == 100
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    meta = json.loads((tmp_path / "x" / "backup.json").read_text())
    assert {f["path"] for f in meta["files"]} == set(names) - {"backup.json"}
