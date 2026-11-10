// calendar 3.2: the range and title of each view, steps, the week's first day.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const D = await load('cal-dates.js');
const day = new Date(2026, 10, 13, 15, 30);          // Fri Nov 13 2026

test('ranges', () => {
  assert.deepEqual(D.rangeOf('week', day).days.map(D.ymd), ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15']);
  assert.equal(D.ymd(D.rangeOf('week', day, 6).from), '2026-11-08');
  assert.equal(D.rangeOf('day', day).days.length, 1);
  const m = D.rangeOf('month', day);
  assert.equal(D.ymd(m.from), '2026-10-26');
  assert.equal(D.ymd(m.to), '2026-12-07');
  assert.equal(m.days.length % 7, 0);
  assert.equal(D.rangeOf('agenda', day).days.length, 30);
});

test('titles', () => {
  assert.equal(D.titleOf('day', day), 'Friday, November 13, 2026');
  assert.equal(D.titleOf('week', day), 'Nov 9 – 15, 2026');
  assert.equal(D.titleOf('week', new Date(2026, 11, 2)), 'Nov 30 – Dec 6, 2026');
  assert.equal(D.titleOf('week', new Date(2026, 11, 30)), 'Dec 28, 2026 – Jan 3, 2027');
  assert.equal(D.titleOf('month', day), 'November 2026');
});

test('steps and words', () => {
  assert.equal(D.ymd(D.step('week', day, 1)), '2026-11-20');
  assert.equal(D.ymd(D.step('month', new Date(2026, 0, 31), 1)), '2026-02-28');
  assert.equal(D.ymd(D.step('day', day, -1)), '2026-11-12');
  assert.equal(D.timeText({ kind: 'event', all_day: false, start: '2026-11-13T13:00', end: '2026-11-13T14:30' }), '13:00–14:30');
  assert.equal(D.timeText({ kind: 'event', all_day: true, start: '2026-11-13', end: '2026-11-14' }), 'All day');
  assert.equal(D.timeText({ kind: 'event', all_day: true, start: '2026-11-12', end: '2026-11-14' }), 'Nov 12–13');
  assert.equal(D.timeText({ kind: 'todo', all_day: false, due: '2026-11-13T17:00' }), 'Due 17:00');
  assert.equal(D.snap(52), 45);
});
