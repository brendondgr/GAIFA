// services/gen3d/ui/chat.js (plan 45.3): the 3D card's pure parts and what it registers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadMod, modSkip } from './mods.mjs';

const skip = modSkip('services/gen3d/ui/chat.js');
const mod = await loadMod('services/gen3d/ui/chat.js');
const t = (name, fn) => test(name, { skip }, fn);

t('points come from the outline: only opaque pixels, front and back, in about -1..1', () => {
  const w = 8, h = 6, data = new Uint8ClampedArray(w * h * 4);
  for (let y = 1; y < 5; y++) for (let x = 2; x < 6; x++) { const i = (y * w + x) * 4; data[i] = data[i + 1] = data[i + 2] = 200; data[i + 3] = 255; }
  let s = 1; const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const pts = mod.pointsFromAlpha(data, w, h, rand, 1);
  assert.ok(pts.length >= 16 && pts.length <= 32, String(pts.length));
  for (const [x, y, z, l] of pts) {
    assert.ok(Math.abs(x) <= 1 && Math.abs(y) <= 1 && Math.abs(z) <= 1);
    assert.ok(l > 0.7 && l < 0.8);
  }
  assert.ok(pts.some(p => p[2] < 0) && pts.some(p => p[2] > 0));
  assert.deepEqual(mod.pointsFromAlpha(new Uint8ClampedArray(16), 2, 2), []);
});

t('the phase follows the preview: nothing yet, the cut-out, the views, done', () => {
  assert.equal(mod.phaseOf(null, 'running'), 'wait');
  assert.equal(mod.phaseOf({ preview: { url: '/api/s/gen3d/v1/jobs/j_1/files/input_rgba.png' } }, 'running'), 'cutout');
  assert.equal(mod.phaseOf({ preview: { url: '/api/s/gen3d/v1/jobs/j_1/files/preview.png' } }, 'running'), 'views');
  assert.equal(mod.phaseOf({ preview: { url: '/x/views.png' } }, 'running'), 'views');
  assert.equal(mod.phaseOf({}, 'done'), 'done');
});

t('it registers the live card for make_3d', () => {
  const kinds = [];
  mod.default({ ui: { h: () => null }, live: {}, parts: {}, registerCard: k => kinds.push(k) });
  assert.deepEqual(kinds, ['live:gen3d_make_3d']);
});
