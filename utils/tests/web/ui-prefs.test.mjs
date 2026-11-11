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

test('this browser’s old choices are saved once, unless config.toml already sets them', async () => {
  const { browserChoices, importBrowser, IMPORTED_KEY } = await import('../../../web/ui-prefs.js');
  const s = store({ 'gaifa.chat.steps': '"split"', 'gaifa.chat.environment': '"work"', 'gaifa.chat.list': JSON.stringify({ group: 'none', envOrder: 'activity', chatOrder: 'title', collapsed: [] }),
    'hub.ovView': 'timeline', 'hub.tlRange': '7d', 'hub.svcRange': '24h', 'hub.theme': 'dark', 'hub.density': 'compact' });
  const fresh = { theme: 'system', density: 'compact', chat: { steps: 'fold', list: { group: 'environment', env_order: 'activity', chat_order: 'updated', collapsed: [] }, environment: null },
    overview: { view: 'dashboard', timeline_range: '24h', services_range: '24h' } };
  assert.deepEqual(browserChoices(fresh, s), { chat: { steps: 'split', environment: 'work', list: { group: 'none', chat_order: 'title' } },
    overview: { view: 'timeline', timeline_range: '7d' }, theme: 'dark' });
  // what config.toml sets wins: nothing from the browser for it
  assert.deepEqual(browserChoices({ ...fresh, theme: 'light', chat: { ...fresh.chat, steps: 'fold', environment: 'home' } }, store({ 'hub.theme': 'dark', 'gaifa.chat.environment': '"work"' })), {});
  // the name before GAIFA counts
  assert.deepEqual(browserChoices(fresh, store({ 'aihub.chat.steps': '"split"' })), { chat: { steps: 'split' } });
  // the Services view is gone (overview-bento 3.1): a browser that chose it saves nothing
  assert.deepEqual(browserChoices(fresh, store({ 'hub.ovView': 'services' })), {});
  const calls = [];
  const api = { saveSettings: async b => { calls.push(b); return { settings: { ui: fresh } }; } };
  assert.deepEqual(await importBrowser(api, { ui: fresh }, s), browserChoices(fresh, s));
  assert.equal(s.m.get(IMPORTED_KEY), '1'); assert.equal(calls.length, 1);
  assert.equal(await importBrowser(api, { ui: fresh }, s), null); assert.equal(calls.length, 1);   // once
});
