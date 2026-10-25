// Plan settings-redesign 3.1–3.3, 5.2: web/settings/search.js, the index, the matcher, highlighting, the palette's rows.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', 'settings', f)).href);
const Q = await load('search.js');
const S = await load('schema.js');
const services = ['relay', 'agent', 'tts', 'stt'].map(id => ({ id, name: id, manifest_errors: [] }));
const draft = { web: { relevance: 'auto' }, memory: {}, judge: {} };
const secs = S.sections({ services, draft, hasSessions: true });
const ix = Q.indexRows(secs, { services, draft });

test('the reserve is found by its label, a synonym and its key', () => {
  for (const q of ['reserve', 'RAM', 'reserve_gb', '  Reserve  ']) assert.ok(Q.matches(ix, q).ids.has('machine/memory/reserve'), q);
  const m = Q.matches(ix, 'reserve_gb');
  assert.deepEqual(m.rows.map(r => r.id), ['machine/memory/reserve']);
  assert.deepEqual(m.perSection, { machine: 1 }); assert.deepEqual(m.perGroup, { 'machine/memory': 1 });
});

test('counts per section; one character finds nothing', () => {
  const m = Q.matches(ix, 'memory');
  assert.ok(m.perSection.machine >= 2 && m.perSection.agent >= 1, JSON.stringify(m.perSection));
  assert.ok(m.ids.has('machine/memory') && m.ids.has('agent/memory'));   // both groups' titles
  assert.equal(Object.values(m.perSection).reduce((a, b) => a + b, 0), m.rows.length);
  assert.equal(Q.matches(ix, 'm').rows.length, 0); assert.equal(Q.matches(ix, '').rows.length, 0);
  assert.ok(Q.matches(ix, 'judge').ids.has('permissions/judge'));
  assert.ok(Q.matches(ix, 'dark mode').ids.has('general/interface/theme'));
  assert.ok(Q.matches(ix, 'VRAM').ids.has('machine/hardware/hardware'));
  assert.ok(Q.matches(ix, 'MCP').ids.has('sessions/sessions/sessions'));
});

test('highlight keeps the case and splits around each match', () => {
  assert.deepEqual(Q.highlight('Memory reserve', 'mem'), [{ text: 'Mem', hit: true }, { text: 'ory reserve', hit: false }]);
  assert.deepEqual(Q.highlight('a-b-a', 'a-'), [{ text: 'a-', hit: true }, { text: 'b-a', hit: false }]);
  assert.deepEqual(Q.highlight('Never', 'x'), [{ text: 'Never', hit: false }]);
  assert.deepEqual(Q.highlight('Reserve reserve', 'reserve').map(p => p.hit), [true, false, true]);
});

test('3.3: the palette’s rows, one per group and per setting, with the hash', () => {
  const rows = Q.paletteRows(ix);
  const reserve = rows.find(r => r.id === 'machine/memory/reserve');
  assert.deepEqual(reserve, { label: 'Reserve', sub: 'Settings › Machine › Memory · memory.reserve_gb', hash: '#/settings/machine/memory/reserve', id: 'machine/memory/reserve' });
  const judge = rows.find(r => r.id === 'permissions/judge');
  assert.deepEqual(judge, { label: 'Settings › Permissions › Auto judge', sub: 'Settings', hash: '#/settings/permissions/judge', id: 'permissions/judge' });
  assert.equal(rows.find(r => r.id === 'general/hub/process').sub, 'Settings › General › Hub');   // a block: no key
  assert.equal(new Set(rows.map(r => r.hash)).size, rows.length);
});

test('5.2: the mods in search: "tts" offers its Settings tab under Mods', () => {
  const svcs = [{ id: 'tts', name: 'LocalTTS', manifest_errors: [] }, { id: 'relay', name: 'LLM Relay', manifest_errors: [] }];
  const index = Q.indexRows(S.sections({ services: svcs, draft }), { services: svcs, draft });
  const m = Q.matches(index, 'tts');
  const mod = index.find(e => e.id === 'mods/tts');
  assert.ok(m.ids.has('mods/tts'));
  assert.equal(mod.label, 'LocalTTS settings'); assert.equal(mod.hash, '#/s/tts/settings'); assert.equal(mod.section, 'mods');
  assert.equal(m.perSection.mods, 1);
  assert.ok(Q.matches(index, 'services/relay').ids.has('mods/relay'));
  assert.ok(Q.matches(index, 'localtts').ids.has('mods/tts'));
  assert.deepEqual(Q.paletteRows(index).find(r => r.id === 'mods/tts'), { label: 'LocalTTS settings', sub: 'Settings › Mods', hash: '#/s/tts/settings', id: 'mods/tts' });
  assert.ok(!S.sections({ services: svcs }).some(s => s.id === 'mods'));   // never in the section list
});
