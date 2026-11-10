// calendar 5.3: a project's Dates panel: the range it asks the calendar for, and each item's words.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = globalThis.React || { createElement: (...a) => a };
const D = await import(pathToFileURL(path.join(root, 'web/chat/chat-project-dates.js')).href);

test('fourteen days from local midnight', () => {
  const r = D.datesRange(new Date(2026, 10, 9, 15, 30));
  assert.equal(new Date(r.from).getTime(), new Date(2026, 10, 9).getTime());
  assert.equal(new Date(r.to).getTime(), new Date(2026, 10, 23).getTime());
});

test('an item in words', () => {
  assert.equal(D.dateWords({ kind: 'event', start: '2026-11-10T13:00', all_day: false }), 'Tue 10 Nov · 13:00');
  assert.equal(D.dateWords({ kind: 'event', start: '2026-11-12', all_day: true }), 'Thu 12 Nov · all day');
  assert.equal(D.dateWords({ kind: 'todo', due: '2026-11-20', all_day: true }), 'due Fri 20 Nov');
  assert.equal(D.dateWords({ kind: 'todo', due: '2026-11-20T17:00', all_day: false }), 'due Fri 20 Nov 17:00');
});
