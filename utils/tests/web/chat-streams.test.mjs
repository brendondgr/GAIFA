// web/chat/chat-streams.js (chat-split plan 3.2): every open chat on one EventSource, reopened with each thread's
// last seq when the set changes, ready per thread, no repeats for a subscriber, the fallback to one stream per
// thread, and the live client using the pool.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const { createStreamPool } = await import(pathToFileURL(path.join(root, 'web/chat/chat-streams.js')).href);
const { createLiveClient } = await import(pathToFileURL(path.join(root, 'web/chat/chat-api.js')).href);

function fakeES() {
  const made = [];
  class ES {
    constructor(url) { this.url = url; this.closed = false; made.push(this); }
    close() { this.closed = true; }
    send(ev) { this.onmessage?.({ data: JSON.stringify(ev) }); }
  }
  return { ES, made, live: () => made.filter(e => !e.closed) };
}
const tick = () => new Promise(r => setTimeout(r, 0));
const wait = ms => new Promise(r => setTimeout(r, ms));
const pool = (es, o = {}) => createStreamPool({ streamsUrl: spec => `/s?threads=${spec}`, single: o.single || (() => { throw new Error('no single'); }),
  probe: o.probe || (() => Promise.resolve(true)), EventSource: es.ES, delay: 1, control: o.control || null });

test('two chats share one connection; each gets only its own events, once', async () => {
  const es = fakeES(), p = pool(es), got = { a: [], b: [] }, ready = [];
  p.stream('t_a', 0, { onEvent: e => got.a.push(e.seq), onReady: e => ready.push(e.thread_id) });
  p.stream('t_b', 5, { onEvent: e => got.b.push(e.seq), onReady: e => ready.push(e.thread_id) });
  await wait(10);
  assert.equal(es.live().length, 1, 'one EventSource');
  assert.equal(es.live()[0].url, '/s?threads=t_a:0,t_b:5');
  const c = es.live()[0];
  c.send({ thread_id: 't_a', seq: 1, type: 'user' }); c.send({ thread_id: 't_b', seq: 6, type: 'user' });
  c.send({ thread_id: 't_a', seq: 1, type: 'user' });                       // a repeat: skipped
  c.send({ thread_id: 't_a', seq: null, type: 'delta' });                   // transient: always passed on
  c.send({ type: 'ready', thread_id: 't_a', seq: 1 }); c.send({ type: 'ready', thread_id: 't_b', seq: 6 });
  c.send({ type: 'gone', thread_id: 't_x' });
  assert.deepEqual(got, { a: [1, null], b: [6] });
  assert.deepEqual(ready, ['t_a', 't_b']);
});

test('a new chat reopens the connection with each thread\'s last seq; closing the last one closes it', async () => {
  const es = fakeES(), p = pool(es), got = [];
  const a = p.stream('t_a', 0, { onEvent: e => got.push(['a', e.seq]) });
  await wait(10);
  es.live()[0].send({ thread_id: 't_a', seq: 3, type: 'user' });
  const b = p.stream('t_b', 0, { onEvent: e => got.push(['b', e.seq]) });
  await wait(10);
  assert.equal(es.made.length, 2); assert.equal(es.made[0].closed, true);
  assert.equal(es.live()[0].url, '/s?threads=t_a:3,t_b:0', 'a from its last seq');
  es.live()[0].send({ thread_id: 't_a', seq: 3, type: 'user' });           // replayed after the reopen: not again
  es.live()[0].send({ thread_id: 't_a', seq: 4, type: 'user' });
  assert.deepEqual(got, [['a', 3], ['a', 4]]);
  assert.equal(a.lastSeq, 4);
  a.close(); await wait(10);
  assert.equal(es.live()[0].url, '/s?threads=t_b:0');
  b.close(); await wait(10);
  assert.equal(es.live().length, 0);
  assert.equal(p.open, false);
});

test('the same chat in two panes: the second replays from the start, the first sees nothing twice', async () => {
  const es = fakeES(), p = pool(es), one = [], two = [];
  p.stream('t_a', 0, { onEvent: e => one.push(e.seq) });
  await wait(10);
  es.live()[0].send({ thread_id: 't_a', seq: 1, type: 'user' });
  p.stream('t_a', 0, { onEvent: e => two.push(e.seq) });
  await wait(10);
  assert.equal(es.live()[0].url, '/s?threads=t_a:0');
  es.live()[0].send({ thread_id: 't_a', seq: 1, type: 'user' }); es.live()[0].send({ thread_id: 't_a', seq: 2, type: 'user' });
  assert.deepEqual(one, [1, 2]); assert.deepEqual(two, [1, 2]);
});

