"""6.1: rollups (avg, min, max, weighted by count), retention, and gaps on an even axis."""

from __future__ import annotations

import pytest

from utils.metrics.store import DAY, HOUR, MetricsError, SeriesInfo, Store, axis, parse_range, pick_step
from utils.tests.metrics.conftest import T0

X = SeriesInfo("x", "X", "count")
Y = SeriesInfo("y", "Y", "bytes", service="svc")


async def fill(store: Store, start: int, end: int, value=lambda ts: float(ts % 600), series=(X,)) -> None:
    for ts in range(start, end, 10):
        await store.record(ts, [(s, value(ts)) for s in series])


async def rows(db, table):
    return await db.fetchall(f"SELECT s.name, m.* FROM {table} m JOIN series s ON s.id = m.sid ORDER BY s.name, ts")


async def test_rollup_avg_min_max(db):
    st = Store(db)
    base = T0 // HOUR * HOUR
    await fill(st, base, base + 2 * HOUR, value=lambda ts: float((ts - base) // 10 % 6))  # 0..5 every minute
    await st.record(base + 30, [(X, None)])  # a NULL sample is not counted
    out = await st.rollup(base + 2 * HOUR + 5)
    assert out["1m"] == 120 and out["1h"] == 2
    m = await rows(db, "metrics_1m")
    assert len(m) == 120
    first = m[0]
    # 0,1,2,(NULL),4,5 → avg 2.4 over 5 samples
    assert (first["avg"], first["min"], first["max"], first["n"]) == (pytest.approx(2.4), 0, 5, 5)
    assert all((r["avg"], r["min"], r["max"], r["n"]) == (2.5, 0, 5, 6) for r in m[1:])
    h = await rows(db, "metrics_1h")
    # weighted by n: (2.4·5 + 2.5·6·59) / (5 + 6·59)
    assert h[0]["avg"] == pytest.approx((2.4 * 5 + 2.5 * 6 * 59) / 359) and h[0]["n"] == 359
    assert (h[0]["min"], h[0]["max"]) == (0, 5) and h[1]["n"] == 360
    # running it again changes nothing (watermarks)
    again = await st.rollup(base + 2 * HOUR + 5)
    assert again["1m"] == 0 and again["1h"] == 0 and len(await rows(db, "metrics_1m")) == 120


async def test_rollup_only_finished_buckets(db):
    st = Store(db)
    base = T0 // HOUR * HOUR
    await fill(st, base, base + 90)  # a minute and a half
    await st.rollup(base + 90)
    assert [r["ts"] for r in await rows(db, "metrics_1m")] == [base]  # the half minute waits
    assert await rows(db, "metrics_1h") == []
    await fill(st, base + 90, base + 120)
    await st.rollup(base + 125)
    assert [r["ts"] for r in await rows(db, "metrics_1m")] == [base, base + 60]
    assert (await rows(db, "metrics_1m"))[1]["n"] == 6


async def test_retention(db):
    st = Store(db)
    now = T0 // HOUR * HOUR + 500 * DAY
    for age, table in ((49 * HOUR, "metrics_raw"), (15 * DAY, "metrics_1m"), (401 * DAY, "metrics_1h")):  # each just past its keep
        sid = 1
        await db.execute("INSERT OR IGNORE INTO series (id, name, label, unit) VALUES (1, 'x', 'X', 'count')")
        cols = "(sid, ts, value)" if table == "metrics_raw" else "(sid, ts, avg, min, max, n)"
        vals = "(?, ?, 1)" if table == "metrics_raw" else "(?, ?, 1, 1, 1, 1)"
        await db.execute(f"INSERT INTO {table} {cols} VALUES {vals}", (sid, now - age))
        await db.execute(f"INSERT INTO {table} {cols} VALUES {vals}", (sid, now - age + 2 * DAY if age > 2 * DAY else now - age + 2 * HOUR))  # and one inside it
    # kv watermarks past everything, so the rollup itself adds nothing
    await db.execute("INSERT INTO kv VALUES ('metrics.rolled_1m', ?), ('metrics.rolled_1h', ?)", (now, now))
    out = await st.rollup(now)
    assert out["pruned_metrics_raw"] == 1 and out["pruned_metrics_1m"] == 1 and out["pruned_metrics_1h"] == 1
    for table in ("metrics_raw", "metrics_1m", "metrics_1h"):
        assert len(await db.fetchall(f"SELECT * FROM {table}")) == 1
    # event rows: closed ones older than 400 days go, open ones stay
    await db.execute("INSERT INTO service_states (service, state, from_ts, to_ts) VALUES ('a', 'ready', ?, ?)", (now - 402 * DAY, now - 401 * DAY))
    await db.execute("INSERT INTO service_states (service, state, from_ts) VALUES ('a', 'ready', ?)", (now - 402 * DAY,))
    await st.rollup(now)
    assert [r["to_ts"] for r in await db.fetchall("SELECT to_ts FROM service_states")] == [None]


async def test_query_gap_across_downtime(db):
    """Samples stop for 10 minutes (the hub was down): those buckets are null, never interpolated."""
    st = Store(db)
    base = T0 // HOUR * HOUR
    await fill(st, base, base + 20 * 60, value=lambda ts: 1.0, series=(X, Y))
    await fill(st, base + 30 * 60, base + HOUR, value=lambda ts: 3.0, series=(X, Y))
    t, s = await st.query(["x", "y", "nope"], base, base + HOUR, 60)
    assert t == list(range(base, base + HOUR, 60)) and len(s["x"]) == 60
    assert s["x"][:20] == [1.0] * 20 and s["x"][20:30] == [None] * 10 and s["x"][30:] == [3.0] * 30
    assert s["y"] == s["x"] and s["nope"] == [None] * 60
    # the same from the minute rollups (a 24 h range reads metrics_1m up to its watermark, then raw)
    await st.rollup(base + 45 * 60)
    t, s = await st.query(["x"], base + HOUR - DAY, base + HOUR, 300)
    tail = s["x"][-12:]  # the last hour in 5-minute buckets
    assert tail == [1.0, 1.0, 1.0, 1.0, None, None, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0]
    assert all(v is None for v in s["x"][:-12])
    # and from the hour rollups (30 d) once the hour has rolled up
    await st.rollup(base + 2 * HOUR)
    t, s = await st.query(["x"], base + 2 * HOUR - 30 * DAY, base + 2 * HOUR, 7200)
    assert s["x"][-1] == pytest.approx((1.0 * 120 + 3.0 * 180) / 300)


async def test_expand_families(db):
    st = Store(db)
    a, b = SeriesInfo("mem.svc.a", "A", "bytes", "a"), SeriesInfo("mem.svc.b", "B", "bytes", "b")
    await st.record(T0, [(a, 1.0)])
    await st.record(T0 + 10, [(b, 1.0), (X, 2.0)])
    assert await st.expand(["mem.svc.*", "x"], T0) == ["mem.svc.a", "mem.svc.b", "x"]
    assert await st.expand(["mem.svc.*"], T0 + 5) == ["mem.svc.b"]  # a has no samples in range
    infos = {i.name: i.as_dict() for i in await st.series()}
    assert infos["mem.svc.a"] == {"name": "mem.svc.a", "label": "A", "unit": "bytes", "service": "a"}


def test_ranges_and_steps():
    assert parse_range("24h") == ("24h", DAY) and parse_range(None) == ("1h", HOUR) and parse_range("90m") == ("90m", 5400)
    for bad in ("0h", "1y", "401d", "abc"):
        with pytest.raises(MetricsError):
            parse_range(bad)
    assert pick_step(HOUR, None) == 10 and pick_step(DAY, None) == 300 and pick_step(30 * DAY, None) == 7200
    assert pick_step(DAY, 7) == 60  # at least the table's resolution, in whole buckets
    assert pick_step(HOUR, 1) == 10 and pick_step(6 * HOUR, 10) == 20  # ≤ 2000 points
    assert axis(105, 165, 30) == [90, 120, 150]
