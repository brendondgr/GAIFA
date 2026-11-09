// Plan chat-history 2.3: the chat list by date: each heading's edges (local midnight), a change of year, the order
// inside a heading, the field the day comes from, the Show all page's short dates, and the sections drawn.
// Times are built with local-time constructors, so the tests hold in any time zone.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}], useRef: v => ({ current: v }), useEffect: () => {},
};
const d = await import(pathToFileURL(path.join(root, 'web/chat/chat-dates.js')).href);
const at = (y, m, day, hh = 0, mm = 0, ss = 0) => new Date(y, m - 1, day, hh, mm, ss).getTime() / 1000;
const NOW = at(2026, 11, 8, 14, 30);          // Sunday, Nov 8 2026, 14:30 local
const key = ts => d.bucketOf(ts, NOW, 'en-US').key;
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('|') : text(n.props?.children));

test('dayStart is local midnight', () => {
  assert.equal(d.dayStart(NOW), at(2026, 11, 8));
  assert.equal(d.dayStart(at(2026, 11, 8, 0, 0, 1)), at(2026, 11, 8));
  assert.equal(d.dayStart(at(2026, 11, 7, 23, 59, 59)), at(2026, 11, 7));
});

test('each heading\'s edges', () => {
  assert.equal(key(at(2026, 11, 8, 0, 0, 30)), 'today');            // just after midnight
  assert.equal(key(NOW + 3600), 'today');                            // a clock a little ahead: still today
  assert.equal(key(at(2026, 11, 7, 23, 59)), 'yesterday');            // 23:59 the day before
  assert.equal(key(at(2026, 11, 7, 0, 0)), 'yesterday');
  assert.equal(key(at(2026, 11, 6, 23, 59)), 'd2');
  assert.equal(key(at(2026, 11, 5, 12)), 'd3');                      // exactly 3 days back
  assert.equal(key(at(2026, 11, 5, 0, 0)), 'd3');
  assert.equal(key(at(2026, 11, 4, 23, 59)), 'week');                 // 4 days back
  assert.equal(key(at(2026, 11, 1, 0, 0, 1)), 'week');                // 7 days back (and across a DST change in the US)
  assert.equal(key(at(2026, 10, 31, 23, 59)), 'older');               // 8 days back
  assert.equal(key(0), 'older');
});

test('the labels: Today, Yesterday, the dates of 2 and 3 days ago, Last week, Older', () => {
  const label = ts => d.bucketOf(ts, NOW, 'en-US').label;
  assert.deepEqual([at(2026, 11, 8, 9), at(2026, 11, 7, 9), at(2026, 11, 6, 9), at(2026, 11, 5, 9), at(2026, 11, 3), at(2026, 9, 1)].map(label),
    ['Today', 'Yesterday', 'Nov 6', 'Nov 5', 'Last week', 'Older']);
});

test('a change of year', () => {
  const jan = at(2027, 1, 2, 10);
  assert.equal(d.bucketOf(at(2027, 1, 1, 22), jan, 'en-US').key, 'yesterday');
  assert.deepEqual(d.bucketOf(at(2026, 12, 31, 8), jan, 'en-US'), { key: 'd2', label: 'Dec 31' });
  assert.deepEqual(d.bucketOf(at(2026, 12, 30, 8), jan, 'en-US'), { key: 'd3', label: 'Dec 30' });
  assert.equal(d.bucketOf(at(2026, 12, 26, 8), jan, 'en-US').key, 'week');
  assert.equal(d.bucketOf(at(2026, 12, 25, 8), jan, 'en-US').key, 'older');
});

const CHATS = [
  { id: 'a', title: 'beta', updated: at(2026, 11, 8, 9), created: at(2026, 10, 1) },
  { id: 'b', title: 'Alpha', updated: at(2026, 11, 8, 12), created: at(2026, 11, 8, 11) },
  { id: 'c', title: 'gamma', updated: at(2026, 11, 2), created: at(2026, 11, 2) },
  { id: 'e', title: 'epsilon', updated: at(2026, 11, 6, 8), created: at(2026, 11, 6) },
];

test('groupByDate: headings in order, empty ones left out; inside, the view\'s order', () => {
  const g = d.groupByDate(CHATS, { now: NOW, locale: 'en-US' });
  assert.deepEqual(g.map(x => [x.key, x.label, x.threads.map(t => t.id)]), [['today', 'Today', ['b', 'a']], ['d2', 'Nov 6', ['e']], ['week', 'Last week', ['c']]]);
  const byName = d.groupByDate(CHATS, { order: 'title', now: NOW });
  assert.deepEqual(byName[0].threads.map(t => t.title), ['Alpha', 'beta']);          // A to Z, the day still from updated
  const byCreated = d.groupByDate(CHATS, { order: 'created', now: NOW, locale: 'en-US' });
  assert.deepEqual(byCreated.map(x => [x.key, x.threads.map(t => t.id)]), [['today', ['b']], ['d2', ['e']], ['week', ['c']], ['older', ['a']]]);
  assert.deepEqual([d.dateField('created'), d.dateField('title'), d.dateField('updated')], ['created', 'updated', 'updated']);
  assert.deepEqual(d.groupByDate([], { now: NOW }), []);
});

test('shortDate: a time today, Yesterday, the date, the date with its year', () => {
  assert.equal(d.shortDate(at(2026, 11, 8, 14, 32), NOW, 'en-US'), '14:32');
  assert.equal(d.shortDate(at(2026, 11, 8, 0, 5), NOW, 'en-US'), '00:05');
  assert.equal(d.shortDate(at(2026, 11, 7, 23, 59), NOW, 'en-US'), 'Yesterday');
  assert.equal(d.shortDate(at(2026, 11, 5, 10), NOW, 'en-US'), 'Nov 5');
  assert.equal(d.shortDate(at(2026, 1, 2, 10), NOW, 'en-US'), 'Jan 2');
  assert.equal(d.shortDate(at(2025, 11, 5, 10), NOW, 'en-US'), 'Nov 5, 2025');
  assert.equal(d.shortDate(0, NOW), '');
});

test('DateSections: a plain heading per day, then its rows', () => {
  const el = d.DateSections({ threads: CHATS, view: { chatOrder: 'updated' }, now: NOW, renderItem: t => ({ type: 'li', props: { children: [t.title] } }) });
  const secs = el.props.children;
  assert.equal(secs.length, 3);
  assert.equal(secs[0].type, 'section');
  assert.equal(secs[0].props.children[0].type, 'h3');
  assert.equal(text(secs[0].props.children[0]), 'Today');
  assert.equal(secs[0].props.children[0].props.style.fontSize, 11.5);
  assert.equal(text(secs[0].props.children.slice(1)), 'Alpha|beta');
});
