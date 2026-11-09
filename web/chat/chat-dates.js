// The chat list by date (plan chat-history 2.3): Today, Yesterday, the date for 2 and 3 days ago ("Nov 6", "Nov 5"),
// Last week (4 to 7 days) and Older. Days start at local midnight in the browser's time zone. A chat's day is the field
// the chosen order sorts on (`updated` for Recent activity and for Name, `created` for Created); inside a heading the
// chats keep that order (Name: A to Z). `shortDate` is the Show all page's date. Pure helpers first (tested in
// utils/tests/web/chat-dates.test.mjs), then `DateSections`. Written by us (web/PATCHES.md).

import { h, T } from './chat-ui.js';

const DAY_MS = 86400000;
export const BUCKETS = ['today', 'yesterday', 'd2', 'd3', 'week', 'older'];
const FIXED = { today: 'Today', yesterday: 'Yesterday', week: 'Last week', older: 'Older' };

/** Local midnight of the day `now` (seconds) falls on, in seconds. */
export function dayStart(now = Date.now() / 1000) {
  const d = new Date(now * 1000);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
}
/** Whole calendar days from `ts`'s day to `now`'s (a day of 23 or 25 hours still counts as one); 0 for the future. */
export const daysAgo = (ts, now = Date.now() / 1000) => Math.max(0, Math.round((dayStart(now) - dayStart(ts)) * 1000 / DAY_MS));

const fmt = (locale, o) => new Intl.DateTimeFormat(locale, o);
const monthDay = (ts, locale) => fmt(locale, { month: 'short', day: 'numeric' }).format(new Date(ts * 1000));

/** `{key, label}` of the heading a time falls under. */
export function bucketOf(ts, now = Date.now() / 1000, locale = undefined) {
  const n = daysAgo(ts, now);
  const key = n === 0 ? 'today' : n === 1 ? 'yesterday' : n === 2 ? 'd2' : n === 3 ? 'd3' : n <= 7 ? 'week' : 'older';
  return { key, label: FIXED[key] || monthDay(dayStart(now) - n * 86400 + 43200, locale) };   // midday of that day: clear of DST edges
}

/** The field a chat's day comes from for an order: Created → `created`, else `updated`. */
export const dateField = order => (order === 'created' ? 'created' : 'updated');

const ORDERS = {
  title: (a, b) => String(a.title || '').toLowerCase().localeCompare(String(b.title || '').toLowerCase()) || (b.updated || 0) - (a.updated || 0),
  created: (a, b) => (b.created || 0) - (a.created || 0),
  updated: (a, b) => (b.updated || 0) - (a.updated || 0),
};
/** The chats under their headings, in heading order, empty headings left out; inside each, the view's order. */
export function groupByDate(threads, { order = 'updated', field = dateField(order), now = Date.now() / 1000, locale } = {}) {
  const by = new Map();
  for (const t of threads || []) {
    const b = bucketOf(t[field] || 0, now, locale);
    if (!by.has(b.key)) by.set(b.key, { ...b, threads: [] });
    by.get(b.key).threads.push(t);
  }
  return BUCKETS.filter(k => by.has(k)).map(k => { const g = by.get(k); g.threads.sort(ORDERS[order] || ORDERS.updated); return g; });
}

/** A chat's date on the Show all page: a time today ("14:32"), "Yesterday", "Nov 5", or "Nov 5, 2025" in another year. */
export function shortDate(ts, now = Date.now() / 1000, locale = undefined) {
  if (!ts) return '';
  const n = daysAgo(ts, now), d = new Date(ts * 1000);
  if (n === 0) return fmt(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d);
  if (n === 1) return 'Yesterday';
  if (d.getFullYear() === new Date(now * 1000).getFullYear()) return monthDay(ts, locale);
  return fmt(locale, { month: 'short', day: 'numeric', year: 'numeric' }).format(d);
}

// ---------- drawing ----------
export const dateHeadSt = { padding: '10px 10px 3px', fontSize: 11.5, color: T.dim, fontWeight: 500 };

/** The loaded chats under their date headings: a plain heading (no arrow, no count), then its rows. No paging of its
 * own: the page loads the 20 newest, and Show all has the rest. */
export function DateSections({ threads, view, renderItem, now }) {
  const groups = groupByDate(threads, { order: view?.chatOrder || 'updated', now });
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 1 } },
    groups.map(g => h('section', { key: g.key, 'aria-label': g.label, style: { display: 'flex', flexDirection: 'column', gap: 1 } },
      h('h3', { style: { margin: 0, ...dateHeadSt } }, g.label),
      g.threads.map(t => renderItem(t)))));
}
