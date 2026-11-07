// chat-responsive 2.2: the queue strip's rows and heading, and the mock agent's queue: held during a turn, answered
// together when it ends, edited, moved, removed, sent now, sent by Stop, paused by an error.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const q = await load('chat/chat-queue.js');
const cmock = await load('chat/chat-mock.js');
const capi = await load('chat/chat-api.js');

test('rows: the agent\'s held messages, then this page\'s not listed yet', () => {
  const state = { items: [{ id: 'q1', text: 'one', client_id: 'c1' }, { id: 'q2', text: 'two' }], paused: null };
  const rows = q.queueRows(state, [{ cid: 'c1', text: 'one' }, { cid: 'c3', text: 'three', attachments: ['o1'] }]);
  assert.deepEqual(rows.map(r => [r.key, r.text, !!r.sending]), [['q1', 'one', false], ['q2', 'two', false], ['pc3', 'three', true]]);
  assert.deepEqual(rows[2].attachments, ['o1']);
  assert.deepEqual(q.queueRows(null, []), []);
});

test('the heading says when they go', () => {
  assert.equal(q.queueLabel({ count: 2 }), 'Queued · 2 · sent when this reply ends');
  assert.equal(q.queueLabel({ count: 1, waiting: true }), 'Queued · 1 · waits for your answer');
  assert.equal(q.queueLabel({ count: 3, paused: 'error' }), 'Paused after an error');
  assert.deepEqual(capi.messageBody('x', [], {}, [], [], null, 'now'), { text: 'x', attachments: [], when: 'now' });
  assert.deepEqual(capi.messageBody('x', [], {}, [], [], null, 'auto'), { text: 'x', attachments: [] });
});

test('the mock holds messages during a turn and answers them in one turn', async () => {
  const c = cmock.createMockClient({}, { speed: 400 }), events = [];
  const until = async (pred, what) => { for (let i = 0; i < 600; i++) { const e = events.find(pred); if (e) return e; await new Promise(r => setTimeout(r, 5)); } throw new Error('timed out waiting for ' + what); };
  const t = await c.create({});
  await new Promise(ok => c.stream(t.id, 0, { onEvent: e => events.push(e), onReady: ok }));
  await c.send(t.id, 'What can you do?');
  const a = await c.send(t.id, 'make it blue', [], {}, [], [], 'c-a');
  const b = await c.send(t.id, 'and green');
  assert.equal(a.queued.text, 'make it blue'); assert.equal(b.queued.position, 1);
  assert.deepEqual((await c.queue(t.id)).items.map(i => i.text), ['make it blue', 'and green']);
  await c.queueEdit(t.id, b.queued.id, { index: 0 });
  await c.queueEdit(t.id, a.queued.id, { text: 'make it blue, please' });
  assert.deepEqual((await c.queue(t.id)).items.map(i => i.text), ['and green', 'make it blue, please']);
  await until(e => e.type === 'queue' && e.payload.items[1]?.text === 'make it blue, please', 'the change on the stream');
  await assert.rejects(c.queueEdit(t.id, a.queued.id, { text: ' ' }), e => e.status === 422);
  await until(e => e.type === 'user' && e.payload.client_id === 'c-a', 'the held messages sent');
  const users = events.filter(e => e.type === 'user').map(e => e.payload.text);
  assert.deepEqual(users, ['What can you do?', 'and green', 'make it blue, please']);
  assert.deepEqual((await c.queue(t.id)).items, []);
  await until(e => e.type === 'state' && e.payload.state === 'idle' && e.seq > events.find(x => x.payload?.client_id === 'c-a').seq, 'the one turn after them');
  const c2 = await c.send(t.id, 'one more');                     // idle with nothing held: sent at once
  assert.equal(c2.type, 'user');
  await c.cancel(t.id);
});

test('the mock: Stop sends the queue, remove and clear, and Send now steers', async () => {
  const c = cmock.createMockClient({}, { speed: 400 }), events = [];
  const until = async (pred, what) => { for (let i = 0; i < 600; i++) { const e = events.find(pred); if (e) return e; await new Promise(r => setTimeout(r, 5)); } throw new Error('timed out waiting for ' + what); };
  const t = await c.create({});
  c.stream(t.id, 0, { onEvent: e => events.push(e) });
  await c.send(t.id, 'What can you do?');
  const x = await c.send(t.id, 'drop me'), y = await c.send(t.id, 'keep me');
  assert.deepEqual((await c.queueRemove(t.id, x.queued.id)).items.map(i => i.text), ['keep me']);
  await c.cancel(t.id);
  await until(e => e.type === 'user' && e.payload.text === 'keep me', 'Stop sending the queue');
  assert.ok(events.some(e => e.type === 'note' && /stopped/.test(e.payload.text)));
  await until(e => e.type === 'state' && e.payload.state === 'running' && e.seq > events.find(u => u.payload?.text === 'keep me').seq, 'its turn');
  const z = await c.send(t.id, 'steer this');
  const ev = await c.queueSend(t.id, z.queued.id);
  assert.equal(ev.payload.steer, true);
  await c.send(t.id, 'gone');
  assert.deepEqual((await c.queueClear(t.id)).items, []);
  await c.cancel(t.id);
  void y;
});
