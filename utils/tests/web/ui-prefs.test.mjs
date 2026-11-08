// settings-that-stick 1.2 / 3.2: a preference the hub has wins, even when this browser holds nothing.
import { test } from 'node:test';
import assert from 'node:assert/strict';

test('the hub’s ui.chat.steps is used with an empty localStorage', { todo: 'settings-that-stick 3.2' }, async () => {
  const m = await import('../../../web/ui-prefs.js');
  const prefs = m.createUiPrefs({ storage: null });
  await prefs.load({ getSettings: async () => ({ ui: { chat: { steps: 'split' } } }) });
  assert.equal(prefs.get('chat.steps', 'fold'), 'split');
});
