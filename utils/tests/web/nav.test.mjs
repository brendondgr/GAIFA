// Plan 33: the sidebar's model (web/nav/nav-model.js): state buckets, the listed services, counts,
// the groups, the Services page's filters, the monogram, and the nav choices kept whole.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const n = await import(pathToFileURL(path.join(root, 'web/nav/nav-model.js')).href);

const sv = (id, state, o = {}) => ({ id, name: id.toUpperCase(), description: '', state, manifest_errors: [], ...o });
const SVCS = [sv('tts', 'ready'), sv('relay', 'degraded'), sv('lcpp', 'starting'), sv('gen3d', 'stopped'), sv('comfy', 'stopping'),
  sv('web', 'failed'), sv('broken', 'stopped', { manifest_errors: ['service.toml: missing [run].port'] }), sv('agent', 'ready', { description: 'The chat agent' })];

test('each state is active, inactive or failed', () => {
  assert.deepEqual(SVCS.map(n.bucket), ['active', 'active', 'active', 'inactive', 'inactive', 'failed', 'failed', 'active']);
  assert.equal(n.bucket(null), 'failed');
  assert.ok(n.pulses(SVCS[2]) && n.pulses(SVCS[4]) && !n.pulses(SVCS[0]));
  assert.deepEqual(Object.keys(n.BUCKETS), ['active', 'inactive', 'failed']);
});

test('the counts and their words', () => {
  const c = n.counts(SVCS);
  assert.deepEqual(c, { active: 4, inactive: 2, failed: 2, total: 8 });
  assert.equal(n.countsText(c), '4 active · 2 inactive · 2 failed');
  assert.equal(n.countsText(n.counts([sv('a', 'ready')])), '1 active');
  assert.equal(n.countsText(n.counts([])), 'No services');
});

test('the nav is always whole and valid', () => {
  assert.deepEqual(n.normNav(null), n.DEFAULT_NAV);
  assert.deepEqual(n.normNav({ collapsed: 'yes', services: 'tiles', hidden: ['a', 'a', 3], folded: true, extra: 1 }),
    { collapsed: false, services: 'list', hidden: ['a'], folded: true });
  assert.deepEqual(n.normNav({ services: 'counts', collapsed: true }), { ...n.DEFAULT_NAV, services: 'counts', collapsed: true });
  const store = new Map(), ls = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(n.readCache(ls), n.DEFAULT_NAV);
  n.writeCache({ collapsed: true, services: 'button', hidden: ['tts'] }, ls);
  assert.deepEqual(n.readCache(ls), { collapsed: true, services: 'button', hidden: ['tts'], folded: false });
  store.set(n.CACHE_KEY, '{nope'); assert.deepEqual(n.readCache(ls), n.DEFAULT_NAV);
  assert.deepEqual(n.readCache({ getItem() { throw new Error('blocked'); } }), n.DEFAULT_NAV);
});

test('the listed services: all but the hidden ones, new mods shown, removed ids dropped', () => {
  const nav = { hidden: ['gen3d', 'gone'] };
  assert.deepEqual(n.visible(SVCS, nav).map(s => s.id), ['tts', 'relay', 'lcpp', 'comfy', 'web', 'broken', 'agent']);
  assert.deepEqual(n.visible([...SVCS, sv('new-mod', 'ready')], nav).at(-1).id, 'new-mod');
  const hid = n.setHidden(nav, SVCS, 'tts', true);
  assert.deepEqual(hid.hidden, ['gen3d', 'tts']);  // 'gone' isn't installed any more
  assert.deepEqual(n.setHidden(hid, SVCS, 'gen3d', false).hidden, ['tts']);
  assert.equal(n.setAllHidden(nav, SVCS, true).hidden.length, SVCS.length);
  assert.deepEqual(n.setAllHidden(nav, SVCS, false).hidden, []);
});

