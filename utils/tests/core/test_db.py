import asyncio
import sqlite3
import time

import pytest

from utils.db import MIGRATIONS, Database, migrate


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "hub.db")
    d.open()
    yield d
    d.close()


def tables(db):
    return {r["name"] for r in db.fetchall_sync("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migrations_apply_once(db, tmp_path):
    assert db.version == len(MIGRATIONS) >= 6
    assert {"activity", "service_peaks", "kv", "outputs", "series", "metrics_raw", "metrics_1m", "metrics_1h",
            "service_states", "load_intervals", "job_history", "approvals", "tool_calls", "sessions", "tool_refusals"} <= tables(db)
    assert db.fetchone_sync("PRAGMA journal_mode")["journal_mode"] == "wal"
    db.close()
    again = Database(tmp_path / "hub.db")
    again.open()  # would fail with "table already exists" if 001 re-ran
    assert again.version == len(MIGRATIONS)
    again.close()


def test_new_migration_applies_on_top(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db", isolation_level=None)
    n = len(MIGRATIONS)
    assert migrate(conn) == n
    assert migrate(conn, MIGRATIONS + ["CREATE TABLE extra (x);"]) == n + 1
    assert migrate(conn, MIGRATIONS + ["CREATE TABLE extra (x);"]) == n + 1


def test_failed_migration_rolls_back(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db", isolation_level=None)
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, ["CREATE TABLE a (x); CREATE TABLE a (x);"])
    assert not conn.in_transaction
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='a'").fetchone()[0] == 0


async def test_execute_and_fetch(db):
    rid = await db.execute(
        "INSERT INTO activity (ts, service, level, text) VALUES (?, ?, ?, ?)", (1.0, "tts", "info", "hi")
    )
    assert rid == 1
    row = await db.fetchone("SELECT * FROM activity WHERE id = ?", (rid,))
    assert row["text"] == "hi" and row["route"] is None
    n = await db.executemany("INSERT INTO kv (key, value) VALUES (?, ?)", [("a", "1"), ("b", "2")])
    assert n == 2
    assert await db.execute("UPDATE kv SET value = 'x'") == 2
    assert [r["value"] for r in await db.fetchall("SELECT value FROM kv ORDER BY key")] == ["x", "x"]


async def test_write_error_rolls_back(db):
    def bad(c):
        c.execute("INSERT INTO kv (key, value) VALUES ('k', 'v')")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await db.write(bad)
    assert await db.fetchone("SELECT * FROM kv WHERE key='k'") is None
    await db.execute("INSERT INTO kv (key, value) VALUES ('k', 'ok')")  # writer still alive
    assert (await db.fetchone("SELECT value FROM kv WHERE key='k'"))["value"] == "ok"


async def test_reads_during_a_write(db):
    await db.execute("INSERT INTO kv (key, value) VALUES ('before', '1')")

    def slow_write(c):
        c.execute("INSERT INTO kv (key, value) VALUES ('during', '1')")
        time.sleep(0.4)

    writing = asyncio.ensure_future(db.write(slow_write))
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    rows = await asyncio.gather(*(db.fetchall("SELECT key FROM kv") for _ in range(8)))
    assert time.monotonic() - t0 < 0.3  # readers did not wait for the writer
    assert all([r["key"] for r in rs] == ["before"] for rs in rows)
    await writing
    assert {r["key"] for r in await db.fetchall("SELECT key FROM kv")} == {"before", "during"}


async def test_writes_are_serialised(db):
    await asyncio.gather(
        *(db.execute("INSERT INTO activity (ts, level, text) VALUES (?, 'info', 'x')", (i,)) for i in range(50))
    )
    assert (await db.fetchone("SELECT count(*) AS n FROM activity"))["n"] == 50


def test_closed_db_refuses_writes(tmp_path):
    d = Database(tmp_path / "hub.db")
    with pytest.raises(RuntimeError, match="not open"):
        d.submit(lambda c: None)


def test_close_waits_for_reads_in_other_threads(tmp_path):
    """Closing while worker threads are mid-query (an app shutting down with a to_thread read
    in flight) must not close a connection under a running query: that segfaults SQLite."""
    import threading

    for _ in range(20):
        d = Database(tmp_path / "busy.db")
        d.open()
        d.submit(lambda c: c.executemany("INSERT INTO kv (key, value) VALUES (?, ?)", [(str(i), "v" * 200) for i in range(2000)])).result()
        stop, errors = threading.Event(), []

        def hammer():
            while not stop.is_set():
                try:
                    d.fetchall_sync("SELECT a.key FROM kv a JOIN kv b ON a.value = b.value LIMIT 3000")
                except RuntimeError:
                    return  # "database is closed": the expected way out
                except sqlite3.ProgrammingError:
                    return
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                    return

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.02)
        d.close()
        stop.set()
        for t in threads:
            t.join(5)
        assert not errors
        with pytest.raises(RuntimeError, match="closed"):
            d.fetchall_sync("SELECT 1")
        (tmp_path / "busy.db").unlink()
