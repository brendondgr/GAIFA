// web/gpu-queue.js (plan 31.5): the pure parts of the GPU queue's views. The components are checked in the browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const g = await import(pathToFileURL(path.join(root, 'web', 'gpu-queue.js')).href);

const names = { gen3d: '3D Generate', comfy: 'Images & Video', tts: 'Speech' };
const nameOf = id => names[id] || id;
const now = 10_000;
const gpu = {
  queue: true, lease_ttl_s: 60,
  holder: { group: 'gen3d', leases: [
    { id: 'a', service: 'gen3d', group: 'gen3d', class: 'job', label: 'Make 3D', state: 'held', created_ts: now - 200, granted_ts: now - 120, elapsed_s: 120, eta_s: 240 },
    { id: 'b', service: 'comfy', group: 'comfy', class: 'job', label: 'TRELLIS.2', state: 'held', parent: 'a', created_ts: now - 60, granted_ts: now - 60, eta_s: null },
  ] },
  waiting: [
    { id: 'c', service: 'comfy', class: 'job', label: 'Image', state: 'waiting', created_ts: now - 30, waited_s: 30, eta_s: 240 },
    { id: 'd', service: 'tts', name: 'Speech (named)', class: 'job', label: 'Hello', state: 'waiting', created_ts: now - 5, eta_s: 40 },
  ],
  recent: [],
};

test('rows: holders, then the waiting ones in order with their positions', () => {
  const r = g.gpuRows(gpu, nameOf, now);
  assert.deepEqual(r.holder.map(x => [x.name, x.nested, x.eta]), [['3D Generate', false, 'about 4 min'], ['Images & Video', true, '']]);
  assert.equal(r.holder[0].elapsed, '2m');
  assert.deepEqual(r.waiting.map(x => [x.pos, x.name, x.eta]), [[1, 'Images & Video', 'about 4 min'], [2, 'Speech (named)', 'about 40 s']]);
  assert.equal(r.waiting[1].waited, '5s');
  assert.equal(r.on, true);
  assert.deepEqual(g.gpuRows(null), { holder: [], waiting: [], on: true });
  assert.equal(g.gpuRows({ ...gpu, queue: false }).on, false);
});

test('summary and ETA words', () => {
  assert.equal(g.gpuSummary(gpu, nameOf), '3D Generate · 2 waiting');
  assert.equal(g.gpuSummary({ holder: null, waiting: [] }), 'free');
  assert.equal(g.fmtEta(null), '');
  assert.equal(g.fmtEta(30), 'about 30 s');
  assert.equal(g.fmtEta(400), 'about 7 min');
});

test('a job waiting for the GPU reads as one line', () => {
  const job = { id: 'j', state: 'queued', stage: 'waiting_gpu', ahead: [{ service: 'gen3d', label: 'Make 3D', eta_s: 240 }], eta_s: 240 };
  assert.equal(g.jobGpuText(job, nameOf), 'Waiting for the GPU: 3D Generate (Make 3D), about 4 min');
  assert.equal(g.jobGpuText({ stage: 'waiting_gpu' }), 'Waiting for the GPU');
  assert.equal(g.jobGpuText({ state: 'running' }), null);
});

test('wait times: the mean of each mod\'s wait and hold series, longest wait first', () => {
  const rows = g.waitTimes({ series: { 'gpu.wait.comfy': [null, 10, 30], 'gpu.hold.comfy': [60], 'gpu.wait.tts': [5], 'gpu.waiting': [1], 'gpu.hold.gen3d': [null] } });
  assert.deepEqual(rows, [{ service: 'comfy', wait: 20, hold: 60 }, { service: 'tts', wait: 5, hold: null }]);
});
