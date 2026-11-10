// Dates for the Calendar page (calendar plan 3.2–3.4): pure, so tests/ui/*.test.mjs run them in node.
// The calendar's API speaks wall times in this machine's zone ("2026-11-13T13:00", all-day "2026-11-13")
// plus unix seconds (`ts`); the page works in the browser's local time, which is the same machine's.

export const DAY_MS = 86400000;
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const pad = n => String(n).padStart(2, '0');

/** "2026-11-13" for a Date (local). */
export const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
/** "2026-11-13T13:05" for a Date (local). */
export const wall = d => `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
/** A wall string or a date string as a local Date. */
export function parse(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(String(s || ''));
  if (!m) return new Date(NaN);
  return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
}
export const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes());
export const addMonths = (d, n) => { const x = new Date(d.getFullYear(), d.getMonth() + n, 1); return new Date(x.getFullYear(), x.getMonth(), Math.min(d.getDate(), daysIn(x))); };
export const daysIn = d => new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
export const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
/** Monday = 0 … Sunday = 6. */
export const dow = d => (d.getDay() + 6) % 7;
/** The first day of `d`'s week; `weekStart` 0 = Monday, 6 = Sunday. */
export function weekStartOf(d, weekStart = 0) {
  const back = (dow(d) - weekStart + 7) % 7;
  return startOfDay(addDays(d, -back));
}
/** Minutes since local midnight. */
export const minutesOf = d => d.getHours() * 60 + d.getMinutes();

/** The days a view shows: [first, …] (Date at local midnight) and the range [from, to) as dates. */
export function rangeOf(view, date, weekStart = 0) {
  const d = startOfDay(date);
  if (view === 'day') return { from: d, to: addDays(d, 1), days: [d] };
  if (view === 'week') {
    const s = weekStartOf(d, weekStart);
    return { from: s, to: addDays(s, 7), days: Array.from({ length: 7 }, (_, i) => addDays(s, i)) };
  }
  if (view === 'month') {
    const first = new Date(d.getFullYear(), d.getMonth(), 1), s = weekStartOf(first, weekStart);
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0), e = addDays(weekStartOf(last, weekStart), 7);
    const n = Math.round((e - s) / DAY_MS);
    return { from: s, to: e, days: Array.from({ length: n }, (_, i) => addDays(s, i)) };
  }
  return { from: d, to: addDays(d, 30), days: Array.from({ length: 30 }, (_, i) => addDays(d, i)) };   // agenda
}

/** The header's title: "Friday, November 13, 2026", "Nov 9 – 15, 2026", "Nov 30 – Dec 6, 2026", "November 2026". */
export function titleOf(view, date, weekStart = 0) {
  const d = startOfDay(date), M = MONTHS, m3 = i => M[i].slice(0, 3);
  if (view === 'day') return `${['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][d.getDay()]}, ${M[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
  if (view === 'month') return `${M[d.getMonth()]} ${d.getFullYear()}`;
  const { from, to } = rangeOf(view, d, weekStart), last = addDays(to, -1);
  if (from.getFullYear() !== last.getFullYear()) return `${m3(from.getMonth())} ${from.getDate()}, ${from.getFullYear()} – ${m3(last.getMonth())} ${last.getDate()}, ${last.getFullYear()}`;
  if (from.getMonth() !== last.getMonth()) return `${m3(from.getMonth())} ${from.getDate()} – ${m3(last.getMonth())} ${last.getDate()}, ${last.getFullYear()}`;
  return `${m3(from.getMonth())} ${from.getDate()} – ${last.getDate()}, ${last.getFullYear()}`;
}

/** The date one step before or after in a view (j / k, ‹ ›). */
export function step(view, date, n) {
  if (view === 'day') return addDays(date, n);
  if (view === 'week') return addDays(date, 7 * n);
  if (view === 'month') return addMonths(date, n);
  return addDays(date, 30 * n);
}

/** "13:00", or "1:00 PM" with `ampm`. */
export function hhmm(d, ampm = false) {
  if (!ampm) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const h = d.getHours() % 12 || 12;
  return `${h}${d.getMinutes() ? ':' + pad(d.getMinutes()) : ''} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
}

/** An occurrence's time in words: "13:00–14:30", "All day", "Due 17:00", "Due today". */
export function timeText(o) {
  if (o.kind === 'todo') return o.all_day ? 'Due' : `Due ${hhmm(parse(o.due || o.start))}`;
  if (o.all_day) {
    const s = parse(o.start), e = addDays(parse(o.end), -1);
    const m = d => MONTHS[d.getMonth()].slice(0, 3);
    if (sameDay(s, e)) return 'All day';
    return s.getMonth() === e.getMonth() ? `${m(s)} ${s.getDate()}–${e.getDate()}` : `${m(s)} ${s.getDate()} – ${m(e)} ${e.getDate()}`;
  }
  return `${hhmm(parse(o.start))}–${hhmm(parse(o.end))}`;
}

/** "Mon Nov 9" */
export const shortDay = d => `${WEEKDAYS[dow(d)]} ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}`;

/** 15-minute snapping of a minute count. */
export const snap = (min, stepMin = 15) => Math.round(min / stepMin) * stepMin;
