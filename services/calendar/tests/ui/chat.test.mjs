// calendar 4.4: the chat module: a card per tool, the result read from a turn's row, an item's line, Open's link.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const M = await load('chat.js');

test("setup registers each tool's step words and cards", () => {
  const cards = [], steps = [];
  globalThis.React = { useRef: () => ({}), useState: v => [v, () => {}], useEffect: () => {} };
  M.default({ ui: { h: (...a) => a, T: {} }, live: { LiveCard: 'LiveCard' }, api: {}, registerCard: k => cards.push(k), registerStep: k => steps.push(k) });
  assert.equal(steps.length, 10);
  assert.deepEqual(cards.sort(), ['live:calendar_add', 'live:calendar_agenda', 'live:calendar_delete', 'live:calendar_done', 'live:calendar_free',
    'live:calendar_plan_day', 'live:calendar_propose', 'live:calendar_update']);
});

test('the result, from an object or JSON text', () => {
  const ctx = r => ({ liveCard: { row: { item: { result: r } } } });
  assert.deepEqual(M.resultOf(ctx({ result: { item: { id: 'c_1' } } })), { item: { id: 'c_1' } });
  assert.deepEqual(M.resultOf(ctx({ content: '{"result": {"slots": []}}' })), { slots: [] });
  assert.deepEqual(M.resultOf(ctx({ content: '{"items": [1]}' })), { items: [1] });
  assert.equal(M.resultOf(ctx({ content: 'oops' })), null);
});

test('an item line and Open in Calendar', () => {
  const it = { id: 'c_1', kind: 'event', title: 'Lunch', start: '2026-11-13T13:00', end: '2026-11-13T14:30', all_day: false, repeat: 'Weekly on Fri', calendar: 'Personal' };
  assert.equal(M.itemLine(it), 'Fri, Nov 13 · 13:00–14:30 · Weekly on Fri · Personal');
  assert.equal(M.openHref(it), '#/calendar?item=c_1%402026-11-13T13%3A00');
  assert.equal(M.itemLine({ kind: 'todo', title: 'Rent', due: '2026-11-30', all_day: true }), 'Mon, Nov 30 · Due');
});
