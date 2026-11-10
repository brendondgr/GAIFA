// Layout for the Calendar page (calendar plan 3.3–3.4): where each occurrence goes in a day column, the all-day
// row, and a month's weeks. Pure, so tests/ui/layout.test.mjs and month.test.mjs run it in node.

import { DAY_MS, addDays, parse, sameDay, startOfDay } from './cal-dates.js';

export const HOUR_PX = 48;
export const MIN_PX = 20;            // a short event keeps this height

/** Timed occurrences of one day as boxes: {occ, top, height, col, cols}. Overlapping ones share the width in
 *  even columns (each cluster of overlaps gets as many columns as it needs); an event crossing midnight is cut
 *  to the day. */
export function layoutDay(occs, day, hourPx = HOUR_PX) {
  const d0 = startOfDay(day).getTime(), d1 = addDays(startOfDay(day), 1).getTime();
  const items = occs.filter(o => !o.all_day && o.kind === 'event')
    .filter(o => { const s = o.ts * 1000, e = (o.end_ts ?? o.ts) * 1000; return s < d1 && (e > d0 || (e === s && s >= d0)); })
    .map(o => ({ occ: o, s: Math.max(o.ts * 1000, d0), e: Math.min((o.end_ts ?? o.ts) * 1000, d1) }))
    .sort((a, b) => a.s - b.s || b.e - a.e);
  const px = ms => (ms - d0) / 60000 * (hourPx / 60);
  const out = [];
  let cluster = [], end = -Infinity;
  const flush = () => {
    const cols = [];
    for (const x of cluster) {
      let c = cols.findIndex(lastEnd => lastEnd <= x.s);
      if (c < 0) { c = cols.length; cols.push(0); }
      cols[c] = Math.max(x.e, x.s + 1);
      x.col = c;
    }
    for (const x of cluster) out.push({ occ: x.occ, top: px(x.s), height: Math.max(MIN_PX, px(x.e) - px(x.s)), col: x.col, cols: cols.length });
    cluster = [];
  };
  for (const x of items) {
    if (cluster.length && x.s >= end) { flush(); end = -Infinity; }
    cluster.push(x);
    end = Math.max(end, x.e, x.s + 1);
  }
  if (cluster.length) flush();
  return out;
}

/** The all-day row for a run of days: bars {occ, start, span, row} (start: the day index), and per day the
 *  bars past `maxRows` as a count ("+N"). To-dos without a time are all-day items too. */
export function layoutAllDay(occs, days, maxRows = 3) {
  const first = startOfDay(days[0]).getTime(), n = days.length;
  const idx = d => Math.round((startOfDay(d).getTime() - first) / DAY_MS);
  const items = occs.filter(o => o.all_day).map(o => {
    const s = parse(o.start), e = o.kind === 'todo' ? s : addDays(parse(o.end), -1);
    return { occ: o, a: Math.max(0, idx(s)), b: Math.min(n - 1, idx(e)) };
  }).filter(x => x.b >= 0 && x.a <= n - 1 && x.b >= x.a)
    .sort((p, q) => p.a - q.a || (q.b - q.a) - (p.b - p.a) || String(p.occ.title).localeCompare(q.occ.title));
  const rows = [], bars = [], more = Array(n).fill(0);
  for (const x of items) {
    let r = rows.findIndex(row => row.every(([a, b]) => b < x.a || a > x.b));
    if (r < 0) { r = rows.length; rows.push([]); }
    rows[r].push([x.a, x.b]);
    if (r < maxRows) bars.push({ occ: x.occ, start: x.a, span: x.b - x.a + 1, row: r });
    else for (let i = x.a; i <= x.b; i++) more[i]++;
  }
  return { bars, more, rows: Math.min(rows.length, maxRows) };
}

/** A month view's weeks: [[Date × 7] …] from `days` (rangeOf('month')). */
export const weeksOf = days => Array.from({ length: Math.ceil(days.length / 7) }, (_, i) => days.slice(i * 7, i * 7 + 7));

/** One day cell of a month: its timed items (sorted) up to `max` after the all-day bars that reach it, then
 *  how many more. */
export function dayItems(occs, day, barsHere, max = 3) {
  const timed = occs.filter(o => !o.all_day && sameDay(new Date(o.ts * 1000), day)).sort((a, b) => a.ts - b.ts);
  const room = Math.max(0, max - barsHere);
  return { shown: timed.slice(0, room), more: Math.max(0, timed.length - room) };
}

/** Where a pointer at `y` px (in a day column) falls, in minutes since midnight, snapped to `stepMin`. */
export function minutesAt(y, hourPx = HOUR_PX, stepMin = 15) {
  const m = Math.round(y / (hourPx / 60) / stepMin) * stepMin;
  return Math.max(0, Math.min(24 * 60, m));
}

/** Agenda: occurrences grouped by local day, days without any left out: [{day, items}]. */
export function agendaGroups(occs, from, to) {
  const out = [];
  for (let d = startOfDay(from); d < to; d = addDays(d, 1)) {
    const items = occs.filter(o => {
      if (!o.all_day) return sameDay(new Date(o.ts * 1000), d);
      const s = parse(o.start), e = o.kind === 'todo' ? addDays(s, 1) : parse(o.end);
      return s <= d && d < e;
    }).sort((a, b) => (b.all_day - a.all_day) || a.ts - b.ts);
    if (items.length) out.push({ day: d, items });
  }
  return out;
}
