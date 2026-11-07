// chat-responsive 1.3: messages drawn before the agent stored them (buildView's live.pending), matched to their user
// event by client_id or by the seq the send answered with, and kept in order.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const th = await import(pathToFileURL(path.join(root, 'web/chat/chat-thread.js')).href);
const turn = await import(pathToFileURL(path.join(root, 'web/chat/chat-turn.js')).href);

const user = (seq, text, extra = {}) => ({ seq, type: 'user', ts: seq, payload: { text, ...extra } });
const reply = (seq, text) => ({ seq, type: 'assistant', ts: seq, payload: { text, step: 's' + seq } });
const pend = (cid, text, extra = {}) => ({ cid, text, ts: 100, state: 'sending', ...extra });

test('a pending message is drawn after the thread, as a user message', () => {
  const v = th.buildView([user(1, 'hi'), reply(2, 'hello')], { deltas: {}, pending: [pend('c1', 'next one', { quotes: [{ text: 'q', reply: 'r' }] })] });
  const last = v.items.at(-1);
  assert.equal(last.kind, 'user'); assert.equal(last.key, 'uc1'); assert.equal(last.pending, 'sending');
  assert.equal(last.ev.seq, null); assert.equal(last.ev.payload.text, 'next one'); assert.deepEqual(last.ev.payload.quotes, [{ text: 'q', reply: 'r' }]);
});

test('its user event takes its place, with the same key', () => {
  const p = [pend('c1', 'next one')];
  const stored = th.buildView([user(1, 'hi'), user(3, 'next one', { client_id: 'c1' })], { deltas: {}, pending: p });
  assert.deepEqual(stored.items.map(i => [i.key, i.pending ?? null]), [['e1', null], ['uc1', null]]);
  const bySeq = th.buildView([user(1, 'hi'), user(3, 'next one')], { deltas: {}, pending: [pend('c1', 'next one', { seq: 3, state: 'sent' })] });
  assert.equal(bySeq.items.length, 2);                          // an agent that didn't echo client_id: matched by the seq
  assert.deepEqual(th.pendingOf([user(3, 'x', { client_id: 'c1' })], p), []);
});

test('a failed message stays, and two pending ones keep their order', () => {
  const v = th.buildView([], { deltas: {}, pending: [pend('a', 'first', { state: 'failed', error: 'GAIFA did not answer' }), pend('b', 'second')] });
  assert.deepEqual(v.items.map(i => [i.key, i.pending, i.error]), [['ua', 'failed', 'GAIFA did not answer'], ['ub', 'sending', null]]);
});

test('a pending message opens a turn of its own, keyed as its stored message will be', () => {
  const v = th.buildView([user(1, 'hi'), reply(2, 'hello')], { deltas: {}, pending: [pend('c9', 'more')] });
  const turns = turn.groupTurns(v, { running: true }).filter(b => b.kind === 'turn');
  assert.equal(turns.length, 2); assert.equal(turns[1].key, 'turn:uc9'); assert.equal(turns[1].running, true);
});

test('a recall event is never drawn', () => {
  const v = th.buildView([user(1, 'hi'), { seq: 2, type: 'recall', payload: { for: 1, memory: [{ id: 'f1' }] } }], { deltas: {} });
  assert.deepEqual(v.items.map(i => i.kind), ['user']);
});
