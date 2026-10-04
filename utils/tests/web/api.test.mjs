// Unit tests for web/api.js (Node's built-in runner, no browser):
//   node --test utils/tests/web/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, createApi, createHttpApi, METHOD_AREA } from '../../../web/api.js';

const json = (status, body, headers = {}) => new Response(body === undefined ? null : JSON.stringify(body),
  { status, headers: { 'content-type': 'application/json', ...headers } });

function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init) => { calls.push({ url, ...init }); return handler(url, init); };
  fn.calls = calls;
  return fn;
}

class FakeES {
  static all = [];
  constructor(url) { this.url = url; this.closed = false; FakeES.all.push(this); }
  close() { this.closed = true; }
  emit(ev) { this.onmessage?.({ data: JSON.stringify(ev) }); }
  fail() { this.onerror?.(new Event('error')); }
}

function fakeMock() {
  const listeners = new Set(), errs = new Set();
  const m = { mock: { scenario: true } };
  for (const name of Object.keys(METHOD_AREA)) m[name] = async (...args) => ({ from: 'mock', name, args });
  m.getOverview = async () => ({ services: ['mock'], memory: 'mock', recent_outputs: [], activity: [], alerts: [], jobs: [], system: 'mock' });
  m.subscribe = (onEvent, onError) => { listeners.add(onEvent); if (onError) errs.add(onError); return { close: () => { listeners.delete(onEvent); errs.delete(onError); } } };
  m.emit = ev => listeners.forEach(fn => fn(ev));
  m.listeners = listeners;
  return m;
}

test('methods in live areas use HTTP, the rest the mock', async () => {
  const fetch = fakeFetch(() => json(200, { hub: { version: '9.9.9' } }));
  const api = createApi({ base: '', liveAreas: ['system'], mock: fakeMock(), fetch, EventSource: FakeES });
  assert.deepEqual(await api.getSystem(), { hub: { version: '9.9.9' } });
  assert.equal(fetch.calls[0].url, '/api/system');
  assert.equal((await api.listServices()).from, 'mock');
  assert.equal((await api.getSettings()).from, 'mock');
  assert.deepEqual(api.liveAreas, ['system']);
  assert.ok(api.isLive('system') && !api.isLive('services'));
  assert.deepEqual(api.mock, { scenario: true });
});

test('no base (not served by the hub) means everything is mock', async () => {
  const fetch = fakeFetch(() => { throw new Error('should not fetch'); });
  const api = createApi({ base: null, liveAreas: ['system'], mock: fakeMock(), fetch });
  assert.equal((await api.getSystem()).from, 'mock');
  assert.deepEqual(api.liveAreas, []);
});

test('every brief method has an area and an HTTP implementation', () => {
  const http = createHttpApi('');
  for (const name of Object.keys(METHOD_AREA)) assert.equal(typeof http[name], 'function', name);
  assert.equal(typeof http.getOverview, 'function');
  assert.equal(typeof http.subscribe, 'function');
});

test('HTTP paths, query strings and bodies', async () => {
  const fetch = fakeFetch(() => json(200, {}));
  const http = createHttpApi('http://h', { fetch });
  await http.loadService('tts', { makeRoom: true });
  await http.listModels({ kind: 'llm', q: 'a b', service: '' });
  await http.deleteModel('m/1', { files: true });
  await http.planRoom('tts', 5);
  await http.getMetrics({ series: ['mem.used', 'mem.svc.*'], range: '1h' });
  const urls = fetch.calls.map(c => `${c.method} ${c.url}`);
  assert.deepEqual(urls, [
    'POST http://h/api/services/tts/load?make_room=1',
    'GET http://h/api/models?kind=llm&q=a%20b',
    'DELETE http://h/api/models/m%2F1?files=1',
    'POST http://h/api/memory/plan',
    'GET http://h/api/metrics?series=mem.used%2Cmem.svc.*&range=1h',
  ]);
  assert.deepEqual(JSON.parse(fetch.calls[3].body), { service: 'tts', needs_bytes: 5 });
  assert.equal(fetch.calls[3].headers['content-type'], 'application/json');
});

