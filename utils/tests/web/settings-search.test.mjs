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
