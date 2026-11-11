// calendar 2.3, 3.5: alerts and snoozing (cal-remind.js): the words for an amount and an alert (timed and all-day),
// a typed amount and its limits, adding an alert, and a snoozed reminder's "until".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const R = await load('cal-remind.js');

test('amounts and alerts in words', () => {
  assert.deepEqual([5, 45, 60, 90, 120, 1440, 2880, 10080, 20160].map(R.amount),
    ['5 min', '45 min', '1 hour', '90 min', '2 hours', '1 day', '2 days', '1 week', '2 weeks']);
  assert.equal(R.alertLabel(0), 'When it starts');
  assert.equal(R.alertLabel(0, { kind: 'todo' }), 'At the time');
  assert.equal(R.alertLabel(30), '30 min before');
  assert.equal(R.alertLabel(2880), '2 days before');
  // all-day: whole days before at the settings' time; a few minutes is the day before
  assert.equal(R.alertLabel(0, { allDay: true, at: '09:00' }), 'On the day at 09:00');
  assert.equal(R.alertLabel(10, { allDay: true, at: '09:00' }), '1 day before at 09:00');
  assert.equal(R.alertLabel(4320, { allDay: true }), '3 days before');
  assert.equal(R.alertLabel(10080, { allDay: true }), '1 week before');
});

test('a typed amount', () => {
  assert.deepEqual(R.minutesOf('45', 'min', R.MAX_ALERT), { minutes: 45 });
  assert.deepEqual(R.minutesOf('3', 'h', R.MAX_ALERT), { minutes: 180 });
  assert.deepEqual(R.minutesOf('2', 'd', R.MAX_ALERT), { minutes: 2880 });
  assert.deepEqual(R.minutesOf('1.5', 'h', R.MAX_ALERT), { minutes: 90 });       // whole minutes are fine
  assert.ok(R.minutesOf('0', 'min', R.MAX_ALERT).error);
  assert.ok(R.minutesOf('', 'min', R.MAX_ALERT).error);
  assert.ok(R.minutesOf('1.5', 'min', R.MAX_ALERT).error);
  assert.match(R.minutesOf('5', 'w', R.MAX_ALERT).error, /4 weeks/);
  assert.deepEqual(R.minutesOf('30', 'd', R.MAX_SNOOZE), { minutes: 43200 });
});

test('adding an alert: sorted, none twice, at most eight', () => {
  assert.deepEqual(R.withAlert([60, 10], 1440), [10, 60, 1440]);
  assert.deepEqual(R.withAlert([10], 10), [10]);
  const full = [0, 5, 10, 15, 30, 60, 120, 1440];
  assert.deepEqual(R.withAlert(full, 2880), full);
});

test('a snoozed reminder says until when', () => {
  const now = new Date(2026, 10, 13, 12, 0), at = (d, h, m = 0) => new Date(2026, 10, d, h, m).getTime() / 1000;
  assert.equal(R.untilWords(at(13, 14, 30), now), 'until 14:30');
  assert.equal(R.untilWords(at(14, 9), now), 'until tomorrow 09:00');
  assert.equal(R.untilWords(at(16, 9), now), 'until Mon Nov 16 09:00');
});
