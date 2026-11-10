// calendar 3.4: a month's weeks for each week start, multi-day bars across a week break, +N more; the agenda.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const D = await load('cal-dates.js');
const L = await load('cal-layout.js');

test('weeks of a month', () => {
  for (const ws of [0, 6]) {
    const weeks = L.weeksOf(D.rangeOf('month', new Date(2026, 1, 10), ws).days);
    assert.ok(weeks.every(w => w.length === 7));
    assert.equal(D.dow(weeks[0][0]), ws);
    assert.ok(weeks.flat().some(d => d.getMonth() === 1 && d.getDate() === 28));
  }
});

test('a multi-day bar across a week break', () => {
  const days = D.rangeOf('month', new Date(2026, 10, 10)).days, weeks = L.weeksOf(days);
  const trip = { id: 't', kind: 'event', all_day: true, start: '2026-11-14', end: '2026-11-18', title: 'Trip' };
  const w2 = L.layoutAllDay([trip], weeks[2]), w3 = L.layoutAllDay([trip], weeks[3]);
  assert.deepEqual([w2.bars[0].start, w2.bars[0].span], [5, 2]);
  assert.deepEqual([w3.bars[0].start, w3.bars[0].span], [0, 2]);
});

test('three a day, then +N more', () => {
  const day = new Date(2026, 10, 10), occs = [9, 10, 11, 12, 13].map(h => ({ kind: 'event', all_day: false, ts: new Date(2026, 10, 10, h).getTime() / 1000, title: String(h) }));
  assert.deepEqual(L.dayItems(occs, day, 0, 3).more, 2);
  assert.deepEqual(L.dayItems(occs, day, 2, 3).shown.map(o => o.title), ['9']);
});

test('the agenda groups by day and leaves empty days out', () => {
  const at = (d, h) => ({ kind: 'event', all_day: false, ts: new Date(2026, 10, d, h).getTime() / 1000 });
  const g = L.agendaGroups([at(10, 9), at(10, 8), at(12, 9), { kind: 'event', all_day: true, start: '2026-11-11', end: '2026-11-13' }], new Date(2026, 10, 10), new Date(2026, 10, 14));
  assert.deepEqual(g.map(x => [x.day.getDate(), x.items.length]), [[10, 2], [11, 1], [12, 2]]);
  assert.equal(g[0].items[0].ts < g[0].items[1].ts, true);
});
