// services/comfy/ui/chat.js (plan 45.2): the picture and video live cards' pure parts and what they register.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const mod = await import(pathToFileURL(path.join(root, 'services/comfy/ui/chat.js')).href);
const kit = await import(pathToFileURL(path.join(root, 'web/live-kit.js')).href);

test('the box follows the call: an aspect, width and height, or nothing', () => {
  assert.equal(mod.aspectFromArgs({ aspect: '16:9' }), 16 / 9);
  assert.equal(mod.aspectFromArgs({ aspect: '4:3 (Standard)' }), 4 / 3);
  assert.equal(mod.aspectFromArgs({ width: 832, height: 480 }), 832 / 480);
  assert.equal(mod.aspectFromArgs({ aspect_ratio: '16:9' }), 16 / 9);   // as a model wrote it
  assert.equal(mod.aspectFromArgs({ prompt: 'x' }), null);
});

test('words for running, done and failed', () => {
  const run = mod.cardState('comfy_generate_image', 'running', { step: 3, steps: 8, eta_s: 5 }, 12, kit);
  assert.deepEqual([run.title, run.meta, run.done], ['Making a picture', 'step 3/8 · 5 s left', false]);
  const done = mod.cardState('comfy_animate_image', 'done', null, 161, kit);
  assert.deepEqual([done.title, done.meta, done.done], ['Made a video', '2m 41s', true]);
  assert.equal(mod.cardState('comfy_edit_image', 'failed', null, 3, kit).title, "Couldn't edit the picture");
  assert.equal(mod.cardState('comfy_generate_image', 'queued', { stage: 'queued' }, null, kit).meta, 'queued');
});

test('it registers a live card for every picture and video tool', () => {
  const kinds = [];
  mod.default({ ui: { h: () => null }, live: kit, parts: {}, registerCard: k => kinds.push(k) });
  for (const t of ['comfy_generate_image', 'comfy_edit_image', 'comfy_upscale_image', 'comfy_remove_background', 'comfy_run_workflow', 'comfy_animate_image', 'comfy_generate_video'])
    assert.ok(kinds.includes('live:' + t), t);
});
