// settings-that-stick 3.2: web/ui-prefs.js: the hub's ui settings win over this browser's copy, the copy paints first,
// a change saves with its base, a reload doesn't undo a change still saving, and a failed save keeps the value.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { createUiPrefs, CACHE_KEY } = await import('../../../web/ui-prefs.js');
const store = (init = {}) => { const m = new Map(Object.entries(init)); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };
const CHAT = { steps: 'fold', list: { group: 'environment' }, environment: null };

test('the hub’s ui.chat.steps is used with an empty localStorage', async () => {
  const prefs = createUiPrefs({ storage: null });
  await prefs.load({ getSettings: async () => ({ ui: { chat: { steps: 'split' } } }) });
  assert.equal(prefs.get('chat.steps', 'fold'), 'split');
});

test('the copy paints first, then the hub wins and the copy follows', async () => {
  const s = store({ [CACHE_KEY]: JSON.stringify({ chat: { steps: 'split' } }) });
  const prefs = createUiPrefs({ storage: s });
  assert.equal(prefs.get('chat.steps', 'fold'), 'split');
  let heard = 0; prefs.subscribe(() => heard++);
  await prefs.load({ getSettings: async () => ({ ui: { chat: CHAT } }) });
  assert.equal(prefs.get('chat.steps', 'fold'), 'fold'); assert.equal(heard, 1);
  assert.equal(JSON.parse(s.m.get(CACHE_KEY)).chat.steps, 'fold');
});

test('set shows at once and saves the table with its base', async () => {
  const calls = [];
  const api = { getSettings: async () => ({ ui: { chat: CHAT } }), saveSettings: async (body, opts) => { calls.push([body, opts]); return { settings: { ui: { chat: { ...CHAT, ...body.ui.chat } } } }; } };
  const prefs = createUiPrefs({ storage: store() });
  await prefs.load(api);
  const p = prefs.set('chat.steps', 'split');
  assert.equal(prefs.get('chat.steps'), 'split');
  await p;
  assert.deepEqual(calls, [[{ ui: { chat: { ...CHAT, steps: 'split' } } }, { base: { ui: { chat: CHAT } } }]]);
});

test('a reload during a save keeps the change; a failed save keeps it and reports', async () => {
  let release;
  const api = { getSettings: async () => ({ ui: { chat: CHAT } }), saveSettings: () => new Promise((res, rej) => { release = [res, rej]; }) };
  const prefs = createUiPrefs({ storage: store() });
  await prefs.load(api);
  const errs = []; prefs.onError = (e, path) => errs.push([e.message, path]);
  const p = prefs.set('chat.steps', 'split');
  prefs.apply({ ui: { chat: CHAT, overview: { view: 'table' } } });   // another tab's save arrives first
  assert.equal(prefs.get('chat.steps'), 'split'); assert.equal(prefs.get('overview.view'), 'table');
  release[1](new Error('down')); await p;
  assert.equal(prefs.get('chat.steps'), 'split'); assert.deepEqual(errs, [['down', 'chat.steps']]);
});
