// settings-that-stick 2.2: every writer sends `base`, and the mock merges a save with what is saved now as the hub does
// (web/settings-merge.js, utils/settings_merge.py); "Always allow" sends the list it added to.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const si = globalThis.setInterval;                 // the mock's 1 s ticker must not keep the test process alive
globalThis.setInterval = (...a) => { const t = si(...a); t.unref?.(); return t; };
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
globalThis.React = { Fragment: Symbol('Fragment'), createElement: () => null, useState: i => [typeof i === 'function' ? i() : i, () => {}], useRef: v => ({ current: v }), useEffect: () => {} };
const { mergeValue, rebase, baseOf, Conflict } = await load('settings-merge.js');
const { createApi } = await load('api.js');
const { createMockApi } = await load('mock.js');
const { allowRule } = await load('chat/chat-judge.js');

test('lists, tables and plain values merge as the hub merges them', () => {
  assert.equal(mergeValue('x', 1, 1, 2), 2);
  assert.equal(mergeValue('x', 3, 1, 1), 3);
  assert.throws(() => mergeValue('judge.threshold', 0.4, 0.35, 0.5), e => e instanceof Conflict && e.field === 'judge.threshold' && e.current === 0.4);
  assert.deepEqual(mergeValue('l', ['a', 'c', 'd'], ['a', 'd'], ['d', 'b']), ['c', 'd', 'b']);
  assert.deepEqual(mergeValue('o', ['a', 'b', 'c'], ['a', 'b', 'c'], ['c', 'a', 'b']), ['c', 'a', 'b']);
  assert.deepEqual(mergeValue('t', { a: true, b: true, n: { x: 1, y: 1 } }, { a: true, b: false, n: { x: 1, y: 0 } }, { a: false, b: false, n: { x: 2, y: 0 } }),
    { a: false, b: true, n: { x: 2, y: 1 } });
  assert.deepEqual(rebase({ judge: { allow_commands: ['a', 'c'] } }, { judge: { allow_commands: ['a', 'b'], threshold: 0.5 } }, { judge: { allow_commands: ['a'] } }),
    { judge: { allow_commands: ['a', 'c', 'b'], threshold: 0.5 } });
});

test('baseOf takes each sent key from what was loaded', () => {
  const loaded = { judge: { allow_commands: ['a'], threshold: 0.35 }, ui: { theme: 'dark' } };
  assert.deepEqual(baseOf({ judge: { allow_commands: ['a', 'b'] } }, loaded), { judge: { allow_commands: ['a'] } });
  assert.deepEqual(baseOf({ nope: { x: 1 } }, loaded), {});
});

test('Always allow sends the list it added to as base', () => {
  assert.deepEqual(allowRule(['git status'], 'ls'), [{ judge: { allow_commands: ['git status', 'ls'] } }, { base: { judge: { allow_commands: ['git status'] } } }]);
  assert.deepEqual(allowRule(['ls'], 'ls')[0].judge.allow_commands, ['ls']);
});

test('api.saveSettings puts base in the body', async () => {
  const calls = [];
  const fetch = async (url, init) => { calls.push({ url, ...init }); return new Response(JSON.stringify({ settings: {}, restart_required: false }), { status: 200, headers: { 'content-type': 'application/json' } }); };
  const api = createApi({ base: '', liveAreas: ['settings'], mock: {}, fetch, EventSource: class {} });
  await api.saveSettings({ judge: { allow_commands: ['a', 'b'] } }, { base: { judge: { allow_commands: ['a'] } } });
  await api.saveSettings({ ui: { theme: 'dark' } });
  assert.deepEqual(JSON.parse(calls[0].body), { judge: { allow_commands: ['a', 'b'] }, base: { judge: { allow_commands: ['a'] } } });
  assert.deepEqual(JSON.parse(calls[1].body), { ui: { theme: 'dark' } });
});

test('the mock keeps a rule added elsewhere and refuses a value changed on both sides', async () => {
  const api = createMockApi();
  const s0 = await api.getSettings();
  await api.saveSettings(...allowRule(s0.judge.allow_commands, 'ls'));                    // a chat adds a rule
  const r = await api.saveSettings({ judge: { allow_commands: [...s0.judge.allow_commands, 'pytest *'] } }, { base: baseOf({ judge: { allow_commands: 0 } }, s0) });
  assert.deepEqual(r.settings.judge.allow_commands, [...s0.judge.allow_commands, 'ls', 'pytest *']);
  await api.saveSettings({ judge: { threshold: 0.4 } });
  await assert.rejects(api.saveSettings({ judge: { threshold: 0.5 } }, { base: { judge: { threshold: s0.judge.threshold } } }),
    e => e.status === 409 && e.code === 'settings_conflict' && e.data.field === 'judge.threshold');
});
