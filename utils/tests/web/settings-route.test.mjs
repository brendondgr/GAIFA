// Plan settings-redesign 2.2: web/settings/route.js, `#/settings/<section>/<group>/<row>` and the old hashes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', 'settings', f)).href);
const R = await load('route.js');
const S = await load('schema.js');
const services = ['relay', 'agent', 'tts'].map(id => ({ id, name: id, manifest_errors: [] }));
const secs = S.sections({ services, hasSessions: true });

test('a three-part hash', () => {
  assert.deepEqual(R.parseSettingsRoute(['machine', 'memory', 'reserve'], secs), { section: 'machine', group: 'memory', row: 'reserve', known: true });
  assert.deepEqual(R.parseSettingsRoute(['permissions', 'judge'], secs), { section: 'permissions', group: 'judge', row: null, known: true });
  assert.equal(R.settingsHash('machine', 'memory', 'reserve'), '#/settings/machine/memory/reserve');
  assert.equal(R.settingsHash('about'), '#/settings/about');
});

test('the old section names are aliases', () => {
  const at = parts => { const r = R.parseSettingsRoute(parts, secs); return [r.section, r.group, r.row].filter(Boolean).join('/'); };
  assert.equal(at(['paths']), 'machine/storage');
  assert.equal(at(['memory']), 'machine/memory');
  assert.equal(at(['memory', 'reserve']), 'machine/memory/reserve');   // an alias names a group: the rest is a row of it
  assert.equal(at(['interface']), 'general/interface');
  assert.equal(at(['agent', 'permissions']), 'permissions');
  assert.equal(at(['about', 'hardware']), 'machine/hardware');
  assert.equal(at(['agent']), 'agent');                          // not an alias on its own
});

test('unknown parts are dropped; no section is General', () => {
  assert.deepEqual(R.parseSettingsRoute([], secs), { section: 'general', group: null, row: null, known: true });
  assert.deepEqual(R.parseSettingsRoute(['nowhere'], secs), { section: 'general', group: null, row: null, known: false });
  assert.deepEqual(R.parseSettingsRoute(['machine', 'nope', 'reserve'], secs), { section: 'machine', group: null, row: null, known: true });
  assert.deepEqual(R.parseSettingsRoute(['machine', 'memory', 'nope'], secs).row, null);
});

test('where you are, in words', () => {
  assert.deepEqual(R.settingsPlace(['machine', 'memory'], secs), ['Machine', 'Memory']);
  assert.deepEqual(R.settingsPlace(['paths'], secs), ['Machine', 'Storage']);
  assert.deepEqual(R.settingsPlace(['services', 'services'], secs), ['Services']);   // a group named as its section
  assert.deepEqual(R.settingsPlace(['about'], secs), ['About']);
});