test('a dropped connection says reconnecting and comes back from the last seqs', async () => {
  const es = fakeES(), states = [];
  const p = createStreamPool({ streamsUrl: s => `/s?threads=${s}`, single: () => null, EventSource: es.ES, delay: 1,
    setTimer: (f, ms) => setTimeout(f, Math.min(ms, 5)) });
  p.stream('t_a', 0, { onState: s => states.push(s) });
  await wait(10);
  es.live()[0].onopen(); es.live()[0].send({ thread_id: 't_a', seq: 7, type: 'user' });
  es.live()[0].onerror();
  assert.equal(es.live().length, 0);
  await wait(20);
  assert.equal(es.live()[0].url, '/s?threads=t_a:7');
  assert.deepEqual(states, ['open', 'reconnecting']);
});

test('an agent without /v1/streams: one stream per chat, and the pool says it isn\'t shared', async () => {
  const es = fakeES(), singles = [];
  const p = pool(es, { probe: () => Promise.resolve(false), single: (tid, after) => { const s = { tid, after, closed: false, close() { this.closed = true; }, lastSeq: after }; singles.push(s); return s; } });
  const a = p.stream('t_a', 2, {});
  await wait(10);
  p.stream('t_b', 0, {});
  assert.deepEqual(singles.map(s => [s.tid, s.after]), [['t_a', 2], ['t_b', 0]]);
  assert.equal(es.made.length, 0);
  assert.equal(p.shared, false);
  a.close();
  assert.equal(singles[0].closed, true);
});

test('the live client streams through the pool: one EventSource on /v1/streams for two chats', async () => {
  const es = fakeES();
  const fetch = async u => ({ status: u.includes('/v1/streams') ? 200 : 404, headers: { get: () => null }, ok: true, text: async () => '' });
  const c = createLiveClient({ fetch, EventSource: es.ES });
  assert.equal(c.sharedStream, true);
  const got = [];
  c.stream('t_a', 0, { onEvent: e => got.push(e.thread_id) });
  c.stream('t_b', 0, { onEvent: e => got.push(e.thread_id) });
  await wait(80);
  assert.equal(es.live().length, 1);
  assert.equal(es.live()[0].url, '/api/s/agent/v1/streams?threads=t_a:0,t_b:0');
  es.live()[0].send({ thread_id: 't_b', seq: 1, type: 'user' });
  assert.deepEqual(got, ['t_b']);
});

test('the live client falls back to per-chat streams when the agent answers 404 itself', async () => {
  const es = fakeES();
  const fetch = async () => ({ status: 404, headers: { get: () => null }, ok: false, text: async () => '' });
  const c = createLiveClient({ fetch, EventSource: es.ES });
  c.stream('t_a', 0, {});
  await wait(80);
  assert.equal(es.live()[0].url, '/api/s/agent/v1/threads/t_a/stream?after=0');
  assert.equal(c.sharedStream, false);
});


test('chat-responsive 3.1: a chat opened or closed later joins or leaves the open connection; a failed call reopens it', async () => {
  const es = fakeES(), calls = [];
  let answer = true;
  const p = pool(es, { control: async (id, body) => { calls.push([id, body]); return answer; } }), got = { a: [], b: [] };
  p.stream('t_a', 3, { onEvent: e => got.a.push(e.seq) });
  await wait(10);
  const c = es.live()[0];
  c.send({ type: 'stream', id: 's_1' });
  const b = p.stream('t_b', 0, { onEvent: e => got.b.push(e.seq) });
  await wait(10);
  assert.equal(es.made.length, 1, 'no new EventSource');
  assert.deepEqual(calls, [['s_1', { add: [['t_b', 0]], remove: [] }]]);
  c.send({ thread_id: 't_b', seq: 1, type: 'user' });
  assert.deepEqual(got.b, [1]);
  b.close();
  await wait(10);
  assert.deepEqual(calls[1], ['s_1', { add: [], remove: ['t_b'] }]);
  answer = false;                                                   // the stream ended on the agent: open a new one
  p.stream('t_c', 0, {});
  await wait(10);
  assert.equal(es.live().length, 1); assert.equal(es.made.length, 2);
  assert.equal(es.live()[0].url, '/s?threads=t_a:3,t_c:0');
});

test('chat-responsive 3.1: before the stream has its id, or with no control, a change reopens it as before', async () => {
  const es = fakeES(), p = pool(es, { control: async () => true });
  p.stream('t_a', 0, {});
  await wait(10);
  p.stream('t_b', 0, {});                                           // no {type: 'stream'} yet
  await wait(10);
  assert.equal(es.made.length, 2); assert.equal(es.live()[0].url, '/s?threads=t_a:0,t_b:0');
});
