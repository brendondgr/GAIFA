// web/chat/chat-status.js (plan 46.3): the status cards' pure parts and their registration.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const st = await import(pathToFileURL(path.join(root, 'web/chat/chat-status.js')).href);
const cards = await import(pathToFileURL(path.join(root, 'web/chat/chat-cards.js')).href);

test('memory from the API reads like the tool, and its bar', () => {
  const m = st.memoryFromApi({ total_bytes: 128e9, used_bytes: 40e9, available_bytes: 88e9, reserve_bytes: 8e9,
    by_service: [{ id: 'comfy', used_bytes: 20e9, estimate_bytes: 22e9, load: 'loaded' }, { id: 'tts', used_bytes: 4e9, load: 'loaded' }] }, { comfy: 'Images & Video' });
  assert.equal(m.used_gb, 40);
  assert.deepEqual(m.by_service[0], { id: 'comfy', name: 'Images & Video', used_gb: 20, estimate_gb: 22, load: 'loaded' });
  const bar = st.memoryBar(m);
  assert.deepEqual(bar.map(p => [p.id, Math.round(p.pct)]), [['comfy', 16], ['tts', 3], ['other', 13]]);
});

test('memory rows: loaded or large, the rest summed', () => {
  const r = { by_service: [{ id: 'a', used_gb: 0.1, load: 'n/a' }, { id: 'b', used_gb: 3, load: 'loaded' }, { id: 'c', used_gb: 0.2, load: 'unloaded' }, { id: 'd', used_gb: 0.7, load: 'unloaded' }] };
  const m = st.memoryRows(r);
  assert.deepEqual(m.rows.map(s => s.id), ['b', 'd']);
  assert.equal(m.rest.n, 2);
  assert.ok(Math.abs(m.rest.gb - 0.3) < 1e-9);
});

test('state words and the doctor summary', () => {
  assert.equal(st.stateTone({ state: 'ready', load: 'loaded' })[1], 'loaded');
  assert.equal(st.stateTone({ state: 'ready', busy: true })[1], 'busy');
  assert.equal(st.stateTone({ state: 'stopped' })[1], 'stopped');
  assert.equal(st.doctorSummary({ counts: { fail: 1, warn: 1, note: 2, ok: 40 } }), '2 problems, 2 notes, 40 passed');
  assert.equal(st.doctorSummary({ counts: { ok: 9 } }), 'No problems, 9 passed');
});

test('the result comes from the event, as JSON or as an object', () => {
  const ctx = r => ({ liveCard: { row: { item: { result: r } } } });
  assert.deepEqual(st.parsed(ctx({ content: '{"status":"done","result":{"a":1}}' })), { a: 1 });
  assert.deepEqual(st.parsed(ctx({ result: { b: 2 } })), { b: 2 });
  assert.equal(st.parsed(ctx({ content: 'not json' })), null);
});

test('each status tool has its card', () => {
  for (const t of ['hub_memory_status', 'hub_list_services', 'hub_gpu_status', 'hub_doctor', 'hub_free_gpu']) assert.ok(cards.hasCard('live:' + t), t);
});
