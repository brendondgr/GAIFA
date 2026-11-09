// web/chat/chat-project.js and chat-project-panels.js (plan projects 5.2): the project page's pure parts: page ages, the
// freshness choices, the folders' order (the primary first), sizes, a new chat's preset and the delete confirm's words.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const panels = await load('chat/chat-project-panels.js');
const page = await load('chat/chat-project.js');

test('a page\'s age', () => {
  const now = 100000;
  assert.equal(panels.pageAge({ fetched: now - 10 }, now), 'fetched just now');
  assert.equal(panels.pageAge({ fetched: now - 600 }, now), 'fetched 10 min ago');
  assert.equal(panels.pageAge({ fetched: now - 7200 }, now), 'fetched 2 h ago');
  assert.equal(panels.pageAge({ fetched: now - 3 * 86400 }, now), 'fetched 3 d ago');
  assert.equal(panels.pageAge({ fetched: null }, now), 'never fetched');
  assert.equal(panels.pageAge({ fetched: now - 10, status: 'fetching' }, now), 'fetching…');
});

test('freshness choices', () => {
  assert.deepEqual(panels.FRESHNESS.map(f => f[0]), [900, 3600, 21600, 86400, 604800, null]);
  assert.equal(panels.freshLabel(3600), '1 h');
  assert.equal(panels.freshLabel(null), 'Never refresh automatically');
  assert.equal(panels.freshLabel(undefined), 'Never refresh automatically');
  assert.equal(panels.freshLabel(1800), '30 min');
});

test('folders: the primary first, moving one to the top or between', () => {
  assert.deepEqual(panels.moveEnv(['a', 'b', 'c'], 'c', 0), ['c', 'a', 'b']);
  assert.deepEqual(panels.moveEnv(['a', 'b', 'c'], 'a', 2), ['b', 'c', 'a']);
  assert.deepEqual(panels.moveEnv(['a', 'b'], 'x', 0), ['a', 'b']);
  const rows = panels.envRows(['grants', 'gone'], [{ id: 'grants', name: 'Grants', folders: [{}, {}] }]);
  assert.deepEqual(rows, [{ id: 'grants', name: 'Grants', folders: 2, primary: true, missing: false },
    { id: 'gone', name: 'gone', folders: 0, primary: false, missing: true }]);
  assert.equal(panels.envRows(['grants'], null)[0].missing, false, 'not said while the list is unknown');
});

test('sizes, a new chat\'s preset and the delete words', () => {
  assert.equal(panels.sizeWords(48200), '~12k tokens');
  assert.equal(panels.sizeWords(9100), '~2.3k tokens');
  assert.equal(panels.sizeWords(400), '~100 tokens');
  assert.deepEqual(page.newChatPreset({ id: 'p_1', environments: ['grants'], defaults: { model: 'm', mode: 'auto' } }),
    { model: 'm', mode: 'auto', settings: { project: 'p_1', environment: 'grants' } });
  assert.deepEqual(page.newChatPreset({ id: 'p_2', environments: [], defaults: {} }), { model: null, mode: 'manual', settings: { project: 'p_2' } });
  for (const w of ['chats stay', 'Memory', 'Outputs', 'instructions']) assert.ok(page.DELETE_BODY.includes(w), w);
});
