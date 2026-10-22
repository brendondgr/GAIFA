// web/mem-pools.js (plan 36.4): the GPU pools' bars. The bars themselves are checked in the browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const mp = await import(pathToFileURL(path.join(root, 'web', 'mem-pools.js')).href);

const sys = { id: 'system', name: 'System memory', total_bytes: 64e9, used_bytes: 20e9, available_bytes: 44e9 };
const services = [{ id: 'comfy', name: 'Images & Video' }, { id: 'lcpp', name: 'LLM Launcher' }];

test('one pool: nothing more to draw', () => {
  assert.deepEqual(mp.poolRows({ pools: [sys], by_service: [] }, services), []);
  assert.equal(mp.poolTitle({ pools: [sys] }), 'Unified memory');
  assert.equal(mp.poolTitle(null), 'Unified memory');
});

test('one card: split by mod, the rest is other', () => {
  const m = { pools: [sys, { id: 'gpu:0', name: 'NVIDIA GeForce RTX 4090', total_bytes: 24e9, used_bytes: 20e9, available_bytes: 4e9 }],
    by_service: [{ id: 'lcpp', vram_bytes: 6e9 }, { id: 'comfy', vram_bytes: 12e9 }, { id: 'web', vram_bytes: 0 }] };
  const [r] = mp.poolRows(m, services);
  assert.equal(mp.poolTitle(m), 'System memory');
  assert.equal(r.text, '20.0 GB / 24.0 GB');
  assert.deepEqual(r.mods.map(x => [x.name, x.bytes, x.pct]), [['Images & Video', 12e9, 50], ['LLM Launcher', 6e9, 25]]);
  assert.equal(r.other.bytes, 2e9);
  assert.equal(r.free, '4.0 GB');
});

test('two cards: a plain bar each', () => {
  const m = { pools: [sys, { id: 'gpu:0', name: 'A', total_bytes: 24e9, used_bytes: 1e9, available_bytes: 23e9 }, { id: 'gpu:1', name: 'B', total_bytes: 24e9, used_bytes: 12e9, available_bytes: 12e9 }],
    by_service: [{ id: 'lcpp', vram_bytes: 12e9 }] };
  const rows = mp.poolRows(m, services);
  assert.deepEqual(rows.map(r => [r.id, r.mods.length, r.other.pct]), [['gpu:0', 0, 1e9 / 24e9 * 100], ['gpu:1', 0, 50]]);
});
