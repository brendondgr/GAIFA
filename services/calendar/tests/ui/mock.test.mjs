// calendar 3.2: the page's mock answers like the mod (a week around today, writes with undo).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const { createMockClient } = await load('cal-mock.js');

test('the mock: a range, a write and its undo', async () => {
  const now = new Date(2026, 10, 11, 10), c = createMockClient(now);
  const from = new Date(2026, 10, 9), to = new Date(2026, 10, 16);
  const r = await c.range(from.toISOString(), to.toISOString());
  assert.ok(r.occurrences.filter(o => o.title === 'Standup').length === 5);
  assert.ok(r.occurrences.some(o => o.all_day && o.title === 'Conference'));
  const a = await c.add({ title: 'New', start: '2026-11-12T10:00', end: '2026-11-12T11:00' });
  assert.ok((await c.range(from.toISOString(), to.toISOString())).occurrences.some(o => o.title === 'New'));
  await c.undo(a.undo);
  assert.ok(!(await c.range(from.toISOString(), to.toISOString())).occurrences.some(o => o.title === 'New'));
  assert.equal((await c.calendars()).length, 2);
});
