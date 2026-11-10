// calendar 7.1: side panels in Chat: which services offer one, the kept state, a toggle, the width's limits, and
// words put into the composer.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = globalThis.React || { createElement: (...a) => a };
const P = await import(pathToFileURL(path.join(root, 'web/chat/chat-panel.js')).href);

test('panels of running mods with one', () => {
  const svcs = [{ id: 'calendar', state: 'ready', chat_panel: { label: 'Calendar', url: '/ui/services/calendar/panel.js' }, logo_url: '/l.svg' },
    { id: 'web', state: 'ready' }, { id: 'other', state: 'stopped', chat_panel: { label: 'O', url: '/x.js' } }];
  assert.deepEqual(P.panelsOf(svcs).map(p => [p.id, p.label, p.url]), [['calendar', 'Calendar', '/ui/services/calendar/panel.js']]);
  assert.deepEqual(P.panelsOf(null), []);
});

test('the kept state, a toggle and the width', () => {
  assert.deepEqual(P.panelState(null), { open: null, width: P.DEF_W });
  assert.deepEqual(P.panelState({ open: 'calendar', width: 9999 }), { open: 'calendar', width: P.MAX_W });
  assert.equal(P.clampWidth(100), P.MIN_W);
  const st = { open: null, width: 300 };
  assert.equal(P.toggled(st, 'calendar').open, 'calendar');
  assert.equal(P.toggled(P.toggled(st, 'calendar'), 'calendar').open, null);
});

test('words into the composer', () => {
  const ta = { value: 'what about', dispatched: 0, focused: false, dispatchEvent() { this.dispatched++; }, focus() { this.focused = true; } };
  const doc = { querySelectorAll: () => [ta] };
  assert.equal(P.insertInto('“Review” (calendar item c_1)', doc), true);
  assert.equal(ta.value, 'what about “Review” (calendar item c_1) ');
  assert.ok(ta.dispatched && ta.focused);
  assert.equal(P.insertInto('x', { querySelectorAll: () => [] }), false);
});