test('the groups: Overview, Chat, Outputs on top; Memory only with the agent; Models and Settings at the bottom', () => {
  const r = (page, ...parts) => ({ page, parts: [page === 'service' ? 's' : page, ...parts] });
  const g = n.groups(r('outputs'), SVCS);
  assert.deepEqual(g.top.map(x => x.label), ['Overview', 'Chat', 'Outputs']);
  assert.deepEqual(g.bottom.map(x => x.label), ['Memory', 'Models', 'Settings']);
  assert.equal(g.bottom[0].href, '#/s/agent/memory');
  assert.deepEqual(g.top.map(x => x.on), [false, false, true]);
  assert.deepEqual(n.groups(r('overview'), SVCS.filter(s => s.id !== 'agent')).bottom.map(x => x.key), ['models', 'settings']);
  for (const tab of ['memory', 'review', 'learning']) {                   // memory-auto-learning 4.2
    assert.ok(n.groups(r('service', 'agent', tab), SVCS).bottom[0].on, tab);
    assert.ok(!n.serviceOn(r('service', 'agent', tab), 'agent'), tab);
  }
  assert.ok(!n.groups(r('service', 'agent', 'harness'), SVCS).bottom[0].on && n.serviceOn(r('service', 'agent', 'harness'), 'agent'));
  assert.ok(n.serviceOn(r('service', 'agent'), 'agent'));
  assert.ok(n.serviceOn(r('service', 'tts', 'logs'), 'tts') && !n.serviceOn(r('services'), 'tts'));
  assert.ok(n.groups(null, []).top[0].on);  // before the route is known
});

test('the Services page filters by state and words', () => {
  const ids = o => n.filterServices(SVCS, o).map(s => s.id);
  assert.equal(ids({}).length, SVCS.length);
  assert.deepEqual(ids({ filter: 'failed' }), ['web', 'broken']);
  assert.deepEqual(ids({ filter: 'inactive' }), ['gen3d', 'comfy']);
  assert.deepEqual(ids({ q: 'chat AGENT' }), ['agent']);
  assert.deepEqual(ids({ q: 'gen3' }), ['gen3d']);
  assert.deepEqual(ids({ filter: 'active', q: 'gen3' }), []);
});

test('a mod without a logo gets a stable monogram', () => {
  const a = n.monogram('my-mod', 'My Mod');
  assert.deepEqual(a, n.monogram('my-mod', 'My Mod'));
  assert.equal(a.text, 'MM');
  assert.match(a.bg, /^hsl\(\d+ 52% 40%\)$/);
  assert.notEqual(n.monogram('alpha', 'x').bg, n.monogram('beta', 'x').bg);
  assert.equal(n.monogram('speech', 'Speech').text, 'SP');
  assert.equal(n.monogram('x', '').text, 'X');
  assert.equal(n.monogram('3d', '3D Generate').text, '3G');
});

test('every installed mod but the template has its own logo file', () => {
  const dirs = fs.readdirSync(path.join(root, 'services')).filter(d => d !== '_template' && fs.existsSync(path.join(root, 'services', d, 'service.toml')));
  const files = dirs.map(d => fs.readFileSync(path.join(root, 'services', d, 'ui', 'logo.svg'), 'utf8'));
  assert.equal(new Set(files).size, dirs.length);
});

test('tooltips: every fixed item has its words, and a service its state (33.5)', () => {
  const g = n.groups({ page: 'overview', parts: ['overview'] }, SVCS);
  for (const it of [...g.top, ...g.bottom]) assert.ok(it.hint && it.hint === n.HINTS[it.key], it.key);
  assert.equal(n.stateWords(SVCS[0]), 'Ready · Active');
  assert.equal(n.stateWords(SVCS[4]), 'Stopping · Inactive');
  assert.equal(n.stateWords(SVCS[6]), 'Manifest error · Failed');
});

test('calendar 2.2: a badge reads the count up to 9, then 9+', () => {
  assert.deepEqual([0, -1, null, 1, 9, 10, 250].map(n.badgeText), ['', '', '', '1', '9', '9+', '9+']);
});
