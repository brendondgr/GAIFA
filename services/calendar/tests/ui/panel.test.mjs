// calendar 7.2: the Chat panel: where the day column starts, a mention's words, the week's days.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const P = await load('panel.js');
const at = (d, h, m = 0) => new Date(2026, 10, d, h, m).getTime() / 1000;

test('the day column starts at the first item or 8', () => {
  assert.equal(P.firstHour([]), 8);
  assert.equal(P.firstHour([{ kind: 'event', all_day: false, ts: at(10, 6, 30) }]), 6);
  assert.equal(P.firstHour([{ kind: 'event', all_day: false, ts: at(10, 13) }]), 8);
});

test('mention words and the week', () => {
  assert.equal(P.mentionText({ title: 'Design review', item_id: 'c_1', ts: at(10, 13), all_day: false }), '“Design review” (calendar item c_1, Tue Nov 10 13:00)');
  const days = P.weekDays([{ kind: 'event', all_day: false, ts: at(10, 9), title: 'A' }, { kind: 'event', all_day: true, start: '2026-11-11', end: '2026-11-13', ts: at(11, 0), title: 'Trip' }], new Date(2026, 10, 10));
  assert.deepEqual(days.map(d => d.items.map(o => o.title).join(',')), ['', 'A', 'Trip', 'Trip', '', '', '']);
});
