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
