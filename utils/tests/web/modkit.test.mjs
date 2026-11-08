// web/mod-kit.js and web/mod-charts.js: the pure parts (formatting, WAV decoding, make-room retry).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const kit = await load('mod-kit.js');
const mc = await load('mod-charts.js');

test('formatting', () => {
  assert.equal(kit.fmtBytes(13e9), '13.0 GB');
  assert.equal(kit.fmtBytes(512), '512 B');
  assert.equal(kit.fmtSecs(5.4), '5.4 s');
  assert.equal(kit.fmtSecs(125), '2m 5s');
});

test('wavSamples reads the data chunk of a 16-bit mono WAV', () => {
  const n = 4, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 24000, true); v.setUint32(28, 48000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, n * 2, true);
  [0, 16384, -16384, 32767].forEach((x, i) => v.setInt16(44 + i * 2, x, true));
  const s = mc.wavSamples(buf);
  assert.equal(s.length, 4);
  assert.equal(s[1], 0.5); assert.equal(s[2], -0.5);
});

test('callRoom asks, then retries with makeRoom; a refusal cancels', async () => {
  const calls = [];
  const plan = { needs_bytes: 13e9, available_bytes: 2e9, unload: [{ id: 'gen3d', frees_bytes: 52e9 }], enough: true };
  const mk = answer => ({
    service: { name: 'Speech' },
    confirm: async o => { calls.push(o.title); return answer; },
    call: async (m, p, o = {}) => { calls.push(o.makeRoom ? 'retry' : 'first'); if (!o.makeRoom) throw Object.assign(new Error('x'), { code: 'needs_room', data: { plan } }); return { status: 200 }; },
  });
  assert.equal((await kit.callRoom(mk(true), 'POST', '/v1/speech')).status, 200);
  assert.deepEqual(calls, ['first', 'Make room?', 'retry']);
  await assert.rejects(kit.callRoom(mk(false), 'POST', '/v1/speech'), e => e.cancelled === true);
});

test('the mock gen3d box GLB is a valid glTF binary', async () => {
  const { boxesGlb } = await load('mock-mods.js');
  const buf = new DataView(await boxesGlb([{ name: 'a', center: [0, 0, 0], size: [1, 1, 1] }, { name: 'b', center: [1, 0, 0], size: [1, 2, 1], color: [255, 0, 0] }]).arrayBuffer());
  assert.equal(buf.getUint32(0, true), 0x46546C67);           // "glTF"
  assert.equal(buf.getUint32(8, true), buf.byteLength);
  const jlen = buf.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf.buffer, 20, jlen)));
  assert.equal(json.nodes.length, 2);
  assert.equal(json.buffers[0].byteLength, buf.getUint32(20 + jlen, true));
});

test('callRoom also answers a needs_room that a mod passes back from the hub', async () => {
  const calls = [];
  const plan = { needs_bytes: 20e9, available_bytes: 2e9, unload: [{ id: 'tts', frees_bytes: 13e9 }], enough: true };
  const ctx = {
    service: { name: 'LLM Launcher' }, confirm: async () => true,
    call: async (m, p, o = {}) => { calls.push(!!o.makeRoom); if (!o.makeRoom) throw Object.assign(new Error('x'), { code: 'upstream_error', data: { body: { code: 'needs_room', detail: 'x', data: { plan } } } }); return { status: 201 }; },
  };
  assert.equal((await kit.callRoom(ctx, 'POST', '/api/instances')).status, 201);
  assert.deepEqual(calls, [false, true]);
});

// settings-that-stick 4.2: the pages' store keeps a mod's values on the hub; drafts stay in the browser.
function fakeStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), key: i => [...m.keys()][i] ?? null, get length() { return m.size; }, m };
}
function fakeApi(values = {}) {
  const saved = [];
  return { saved, getUiStore: async mod => ({ values: { ...(values[mod] || {}) } }), saveUiStore: async (mod, { set }) => { saved.push([mod, set]); values[mod] = { ...(values[mod] || {}), ...set }; return { values: values[mod] }; } };
}

test('store: the hub’s values win once loaded; set saves there and here; drafts stay here', async () => {
  const st = fakeStorage({ 'gaifa.prefs.imported.tts': '1', 'tts.speak': JSON.stringify({ voice: 'old' }) });
  const api = fakeApi({ tts: { 'tts.speak': { voice: 'af_heart' } } });
  const s = kit.createStore({ storage: st });
  assert.deepEqual(s.get('tts.speak'), { voice: 'old' });            // before load: this browser's copy
  await s.load(api, 'tts');
  assert.deepEqual(s.get('tts.speak'), { voice: 'af_heart' });
  s.set('tts.speak', { voice: 'bf_emma' });
  assert.deepEqual(s.get('tts.speak'), { voice: 'bf_emma' }); assert.deepEqual(api.saved, [['tts', { 'tts.speak': { voice: 'bf_emma' } }]]);
  assert.equal(st.m.get('tts.speak'), JSON.stringify({ voice: 'bf_emma' }));
  s.set('tts.draft', 'Hello'); s.local.set('tts.other', 1);
  assert.equal(api.saved.length, 1); assert.equal(s.get('tts.draft'), 'Hello');
});

test('store: a mod’s values saved in this browser before are copied up once; a down hub falls back', async () => {
  const st = fakeStorage({ 'stt.preset': '"accurate"', 'stt.language': '"en"', 'tts.speak': '{}', 'stt.draft': '"x"' });
  const api = fakeApi({ stt: { 'stt.language': 'de' } });
  const s = kit.createStore({ storage: st });
  await s.load(api, 'stt');
  assert.deepEqual(api.saved, [['stt', { 'stt.preset': 'accurate' }]]);     // not the one the hub has, not a draft, not another mod's
  assert.equal(s.get('stt.preset'), 'accurate'); assert.equal(s.get('stt.language'), 'de');
  assert.equal(st.m.get('gaifa.prefs.imported.stt'), '1');
  await s.load(api, 'stt'); assert.equal(api.saved.length, 1);
  const down = kit.createStore({ storage: fakeStorage({ 'relay.window': '"7d"' }) });
  await down.load({ getUiStore: async () => { throw new Error('down'); } }, 'relay');
  assert.equal(down.get('relay.window', '24h'), '7d');
});
