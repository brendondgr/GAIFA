// services/tts/ui/chat.js (plan 45.4): the speech card's pure parts and what it registers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadMod, modSkip } from './mods.mjs';

const skip = modSkip('services/tts/ui/chat.js');
const mod = await loadMod('services/tts/ui/chat.js');
const t = (name, fn) => test(name, { skip }, fn);

t('lines split as the mod splits them', () => {
  assert.deepEqual(mod.linesOf('a\n\n b '), ['a', 'b']);
  assert.equal(mod.linesOf('One sentence here. '.repeat(12)).length, 12);
});

t('peaks: one bar per slice, scaled to the loudest', () => {
  const s = new Int16Array(1200); s[0] = 100; s[600] = 1000;
  const p = mod.peaksOf(s, 2);
  assert.deepEqual(p, [0.1, 1]);
  assert.deepEqual(mod.peaksOf(null, 3), [0, 0, 0]);
});

t('the line at a share of the way through', () => {
  const lines = ['aaaa', 'bbbb', 'cccc', 'dddd'];
  assert.equal(mod.lineAt(lines, 0), 0);
  assert.equal(mod.lineAt(lines, 0.3), 1);
  assert.equal(mod.lineAt(lines, 0.99), 3);
});

t("a WAV's samples", () => {
  const n = 3, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE'); str(12, 'fmt '); v.setUint32(16, 16, true);
  str(36, 'data'); v.setUint32(40, n * 2, true); [5, -5, 7].forEach((x, i) => v.setInt16(44 + i * 2, x, true));
  assert.deepEqual([...mod.wavSamples(buf)], [5, -5, 7]);
  assert.equal(mod.wavSamples(new ArrayBuffer(8)), null);
});

t('it registers the live card for speak', () => {
  const kinds = [];
  mod.default({ ui: { h: () => null }, live: {}, parts: {}, registerCard: k => kinds.push(k) });
  assert.deepEqual(kinds, ['live:tts_speak', 'live:tts_list_voices']);
});
