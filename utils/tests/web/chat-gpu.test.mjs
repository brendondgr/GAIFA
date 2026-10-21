// Plan 31.4: a model call waiting for AIHub's GPU slot shows on the turn's live header. The agent sends the
// transient `gpu_wait` {text, eta_s, ahead} (an empty one clears it); a token, the reply or the turn's end
// clear it too.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const th = await load('chat/chat-thread.js');
const ct = await load('chat/chat-turn.js');
const ca = await load('chat/chat-activity.js');

const EMPTY = { deltas: {}, progress: {}, meter: null };
const USER = { thread_id: 't', seq: 1, type: 'user', payload: { text: 'hello' }, ts: 100 };
const WAIT = { type: 'gpu_wait', seq: null, payload: { text: 'Waiting for the GPU: Images & Video portrait, about 6 min left', eta_s: 360, ahead: [] } };
const turnOf = live => ct.groupTurns(th.buildView([USER], live), { running: true, now: 110 }).find(b => b.kind === 'turn');

test('the wait shows on the live header, then a token clears it', () => {
  let live = th.applyTransient(EMPTY, WAIT);
  const st = turnOf(live).status;
  assert.equal(st.kind, 'gpu');
  assert.equal(ca.statusText(st, {}).text, 'Waiting for the GPU: Images & Video portrait, about 6 min left');
  live = th.applyTransient(live, { type: 'delta', seq: null, payload: { kind: 'thinking', text: 'hm', step: 's1' }, ts: 105 });
  assert.equal(turnOf(live).status.kind, 'thinking');
});

test('an empty gpu_wait or the end of the turn clears it', () => {
  const live = th.applyTransient(EMPTY, WAIT);
  assert.equal(th.applyTransient(live, { type: 'gpu_wait', seq: null, payload: {} }).gpu, null);
  assert.equal(th.settleLive(live, { type: 'state', seq: 3, payload: { state: 'idle' } }).gpu, null);
  assert.equal(turnOf(EMPTY).status.kind, 'working');
});
