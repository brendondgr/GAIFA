// calendar 3.3: overlaps share the width, a minimum height, events across midnight, the all-day row, snapping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const L = await load('cal-layout.js');
const ts = (d, h, m = 0) => new Date(2026, 10, d, h, m).getTime() / 1000;
const ev = (id, d, h1, m1, h2, m2, o = {}) => ({ id, kind: 'event', all_day: false, ts: ts(d, h1, m1), end_ts: ts(d, h2, m2), ...o });
const day = new Date(2026, 10, 10);

test('overlaps: two, three, and a chain', () => {
  const two = L.layoutDay([ev('a', 10, 9, 0, 10, 0), ev('b', 10, 9, 30, 10, 30)], day);
  assert.deepEqual(two.map(b => [b.occ.id, b.col, b.cols]), [['a', 0, 2], ['b', 1, 2]]);
  const three = L.layoutDay([ev('a', 10, 9, 0, 11, 0), ev('b', 10, 9, 0, 10, 0), ev('c', 10, 9, 30, 10, 30)], day);
  assert.deepEqual(three.map(b => b.cols), [3, 3, 3]);
  const chain = L.layoutDay([ev('a', 10, 9, 0, 10, 0), ev('b', 10, 9, 30, 11, 0), ev('c', 10, 10, 0, 11, 30)], day);
  assert.deepEqual(chain.map(b => [b.occ.id, b.col]), [['a', 0], ['b', 1], ['c', 0]]);
  const apart = L.layoutDay([ev('a', 10, 9, 0, 10, 0), ev('b', 10, 10, 0, 11, 0)], day);
  assert.deepEqual(apart.map(b => b.cols), [1, 1]);
});

test('positions, the minimum height, other days and midnight', () => {
  const [b] = L.layoutDay([ev('a', 10, 13, 0, 13, 5)], day);
  assert.equal(b.top, 13 * L.HOUR_PX);
  assert.equal(b.height, L.MIN_PX);
  assert.deepEqual(L.layoutDay([ev('x', 9, 13, 0, 14, 0), ev('y', 11, 9, 0, 10, 0)], day), []);
  const late = { id: 'n', kind: 'event', all_day: false, ts: ts(9, 23, 0), end_ts: ts(10, 1, 0) };
  const [m] = L.layoutDay([late], day);
  assert.equal(m.top, 0);
  assert.equal(m.height, L.HOUR_PX);
});

test('the all-day row: bars, rows and overflow', () => {
  const days = Array.from({ length: 7 }, (_, i) => new Date(2026, 10, 9 + i));
  const ad = (id, s, e) => ({ id, kind: 'event', all_day: true, start: s, end: e, title: id });
  const r = L.layoutAllDay([ad('conf', '2026-11-11', '2026-11-14'), ad('a', '2026-11-11', '2026-11-12'), ad('b', '2026-11-11', '2026-11-12'),
    ad('c', '2026-11-11', '2026-11-12'), ad('early', '2026-11-01', '2026-11-10')], days, 3);
  assert.deepEqual(r.bars.find(b => b.occ.id === 'conf'), { occ: r.bars.find(b => b.occ.id === 'conf').occ, start: 2, span: 3, row: 0 });
  assert.equal(r.bars.find(b => b.occ.id === 'early').start, 0);
  assert.equal(r.more[2], 1);
  assert.equal(r.rows, 3);
});

test('snapping a drag to 15 minutes', () => {
  assert.equal(L.minutesAt(9 * L.HOUR_PX + 10), 9 * 60 + 15);
  assert.equal(L.minutesAt(9 * L.HOUR_PX + 5), 9 * 60);
  assert.equal(L.minutesAt(-30), 0);
  assert.equal(L.minutesAt(30 * L.HOUR_PX), 24 * 60);
});
