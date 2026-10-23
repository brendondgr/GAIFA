// web/chat/chat-save.js (plan 48.4): Download, Copy and Save to… on every output.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const save = await import(pathToFileURL(path.join(root, 'web/chat/chat-save.js')).href);
const acts = await import(pathToFileURL(path.join(root, 'web/chat/chat-actions.js')).href);

test('every kind gets the three; Save to… needs the workspace mod', () => {
  const tools = [{ name: 'workspace_write', available: true }];
  for (const k of save.KINDS) assert.deepEqual(acts.actionsFor(k, { tools, derive: false }).filter(a => /\.(download|copy|save)$/.test(a.id)).map(a => a.label), ['Download', 'Copy', 'Save to…']);
  assert.deepEqual(acts.actionsFor('image', { tools: [], derive: false }).filter(a => a.id === 'image.save'), []);
});

test('copy: pictures as pictures, the rest as links; a refusal in words', () => {
  assert.equal(save.copyKind({ kind: 'image' }), 'image');
  assert.equal(save.copyKind({ kind: 'audio' }), 'link');
  assert.equal(save.refusal({ data: { body: { detail: "x isn't one of this chat's folders", fix: 'add it at Edit' } } }), "x isn't one of this chat's folders — add it at Edit");
});

test('save to: picks a folder, then saves into it for this chat', async () => {
  const calls = [], toasts = [];
  const api = { callService: async (id, m, p, o) => { calls.push([id, m, p, o.json]); return p === '/v1/pick-folder' ? { json: { path: '/home/me/pics' } } : { json: { path: '/home/me/pics/fox.png' } }; } };
  await save.saveTo({ output_id: 'aaaaaaaaaaaa' }, { api, toast: (t, l) => toasts.push([t, l]), environment: 'env1', thread: 't1' });
  assert.deepEqual(calls[1], ['workspace', 'POST', '/v1/save-output', { output_id: 'aaaaaaaaaaaa', folder: '/home/me/pics', environment: 'env1', thread: 't1' }]);
  assert.deepEqual(toasts, [['Saved to /home/me/pics/fox.png', 'success']]);
  const cancelled = { callService: async () => ({ json: { cancelled: true } }) };
  calls.length = 0;
  await save.saveTo({ output_id: 'aaaaaaaaaaaa' }, { api: cancelled, toast: () => {} });
  assert.equal(calls.length, 0);
});
