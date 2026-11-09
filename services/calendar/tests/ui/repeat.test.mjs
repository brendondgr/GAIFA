// calendar 3.5: the repeat picker's rule for each choice, and its words back (the same as repeat.py).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const R = await load('cal-repeat.js');
const tue = '2026-11-10T09:00';

test('choices to rules', () => {
  const r = c => R.ruleOf({ interval: 1, end: { type: 'never' }, ...c }, tue);
  assert.equal(r({ kind: 'none' }), null);
  assert.equal(r({ kind: 'daily' }), 'FREQ=DAILY');
  assert.equal(r({ kind: 'weekdays' }), 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR');
  assert.equal(r({ kind: 'weekly' }), 'FREQ=WEEKLY;BYDAY=TU');
  assert.equal(r({ kind: 'weekly', days: ['TH', 'MO'] }), 'FREQ=WEEKLY;BYDAY=MO,TH');
  assert.equal(r({ kind: 'monthly' }), 'FREQ=MONTHLY;BYMONTHDAY=10');
  assert.equal(r({ kind: 'monthly_last' }), 'FREQ=MONTHLY;BYMONTHDAY=-1');
  assert.equal(r({ kind: 'yearly', end: { type: 'count', count: 5 } }), 'FREQ=YEARLY;COUNT=5');
  assert.equal(r({ kind: 'custom', unit: 'day', interval: 3, end: { type: 'until', until: '2026-12-01' } }), 'FREQ=DAILY;INTERVAL=3;UNTIL=20261201T235959');
});

test('rules back to choices', () => {
  for (const kind of ['daily', 'weekdays', 'weekly', 'monthly', 'monthly_last', 'yearly']) {
    const rule = R.ruleOf({ kind, interval: 1, end: { type: 'never' } }, tue);
    assert.equal(R.choiceOf(rule).kind, kind);
  }
  const c = R.choiceOf('FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;COUNT=4');
  assert.deepEqual([c.kind, c.unit, c.interval, c.days, c.end], ['custom', 'week', 2, ['FR'], { type: 'count', count: 4 }]);
});

test('words', () => {
  assert.equal(R.words('FREQ=WEEKLY;BYDAY=TU,TH'), 'Weekly on Tue, Thu');
  assert.equal(R.words('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'), 'Every weekday');
  assert.equal(R.words('FREQ=DAILY;INTERVAL=2;COUNT=5'), 'Every 2 days, 5 times');
  assert.equal(R.words('FREQ=MONTHLY;BYMONTHDAY=-1'), 'Monthly on the last day');
  assert.equal(R.words('FREQ=YEARLY;UNTIL=20271201'), 'Yearly until Dec 1, 2027');
  assert.equal(R.words(null), "Doesn't repeat");
});
