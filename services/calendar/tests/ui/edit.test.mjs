// calendar 3.5–3.6: the editor's fields and body for each kind, the scope question; the proposal ticks; the
// shell's keys and quick add's preview.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const E = await load('cal-edit.js');
const F = await load('cal-files.js');
const S = await load('cal-shell.js');

test('an event: fields and the body a save sends', () => {
  const f = E.fieldsOf({ kind: 'event', title: 'Lunch', start: '2026-11-13T12:30', end: '2026-11-13T13:30', all_day: false, alerts: [{ before_min: 10 }], calendar_id: 'cal_1' });
  assert.deepEqual([f.date, f.time, f.endDate, f.endTime, f.alerts], ['2026-11-13', '12:30', '2026-11-13', '13:30', [10]]);
  f.repeat = { kind: 'weekly', days: [], end: { type: 'never' } };
  const b = E.bodyOf(f);
  assert.deepEqual([b.start, b.end, b.rrule, b.alerts, b.calendar], ['2026-11-13T12:30', '2026-11-13T13:30', 'FREQ=WEEKLY;BYDAY=FR', [10], 'cal_1']);
});

test('all day: the end date is the last day, sent exclusive', () => {
  const f = E.fieldsOf({ kind: 'event', title: 'Trip', start: '2026-12-20', end: '2026-12-28', all_day: true });
  assert.deepEqual([f.date, f.endDate, f.all_day], ['2026-12-20', '2026-12-27', true]);
  const b = E.bodyOf(f);
  assert.deepEqual([b.start, b.end], ['2026-12-20', '2026-12-28']);
});

test('a to-do: due date or time, priority, estimate', () => {
  const f = E.fieldsOf(null, { kind: 'todo', start: '2026-11-13', all_day: true });
  f.title = 'Rent'; f.priority = '3'; f.estimate = '45';
  assert.deepEqual(E.bodyOf(f), { kind: 'todo', title: 'Rent', due: '2026-11-13', priority: 3, estimate_min: 45, rrule: null, alerts: [], notes: '', url: '', project_id: null });
  f.all_day = false; f.time = '17:00';
  assert.equal(E.bodyOf(f).due, '2026-11-13T17:00');
});

test('the scope question only for an occurrence of a repeating item', () => {
  assert.equal(E.asksScope({ rrule: 'FREQ=DAILY' }, '2026-11-13T09:00'), true);
  assert.equal(E.asksScope({ rrule: null }, '2026-11-13T09:00'), false);
  assert.equal(E.asksScope({ rrule: 'FREQ=DAILY' }, null), false);
});

test('proposal ticks', () => {
  const p = { items: [{ pid: '1' }, { pid: '2', already: true }, { pid: '3', problem: { detail: 'x' } }, { pid: '4' }] };
  assert.deepEqual([...F.initialTicks(p)], ['1', '4']);
  assert.equal(F.addLabel(2), 'Add 2');
  assert.equal(F.addLabel(0), 'Nothing ticked');
});

test('keys', () => {
  const k = (key, tagName = 'BODY', o = {}) => S.keyAction({ key, target: { tagName }, ...o });
  assert.deepEqual(k('w'), { kind: 'view', view: 'week' });
  assert.deepEqual(k('t'), { kind: 'today' });
  assert.deepEqual(k('j'), { kind: 'step', n: -1 });
  assert.deepEqual(k('n'), { kind: 'new' });
  assert.deepEqual(k('/'), { kind: 'search' });
  assert.equal(k('w', 'INPUT'), null);
  assert.deepEqual(k('Escape', 'INPUT'), { kind: 'escape' });
  assert.equal(k('w', 'BODY', { ctrlKey: true }), null);
});

test('quick add preview', () => {
  assert.equal(S.previewText({ kind: 'event', title: 'Lunch', start: '2026-11-13T13:00', end: '2026-11-13T14:30', all_day: false }), 'Event · Lunch · Fri Nov 13 · 13:00–14:30');
  assert.equal(S.previewText({ kind: 'todo', title: 'Call', due: '2026-11-10T10:00' }), 'To-do · Call · Due 10:00 · Tue Nov 10');
  assert.match(S.previewText({ kind: 'event', title: 'Sync', start: '2026-11-10T09:00', end: '2026-11-10T10:00', repeat: 'Weekly on Tue' }), /Weekly on Tue$/);
});
