// web/chat/chat-mods.js (plan 44.1): loading mods' chat modules.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const { loadChatModules, resetChatModules, CHAT_API_VERSION } = await import(pathToFileURL(path.join(root, 'web/chat/chat-mods.js')).href);

function registries() {
  const cards = new Map(), steps = new Map();
  return {
    cards, steps,
    chat: {
      registerCard: (k, C) => { cards.set(k, C); return () => cards.delete(k); },
      registerStep: (k, w) => { steps.set(k, w); return () => steps.delete(k); },
      registerPreview: () => () => {}, registerAction: () => () => {}, ui: {}, api: {}, live: null,
    },
  };
}
const quiet = async f => { const e = console.error; console.error = () => {}; try { return await f(); } finally { console.error = e; } };

test('a module registers a card and a step, once per page', async () => {
  resetChatModules();
  const { chat, cards, steps } = registries();
  let calls = 0, seen;
  const mods = { '/ui/services/a/chat.js': { default: c => { calls++; seen = c; c.registerCard('step:a_x', () => null); c.registerStep('a_x', { running: 'Doing' }); } } };
  const importer = u => Promise.resolve(mods[u.split('?')[0]]);
  const svc = [{ id: 'a', chat_url: '/ui/services/a/chat.js', version: '1.0' }, { id: 'b', chat_url: null }];
  const r = await loadChatModules(svc, chat, importer);
  assert.deepEqual(r, [{ mod: 'a', ok: true }]);
  assert.ok(cards.has('step:a_x') && steps.has('a_x'));
  assert.equal(seen.version, CHAT_API_VERSION);
  await loadChatModules(svc, chat, importer);
  assert.equal(calls, 1);
});

test('a module that throws is skipped and its registrations undone; a missing file too', async () => {
  resetChatModules();
  const { chat, cards } = registries();
  const importer = u => u.startsWith('/ui/services/bad/') ? Promise.resolve({ default: c => { c.registerCard('step:bad', () => null); throw new Error('boom'); } })
    : u.startsWith('/ui/services/nodef/') ? Promise.resolve({}) : Promise.reject(new Error('404'));
  const r = await quiet(() => loadChatModules([{ id: 'bad', chat_url: '/ui/services/bad/chat.js' }, { id: 'nodef', chat_url: '/ui/services/nodef/chat.js' },
    { id: 'gone', chat_url: '/ui/services/gone/chat.js' }], chat, importer));
  assert.deepEqual(r.map(x => [x.mod, x.ok]), [['bad', false], ['nodef', false], ['gone', false]]);
  assert.match(r[0].error, /boom/);
  assert.equal(cards.has('step:bad'), false);
});

test("the template's chat module registers its step and live card", async () => {
  resetChatModules();
  const { chat, cards, steps } = registries();
  chat.ui = { h: () => null }; chat.live = {};
  const url = pathToFileURL(path.join(root, 'services/_template/ui/chat.js')).href;
  const r = await loadChatModules([{ id: '_template', chat_url: url }], chat, u => import(u));
  assert.deepEqual(r, [{ mod: '_template', ok: true }]);
  assert.ok(steps.has('_template_hello') && cards.has('live:_template_hello'));
});
