// Plan 44.2: a job's `live` progress rides on the agent's transient `progress` event onto the step's item.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const th = await import(pathToFileURL(path.join(root, 'web/chat/chat-thread.js')).href);
const ev = (seq, type, payload) => ({ thread_id: 't', seq, ts: seq, type, payload });

test('the live shape reaches the tool item, and goes with the result', () => {
  const lv = { stage: 'sampling', step: 3, steps: 8, preview: { url: '/api/s/comfy/v1/runs/r/preview', seq: 3 } };
  let live = { deltas: {}, progress: {}, meter: null };
  live = th.applyTransient(live, { type: 'progress', seq: null, payload: { id: 'c1', progress: 0.4, live: lv } });
  const events = [ev(1, 'user', { text: 'fox' }), ev(2, 'tool_call', { id: 'c1', name: 'comfy_generate_image', arguments: { prompt: 'fox' } })];
  const item = th.buildView(events, live).items.find(i => i.kind === 'tool');
  assert.deepEqual(item.progress.live, lv);
  const done = [...events, ev(3, 'tool_result', { id: 'c1', name: 'comfy_generate_image', status: 'done', outputs: [] })];
  live = th.settleLive(live, done[2]);
  assert.ok(!th.buildView(done, live).items.find(i => i.kind === 'tool').progress);
});
