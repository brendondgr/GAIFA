"""Time series in `hub.db` (architecture §13): samples, rollups, retention and queries.

- **Samples** sit on a 10 s grid in `metrics_raw` (`value` may be NULL: a deliberate break).
- **Rollups** (`metrics_1m`, `metrics_1h`) hold avg/min/max and the sample count `n`; the hour
  rollup averages the minute rollups by weight. A watermark per table (in `kv`) marks what is
  rolled up, so `rollup()` is safe to run any time and never counts a sample twice.
- **Queries** read the coarsest table that covers each part of the range (rolled-up history,
  then the finer tables past their watermarks) and bucket it onto an even `t` axis. A bucket
  with no samples is `None`: a gap, never a line across missing time.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.db import Database

RAW_STEP = 10
MIN, HOUR, DAY = 60, 3600, 86400
KEEP = {"metrics_raw": 48 * HOUR, "metrics_1m": 14 * DAY, "metrics_1h": 400 * DAY}
EVENTS_KEEP_S = 400 * DAY
WM_1M, WM_1H = "metrics.rolled_1m", "metrics.rolled_1h"  # everything before this ts is rolled up
RANGES = {"1h": HOUR, "6h": 6 * HOUR, "24h": DAY, "7d": 7 * DAY, "14d": 14 * DAY, "30d": 30 * DAY}
DEFAULT_STEP = {HOUR: 10, 6 * HOUR: MIN, DAY: 5 * MIN, 7 * DAY: 30 * MIN, 14 * DAY: HOUR, 30 * DAY: 2 * HOUR}
MAX_RANGE_S = 400 * DAY
MAX_POINTS = 2000
_RANGE = re.compile(r"^(\d{1,4})([mhd])$")


class MetricsError(ValueError):
    """A bad range, step or series name (422)."""


@dataclass(frozen=True)
class SeriesInfo:
    name: str
    label: str
    unit: str
    service: str | None = None
    reset: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "label": self.label, "unit": self.unit}
        if self.service:
            d["service"] = self.service
        if self.reset:
            d["reset"] = self.reset
        return d


def parse_range(r: str | None, default: str = "1h") -> tuple[str, int]:
    """`"24h"` → ("24h", 86400). Accepts `<n>m|h|d` up to 400 days."""
    r = (r or default).strip().lower()
    if r in RANGES:
        return r, RANGES[r]
    m = _RANGE.match(r)
    if not m:
        raise MetricsError(f"range {r!r}: use 1h, 6h, 24h, 7d, 30d or <n>m|h|d")
    seconds = int(m[1]) * {"m": MIN, "h": HOUR, "d": DAY}[m[2]]
    if not 0 < seconds <= MAX_RANGE_S:
        raise MetricsError(f"range {r!r}: must be between 1m and 400d")
    return r, seconds


def table_for(seconds: int) -> tuple[str, int]:
    """The table a range reads (≤ 6 h raw, ≤ 7 d minutes, else hours) and its resolution."""
    if seconds <= 6 * HOUR:
        return "metrics_raw", RAW_STEP
    if seconds <= 7 * DAY:
        return "metrics_1m", MIN
    return "metrics_1h", HOUR


def pick_step(seconds: int, step: int | None) -> int:
    _, res = table_for(seconds)
    if step is None:
        step = DEFAULT_STEP.get(seconds) or max(res, math.ceil(seconds / 360))
    if step <= 0:
        raise MetricsError("step must be a positive number of seconds")
    step = max(res, math.ceil(step / res) * res)  # a whole number of the table's buckets
    while math.ceil(seconds / step) > MAX_POINTS:
        step += res
    return step


def axis(frm: float, to: float, step: int) -> list[int]:
    t0 = int(frm // step * step)
    return list(range(t0, int(to), step)) or [t0]


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._ids: dict[str, int] = {}
        self._infos: dict[str, SeriesInfo] = {}

    # writes -----------------------------------------------------------------------

    def _sid(self, c: sqlite3.Connection, info: SeriesInfo) -> int:
        if self._infos.get(info.name) == info and info.name in self._ids:
            return self._ids[info.name]
        c.execute(
            "INSERT INTO series (name, label, unit, service, reset) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET label = excluded.label, unit = excluded.unit, "
            "service = excluded.service, reset = excluded.reset",
            (info.name, info.label, info.unit, info.service, info.reset),
        )
        sid = c.execute("SELECT id FROM series WHERE name = ?", (info.name,)).fetchone()[0]
        self._ids[info.name], self._infos[info.name] = sid, info
        return sid

    async def record(self, ts: int, samples: list[tuple[SeriesInfo, float | None]], extra: Any = None) -> None:
        """Write one tick's samples (and `extra(conn)` in the same transaction)."""

        def run(c: sqlite3.Connection) -> None:
            rows = [(self._sid(c, info), ts, value) for info, value in samples]
            c.executemany("INSERT OR REPLACE INTO metrics_raw (sid, ts, value) VALUES (?, ?, ?)", rows)
            c.executemany("UPDATE series SET last_ts = ? WHERE id = ?", [(ts, sid) for sid, _, _ in rows])
            if extra:
                extra(c)

        await self.db.write(run)

    async def rollup(self, now: float) -> dict[str, int]:
        """Roll finished minutes and hours up, then drop what is past its retention."""

        def run(c: sqlite3.Connection) -> dict[str, int]:
            out = {}
            end_m = int(now // MIN * MIN)
            out["1m"] = _roll(c, WM_1M, "metrics_raw", "metrics_1m", MIN, end_m,
                              "AVG(value), MIN(value), MAX(value), COUNT(value)", "COUNT(value) > 0")
            end_h = int(min(end_m, _wm(c, WM_1M) or end_m) // HOUR * HOUR)
            out["1h"] = _roll(c, WM_1H, "metrics_1m", "metrics_1h", HOUR, end_h,
                              "SUM(avg * n) / SUM(n), MIN(min), MAX(max), SUM(n)", "SUM(n) > 0")
            for table, keep in KEEP.items():
                out[f"pruned_{table}"] = c.execute(f"DELETE FROM {table} WHERE ts < ?", (now - keep,)).rowcount
            cutoff = now - EVENTS_KEEP_S
            for table, col in (("service_states", "to_ts"), ("load_intervals", "to_ts"), ("job_history", "end_ts")):
                c.execute(f"DELETE FROM {table} WHERE {col} IS NOT NULL AND {col} < ?", (cutoff,))
            return out

        return await self.db.write(run)

    # reads ------------------------------------------------------------------------

    async def series(self) -> list[SeriesInfo]:
        rows = await self.db.fetchall("SELECT name, label, unit, service, reset FROM series ORDER BY name")
        return [SeriesInfo(**r) for r in rows]

    async def expand(self, names: list[str], since: float) -> list[str]:
        """`mem.svc.*` → every known `mem.svc.<id>` with samples since `since`; plain names as given."""
        out: list[str] = []
        known = None
        for n in names:
            if n.endswith(".*"):
                if known is None:
                    known = await self.db.fetchall("SELECT name, last_ts FROM series ORDER BY name")
                prefix = n[:-1]
                out += [r["name"] for r in known if r["name"].startswith(prefix) and r["last_ts"] >= since]
            else:
                out.append(n)
        return list(dict.fromkeys(out))

    async def query(self, names: list[str], frm: float, to: float, step: int) -> tuple[list[int], dict[str, list[float | None]]]:
        t = axis(frm, to, step)
        ids = {r["name"]: r["id"] for r in await self.db.fetchall(
            f"SELECT id, name FROM series WHERE name IN ({','.join('?' * len(names))})", names)} if names else {}
        series: dict[str, list[float | None]] = {n: [None] * len(t) for n in names}
        if not ids:
            return t, series
        lo, hi = t[0], t[-1] + step
        table, _ = table_for(int(to - frm))
        wm_m = await self._wm(WM_1M)
        wm_h = await self._wm(WM_1H)
        # Each part of the range from the coarsest table that has it.
        parts: list[tuple[str, float, float]] = []
        if table == "metrics_1h":
            parts.append(("metrics_1h", lo, min(hi, wm_h)))
            parts.append(("metrics_1m", max(lo, wm_h), min(hi, wm_m)))
        elif table == "metrics_1m":
            parts.append(("metrics_1m", lo, min(hi, wm_m)))
        parts.append(("metrics_raw", max(lo, wm_m) if table != "metrics_raw" else lo, hi))
        sums: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
        q = ",".join("?" * len(ids))
        for tbl, a, b in parts:
            if a >= b:
                continue
            cols = "sid, ts, value, 1" if tbl == "metrics_raw" else "sid, ts, avg, n"
            rows = await self.db.fetchall(
                f"SELECT {cols} FROM {tbl} WHERE sid IN ({q}) AND ts >= ? AND ts < ?", [*ids.values(), a, b])
            for r in rows:
                sid, ts, v, n = r.values()
                if v is None or not n:
                    continue
                acc = sums[(sid, int((ts - lo) // step))]
                acc[0] += v * n
                acc[1] += n
        by_id = {v: k for k, v in ids.items()}
        for (sid, i), (total, n) in sums.items():
            if 0 <= i < len(t) and n:
                series[by_id[sid]][i] = total / n
        return t, series

    async def _wm(self, key: str) -> float:
        row = await self.db.fetchone("SELECT value FROM kv WHERE key = ?", (key,))
        return float(row["value"]) if row and row["value"] else 0.0


def _wm(c: sqlite3.Connection, key: str) -> int | None:
    row = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return int(float(row[0])) if row and row[0] else None


def _roll(c: sqlite3.Connection, key: str, src: str, dst: str, size: int, end: int, aggs: str, having: str) -> int:
    start = _wm(c, key)
    if start is None:
        first = c.execute(f"SELECT MIN(ts) FROM {src}").fetchone()[0]
        if first is None:
            return 0
        start = int(first // size * size)
    if end <= start:
        return 0
    n = c.execute(
        f"INSERT OR REPLACE INTO {dst} (sid, ts, avg, min, max, n) "
        f"SELECT sid, (ts / {size}) * {size} AS b, {aggs} FROM {src} "
        f"WHERE ts >= ? AND ts < ? GROUP BY sid, b HAVING {having}",
        (start, end),
    ).rowcount
    c.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(end)))
    return n
