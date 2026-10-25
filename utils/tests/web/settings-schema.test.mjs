// Plan settings-redesign: web/settings/schema.js, the Settings page as data. Imported without a DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const S = await import(pathToFileURL(path.join(root, 'web', 'settings', 'schema.js')).href);

const services = [{ id: 'relay', name: 'LLM Relay', manifest_errors: [] }, { id: 'lcpp', name: 'LLM Launcher', manifest_errors: [] },
  { id: 'tts', name: 'Speech', manifest_errors: [] }, { id: 'broken', name: 'Broken', manifest_errors: ['bad port'] }];
const ctx = { services };
const DRAFT = {
  hub: { port: 7000 },
  memory: { reserve_gb: 12, auto_make_room: false, never_unload: ['lcpp'], priority: ['tts', 'relay', 'lcpp'] },
  services: { order: ['relay', 'lcpp', 'tts'], enabled: { relay: true, lcpp: true, tts: true }, autostart: { relay: true, lcpp: false, tts: true } },
  ui: { theme: 'system', density: 'compact', dashboard: { order: [], hidden: [], ranges: {} }, nav: { collapsed: false, services: 'list', hidden: [], folded: false } },
};

test('the rows: every key the page edits has a row, with its config.toml key', () => {
  const secs = S.sections(ctx), rows = S.rowsOf(secs);
  const keys = new Set(rows.flatMap(r => [r.key, ...(r.keys || [])]).filter(Boolean));
  for (const k of ['hub.port', 'memory.reserve_gb', 'memory.auto_make_room', 'memory.never_unload', 'memory.priority',
    'services.order', 'services.enabled', 'services.autostart', 'ui.theme', 'ui.density']) assert.ok(keys.has(k), k);
  assert.ok(rows.every(r => r.ref === `${r.section}/${r.group}/${r.id}`));
  assert.equal(new Set(rows.map(r => r.ref)).size, rows.length, 'refs are unique');
  const res = rows.find(r => r.key === 'memory.reserve_gb');
  assert.equal(res.get(DRAFT), 12);
  assert.equal(S.rowFor(secs, 'memory.reserve_gb').ref, res.ref);
  assert.equal(S.rowAt(secs, res.ref).label, 'Reserve');
  assert.equal(S.rowAt(secs, 'nope/x/y'), null);
  // choices come from the services, broken mods left out
  assert.deepEqual(rows.find(r => r.key === 'memory.never_unload').choices.map(c => c.value), ['relay', 'lcpp', 'tts']);
  assert.deepEqual(rows.find(r => r.key === 'memory.priority').items(DRAFT).map(i => [i.id, i.note]), [['tts', ''], ['relay', ''], ['lcpp', 'never unloaded']]);
});

test('config keys: the agent tables live under [agent]', () => {
  assert.equal(S.configKey('judge.threshold'), 'agent.judge.threshold');
  assert.equal(S.configKey('permissions.deny'), 'agent.permissions.deny');
  assert.equal(S.configKey('memory.reserve_gb'), 'memory.reserve_gb');
  const d = {}; S.setPath(d, 'a.b.c', 1); assert.deepEqual(d, { a: { b: { c: 1 } } }); assert.equal(S.getPath(d, 'a.x.c'), undefined);
});

test('validateDraft: the port and reserve rules, with the page’s messages', () => {
  const secs = S.sections(ctx);
  assert.deepEqual(S.validateDraft(secs, DRAFT), {});
  const bad = { ...DRAFT, hub: { port: 80 }, memory: { ...DRAFT.memory, reserve_gb: 99 } };
  assert.deepEqual(S.validateDraft(secs, bad), { 'hub.port': 'Use a port between 1024 and 65535', 'memory.reserve_gb': 'Between 0 and 64 GB' });
  assert.deepEqual(S.validateDraft(secs, { ...DRAFT, hub: { port: '70x0' }, memory: { ...DRAFT.memory, reserve_gb: '' } }),
    { 'hub.port': S.PORT_MSG, 'memory.reserve_gb': S.RESERVE_MSG });
});

test('dirty and the save body: ui applies at once and is never sent', () => {
  const d = JSON.parse(JSON.stringify(DRAFT));
  assert.equal(S.isDirty(DRAFT, d), false);
  d.ui.theme = 'dark'; assert.equal(S.isDirty(DRAFT, d), false);
  d.hub.port = '7001'; assert.equal(S.isDirty(DRAFT, d), true);
  const body = S.saveBody(d);
  assert.equal(body.hub.port, 7001); assert.equal('ui' in body, false);
});