test('error mapping: hub down, envelope, non-JSON, 204', async () => {
  const down = createHttpApi('', { fetch: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(down.getSystem(), e => e instanceof ApiError && e.status === 0 && e.code === 'hub_error' && /not responding/.test(e.detail));

  const env = createHttpApi('', { fetch: async () => json(409, { detail: 'no room', code: 'needs_room', data: { plan: { enough: false } } }, { 'x-aihub-error': 'needs_room' }) });
  await assert.rejects(env.loadService('tts'), e => e.status === 409 && e.code === 'needs_room' && e.detail === 'no room' && e.data.plan.enough === false);

  const html = createHttpApi('', { fetch: async () => new Response('Bad Gateway', { status: 502 }) });
  await assert.rejects(html.getSystem(), e => e.status === 502 && e.code === 'hub_error' && e.detail === 'Bad Gateway');

  const empty = createHttpApi('', { fetch: async () => new Response(null, { status: 204 }) });
  assert.equal(await empty.deleteOutput('x'), null);
});

test('callService: JSON, media blobs, mod errors and hub errors', async () => {
  let next;
  const http = createHttpApi('', { fetch: async () => next() });
  next = () => json(200, { ok: 1 });
  const r = await http.callService('tts', 'POST', '/v1/echo?a=1', { query: { b: 2 }, json: { x: 1 } });
  assert.equal(r.status, 200); assert.equal(r.ok, true); assert.deepEqual(r.json, { ok: 1 }); assert.equal(r.content_type, 'application/json');

  next = () => new Response(new Uint8Array([82, 73, 70, 70]), { status: 200, headers: { 'content-type': 'audio/wav' } });
  const a = await http.callService('tts', 'POST', '/v1/speech', { json: {} });
  assert.equal(a.blob.size, 4); assert.match(a.url, /^blob:/);

  next = () => json(404, { detail: 'no voice "x"' });
  await assert.rejects(http.callService('tts', 'GET', '/v1/voices/x'), e => e.code === 'upstream_error' && e.status === 404 && e.detail === 'no voice "x"' && !!e.data.body.detail);

  next = () => json(503, { detail: 'Speech is not running', code: 'service_not_running' }, { 'x-aihub-error': 'service_not_running' });
  await assert.rejects(http.callService('tts', 'GET', '/health'), e => e.code === 'service_not_running' && e.status === 503);
});

test('callService streams server-sent events to onEvent', async () => {
  const body = 'data: {"n":0}\n\ndata: {"n":1}\n\n: comment\ndata: done\n\n';
  const http = createHttpApi('', { fetch: async () => new Response(body, { headers: { 'content-type': 'text/event-stream' } }) });
  const seen = [];
  const r = await http.callService('x', 'GET', '/v1/events', { onEvent: d => seen.push(d) });
  assert.deepEqual(seen, ['{"n":0}', '{"n":1}', 'done']);
  assert.equal(r.text, '{"n":0}\n{"n":1}\ndone');
});

test('callService sends forms as multipart', async () => {
  const fetch = fakeFetch(() => json(200, {}));
  await createHttpApi('', { fetch }).callService('gen3d', 'POST', '/v1/jobs', { form: { prompt: 'fox', tags: ['a', 'b'] } });
  const fd = fetch.calls[0].body;
  assert.ok(fd instanceof FormData);
  assert.equal(fd.get('prompt'), 'fox'); assert.deepEqual(fd.getAll('tags'), ['a', 'b']);
});

test('subscribe merges live events for live areas with mock events for the rest', () => {
  FakeES.all = [];
  const mock = fakeMock();
  const api = createApi({ base: '', liveAreas: ['system', 'services'], mock, EventSource: FakeES });
  const got = [];
  const sub = api.subscribe(ev => got.push(ev), () => got.push('down'));
  const es = FakeES.all[0];
  assert.equal(es.url, '/api/events');
  mock.emit({ type: 'service', service: { id: 'mocked' } });   // services is live: dropped
  mock.emit({ type: 'memory', memory: 'from mock' });           // memory is mocked: kept
  es.emit({ type: 'service', service: { id: 'live' } });       // kept
  es.emit({ type: 'activity', item: {} });                      // events area mocked: dropped
  es.emit({ type: 'resync' });                                  // always kept
  assert.deepEqual(got, [{ type: 'memory', memory: 'from mock' }, { type: 'service', service: { id: 'live' } }, { type: 'resync' }]);
  es.fail(); es.fail();
  assert.deepEqual(got.slice(3), ['down']);                     // reported once, stream closed
  assert.ok(es.closed);
  sub.close();
  assert.equal(mock.listeners.size, 0);
});

test('subscribe with nothing live opens no hub stream', () => {
  FakeES.all = [];
  createApi({ base: '', liveAreas: [], mock: fakeMock(), EventSource: FakeES }).subscribe(() => {});
  assert.equal(FakeES.all.length, 0);
});

test('getOverview is assembled from live areas until /api/overview exists', async () => {
  const fetch = fakeFetch(url => json(200, url === '/api/system' ? { hub: 'live' } : [{ id: 'live-svc' }]));
  const api = createApi({ base: '', liveAreas: ['system'], mock: fakeMock(), fetch });
  const ov = await api.getOverview();
  assert.deepEqual(ov.system, { hub: 'live' });
  assert.deepEqual(ov.services, ['mock']);
  assert.deepEqual(fetch.calls.map(c => c.url), ['/api/system']);

  const down = createApi({ base: '', liveAreas: ['system'], mock: fakeMock(), fetch: async () => { throw new TypeError('x'); } });
  await assert.rejects(down.getOverview(), e => e.status === 0);
});
