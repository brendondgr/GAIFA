// web/live-kit.js (plan 44.3) and web/chat/chat-live.js: the pure parts of live cards.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const kit = await load('live-kit.js');
const cards = await load('chat/chat-cards.js');
const chatLive = await load('chat/chat-live.js');

test('time left', () => {
  assert.equal(kit.fmtLeft(6.2), '7 s left');
  assert.equal(kit.fmtLeft(65), '1:05 left');
  assert.equal(kit.fmtLeft(null), null);
  assert.equal(kit.fmtLeft(-1), null);
});

test('what the box says before frames: the GPU queue first, then queued or loading', () => {
  assert.deepEqual(kit.waitInfo({ stage: 'loading' }, 'Waiting for the GPU: 3D Generate fox, about 20 s left'),
    { title: 'Waiting for the GPU', sub: '3D Generate fox, about 20 s left' });
  assert.deepEqual(kit.waitInfo({ stage: 'loading', eta_s: 4 }, null, { model: 'Qwen-Image' }), { title: 'Loading Qwen-Image', sub: '4 s left' });
  assert.deepEqual(kit.waitInfo({ stage: 'queued' }), { title: 'Queued', sub: null });
  assert.equal(kit.waitInfo({ stage: 'sampling', preview: { url: '/x', seq: 1 } }), null);
  assert.deepEqual(kit.waitInfo(null), { title: 'Starting', sub: null });
});

test('step words, meta and chips', () => {
  assert.equal(kit.stepLabel({ step: 3, steps: 8 }), 'Step 3 of 8');
  assert.equal(kit.stepLabel({ stage: 'decoding' }), 'Decoding');
  assert.equal(kit.metaText({ step: 3, steps: 8, eta_s: 6.5 }), 'step 3/8 · 7 s left');
  assert.equal(kit.metaText({ stage: 'queued' }), 'queued');
  assert.deepEqual(kit.chipsOf([{ id: 'bg', label: 'Background', state: 'done' }, { id: 'shape', label: 'Shape', state: 'running', eta_s: 42 }, { id: 'views', state: 'waiting' }])
    .map(c => [c.mark, c.label, c.left]), [['✓', 'Background', null], ['●', 'Shape', '42 s left'], ['○', 'views', null]]);
});

test('a new seq is a new frame; at most two frames kept', () => {
  const lv = { preview: { url: '/api/s/comfy/v1/runs/r/preview', seq: 3, w: 1184, h: 896 } };
  assert.equal(kit.previewSrc(lv), '/api/s/comfy/v1/runs/r/preview?seq=3');
  assert.equal(kit.previewSrc({ preview: { url: '/p?x=1', seq: 2 } }), '/p?x=1&seq=2');
  assert.equal(kit.previewSrc({}), null);
  assert.equal(kit.aspectOf(lv), 1184 / 896);
  assert.equal(kit.aspectOf({}, 16 / 9), 16 / 9);
  let f = kit.nextFrames([], 'a');
  f = kit.nextFrames(f, 'a');
  assert.equal(f.length, 1);
  f = kit.nextFrames(kit.nextFrames(f, 'b'), 'c');
  assert.deepEqual(f.map(x => x.src), ['b', 'c']);
});

test('which steps draw a live card, and which outputs the strip leaves out', () => {
  const undo = cards.registerCard('live:x_image', () => null);
  const row = (name, status, live) => ({ type: 'tool', key: name, name, status, progress: live ? { live } : null, item: {} });
  const turn = { steps: [{ rows: [row('x_image', 'done'), row('y_other', 'running', { preview: { url: '/p', seq: 1 } }), row('z_plain', 'running', { stage: 'loading' }), { type: 'update' }] }] };
  assert.deepEqual(chatLive.liveRows(turn).map(r => [r.row.name, r.own]), [['x_image', true], ['y_other', false]]);
  assert.equal(chatLive.shownLive({ tool: 'x_image' }), true);
  assert.equal(chatLive.shownLive({ tool: 'y_other' }), false);
  undo();
  assert.equal(chatLive.shownLive({ tool: 'x_image' }), false);
});
