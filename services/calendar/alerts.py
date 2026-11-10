"""Alerts (calendar plan 2.3): every 20 s, the alerts that came due since the last check are recorded in `fired`
and posted to the hub's `POST /api/notify` (a toast with Snooze and, for a to-do, Done), followed by the unread
count (the Calendar item's badge).

- An alert is `before_min` minutes before a timed occurrence (a to-do's due time). An all-day item's alert is at
  `allday_alert` (09:00) on its day for `before_min = 0`, else that time on the day before.
- The last check is kept in the store (`meta.alerts_checked`): alerts missed while the mod was down fire once,
  marked late; ones more than 24 hours old are only listed (no toast).
- A hub that's down is retried on the next tick (`fired.posted`): a fired alert is never lost.
- Snoozed alerts come back as unread at `snooze_until`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import repeat as R
import timeutil as T
from store import new_id

log = logging.getLogger("calendar.alerts")
TICK_S = 20
LATE_S = 120
OLD_S = 24 * 3600
Poster = Callable[[dict[str, Any]], Awaitable[bool]]


def alert_time(occ: dict[str, Any], before_min: int, allday_at: str) -> float:
    if occ["all_day"]:
        day = datetime.fromisoformat(occ["start"][:10]).date() - timedelta(days=1 if before_min > 0 else 0)
        hh, mm = (int(x) for x in allday_at.split(":"))
        return datetime(day.year, day.month, day.day, hh, mm, tzinfo=T.local_tz()).timestamp()
    return occ["ts"] - before_min * 60


def body_of(occ: dict[str, Any], now: float) -> str:
    tz = T.local_tz()
    fmt = lambda ts: datetime.fromtimestamp(ts, tz).strftime("%H:%M")  # noqa: E731
    if occ["kind"] == "todo":
        return "due today" if occ["all_day"] else f"due {fmt(occ['ts'])}"
    if occ["all_day"]:
        d = datetime.fromisoformat(occ["start"][:10]).date()
        return "today, all day" if d == datetime.now(tz).date() else f"{d.strftime('%a %b')} {d.day}, all day"
    mins = round((occ["ts"] - now) / 60)
    when = "now" if abs(mins) < 1 else f"in {mins} min" if 0 < mins < 60 else f"in {mins // 60} h {mins % 60:02d} min" if mins > 0 else f"started {-mins} min ago"
    return f"{when} · {fmt(occ['ts'])}–{fmt(occ['end_ts'])}"


class Alerts:
    def __init__(self, cal: Any, poster: Poster | None = None) -> None:
        self.cal = cal
        self.poster = poster or self._post_hub
        self.task: asyncio.Task[None] | None = None
        self._client: Any = None
        self._next: float | None = None

    @property
    def store(self) -> Any:
        return self.cal.store

    # ---- the loop ----------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._client is not None:
            await self._client.aclose()

    async def _loop(self) -> None:
        await self.post_unread()
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001: the loop never stops
                log.exception("alerts tick")
            await asyncio.sleep(TICK_S)

    async def _post_hub(self, body: dict[str, Any]) -> bool:
        if not self.cal.hub_url:
            return False
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5)
        try:
            r = await self._client.post(self.cal.hub_url.rstrip("/") + "/api/notify", json={"service": "calendar", **body})
            return r.status_code < 300
        except Exception as e:  # noqa: BLE001
            log.info("the hub didn't take a notification: %s", e)
            return False

    # ---- one check ---------------------------------------------------------------------------------------------
    def _checked(self) -> float | None:
        r = self.store.db.execute("SELECT value FROM meta WHERE key = 'alerts_checked'").fetchone()
        return float(r[0]) if r else None

    def _set_checked(self, t: float) -> None:
        self.store.db.execute("INSERT INTO meta(key, value) VALUES('alerts_checked', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(t),))

    def due(self, frm: float, to: float) -> list[tuple[float, dict[str, Any], int]]:
        """(alert time, occurrence, before_min) for every alert with frm < time <= to; done to-dos have none."""
        allday_at = self.cal.settings.get()["allday_alert"]
        items = [i for i in self.store.items() if i.get("alerts")]
        if not items:
            return []
        lead = max(a["before_min"] for i in items for a in i["alerts"]) * 60 + 2 * 86400
        tz = T.local_tz()
        a, b = datetime.fromtimestamp(frm, tz), datetime.fromtimestamp(to + lead, tz)
        out = []
        ovs = self.store.all_overrides([i["id"] for i in items if i.get("rrule")])
        for it in items:
            if it["kind"] == "todo" and not it.get("rrule") and it.get("done_at"):
                continue
            for o in R.occurrences(it, ovs.get(it["id"], {}), a - timedelta(days=1), b):
                if o.get("done"):
                    continue
                for al in it["alerts"]:
                    t = alert_time(o, al["before_min"], allday_at)
                    if frm < t <= to:
                        out.append((t, o, al["before_min"]))
        out.sort(key=lambda x: x[0])
        return out

    async def tick(self, now: float | None = None) -> list[str]:
        """Fire what came due; post what wasn't posted; bring back snoozed alerts. The new fired ids."""
        now = now if now is not None else time.time()
        last = self._checked()
        frm = last if last is not None else now - TICK_S
        made = []
        with self.store.lock:
            for t, o, before in self.due(frm, now):
                fid = new_id("f")
                late = 1 if t < now - LATE_S else 0
                old = t < now - OLD_S
                cur = self.store.db.execute(
                    "INSERT OR IGNORE INTO fired(id, item_id, occurrence, alert_at, fired_at, state, late, title, body, kind, before_min, posted, ts) "
                    "VALUES (?,?,?,?,?, 'unread', ?,?,?,?,?,?,?)",
                    (fid, o["item_id"], o["occurrence"], t, now, late, o["title"], body_of(o, t if late else now), o["kind"], before,
                     1 if old else 0, o["ts"]))
                if cur.rowcount:
                    made.append(fid)
            self.store.db.execute("UPDATE fired SET state = 'unread', posted = 0, fired_at = ? WHERE state = 'snoozed' AND snooze_until <= ?", (now, now))
            self._set_checked(now)
            if made:
                self.store.bump()
        await self.post_pending(now)
        self._next = self._next_after(now)
        return made

    async def post_pending(self, now: float) -> None:
        rows = self.store.db.execute("SELECT * FROM fired WHERE posted = 0 AND state = 'unread' ORDER BY alert_at LIMIT 20").fetchall()
        changed = False
        for r in rows:
            acts = [{"label": "Snooze 10 min", "op": f"POST /v1/alerts/{r['id']}/snooze?minutes=10"}]
            if r["kind"] == "todo":
                acts.append({"label": "Done", "op": f"POST /v1/alerts/{r['id']}/done"})
            body = r["body"] + (" (missed while GAIFA was off)" if r["late"] else "")
            ok = await self.poster({"title": r["title"], "body": body, "level": "info", "key": r["id"], "actions": acts,
                                    "route": f"#/calendar?item={r['item_id']}@{r['occurrence']}"})
            if not ok:
                break
            self.store.db.execute("UPDATE fired SET posted = 1 WHERE id = ?", (r["id"],))
            changed = True
        if changed or rows:
            await self.post_unread()

    async def post_unread(self) -> bool:
        return await self.poster({"unread": self.store.db.execute("SELECT COUNT(*) FROM fired WHERE state = 'unread'").fetchone()[0]})

    def _next_after(self, now: float) -> float | None:
        nxt = self.due(now, now + 2 * 86400)
        snz = self.store.db.execute("SELECT MIN(snooze_until) FROM fired WHERE state = 'snoozed'").fetchone()[0]
        cands = [x[0] for x in nxt[:1]] + ([snz] if snz else [])
        return min(cands) if cands else None

    def next_at(self) -> float | None:
        return self._next

    # ---- what you do with one ----------------------------------------------------------------------------------
    def list(self, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM fired", []
        if state and state != "all":
            sql += " WHERE state = ?"
            args.append(state)
        sql += " ORDER BY (state = 'unread') DESC, alert_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def get(self, fid: str) -> dict[str, Any]:
        r = self.store.db.execute("SELECT * FROM fired WHERE id = ?", (fid,)).fetchone()
        if r is None:
            from store import NotFound
            raise NotFound(fid)
        return dict(r)

    async def mark(self, fid: str, state: str, snooze_until: float | None = None) -> dict[str, Any]:
        f = self.get(fid)
        with self.store.lock:
            if state == "done" and f["kind"] == "todo":
                try:
                    it = self.store.get(f["item_id"])
                    self.cal.items.done(f["item_id"], {}, f["occurrence"] if it.get("rrule") else None)
                except Exception as e:  # noqa: BLE001: the alert is marked whatever happened to the item
                    log.info("done from an alert: %s", e)
            self.store.db.execute("UPDATE fired SET state = ?, snooze_until = ?, posted = 1 WHERE id = ?", (state, snooze_until, fid))
            self.store.bump()
        if state == "snoozed":
            self._next = min(x for x in (self._next, snooze_until) if x) if snooze_until else self._next
        await self.post_unread()
        return self.get(fid)

    async def seen_all(self) -> int:
        with self.store.lock:
            n = self.store.db.execute("UPDATE fired SET state = 'seen', posted = 1 WHERE state = 'unread'").rowcount
            self.store.bump()
        await self.post_unread()
        return n
