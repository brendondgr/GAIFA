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

// ---------- 2.1: the regrouped sections ----------
const FULL = {
  ...DRAFT,
  learning: { enabled: true, nightly_at: '03:00', idle_min: 60, infer_after: 2, fade_days: 60 },
  speech_input: { mics: ['USB mic'], language: '', preset: 'balanced', mode: 'both' },
  speech_output: { voice: 'Hope', engine: 'auto', speed: 1, auto_read: false, pause_ms: 1200 },
  judge: { backend: 'decide', model: 'gemma4-26B', url: 'u', threshold: 0.35, timeout_s: 3, context: 'none', allow_commands: ['pytest *', 'ls *'], ask_commands: ['git push *'] },
  screen: { pages: true, documents: false, transcripts: false, timeout_s: 30, window_chars: 6000, backend: null, model: null, url: null, threshold: null, confirm: true, parallel: 4 },
  permissions: { deny: [], ask: ['hub_set_preference'], allow: ['hub_start_service'] },
  web: { relevance: 'auto', model: 'd3-lite', url: 'u', candidates: 24, timeout_s: 8 },
  outputs: { hidden_keep_days: 7 },
};
const ALL = [...services, { id: 'agent', name: 'Agent', manifest_errors: [] }, { id: 'stt', name: 'Speech to Text', manifest_errors: [] }];

test('2.1: eight sections in order, with their groups', () => {
  const secs = S.sections({ services: ALL, draft: FULL, hasSessions: true });
  assert.deepEqual(secs.map(s => s.id), ['general', 'machine', 'services', 'agent', 'permissions', 'speech', 'sessions', 'about']);
  const groups = Object.fromEntries(secs.map(s => [s.id, s.groups.map(g => g.id)]));
  assert.deepEqual(groups, {
    general: ['hub', 'interface', 'outputs'], machine: ['memory', 'storage', 'hardware'], services: ['services'],
    agent: ['model', 'documents', 'web', 'instructions', 'memory', 'skills', 'learning'],
    permissions: ['modes', 'rules', 'grants', 'judge', 'screening', 'judged'], speech: ['dictation', 'voice'], sessions: ['sessions'], about: ['versions', 'cli', 'doctor'] });
  assert.ok(secs.every(s => s.groups.length >= 1 && s.groups.length <= 7));
  const rows = S.rowsOf(secs);
  assert.equal(S.rowFor(secs, 'outputs.hidden_keep_days').ref, 'general/outputs/hiddenDays');
  assert.equal(S.rowFor(secs, 'memory.reserve_gb').ref, 'machine/memory/reserve');
  assert.equal(rows.find(r => r.block === 'HardwareCard').section, 'machine');
  for (const k of ['hub.port', 'memory.reserve_gb', 'memory.auto_make_room', 'memory.never_unload', 'memory.priority', 'ui.theme', 'ui.density'])
    assert.ok(rows.some(r => r.key === k), k);   // every Phase 1 row still has a home
  for (const b of ['ProcessCard', 'PathsList', 'MemoryHistory', 'ServicesTable', 'AddModCard', 'Versions', 'CliList', 'DoctorPanel', 'SessionsPanel', 'HardwareCard',
    'ModelsCard', 'DocumentsCard', 'InstructionsCard', 'MemoryCard', 'SkillsCard', 'MicsBlock', 'GrantsList', 'JudgedList'])
    assert.ok(rows.some(r => r.block === b), b);
  assert.equal(S.rowFor(secs, 'permissions.deny').key, 'agent.permissions.deny');
  assert.equal(S.rowFor(secs, 'judge.allow_commands').control, 'list');
  assert.match(S.rowFor(secs, 'judge.allow_commands').check('rm -rf; x').error, /^No shell/);
});

test('2.1: which sections show', () => {
  const ids = c => S.sections(c).map(s => s.id);
  assert.deepEqual(ids({ services: services.filter(s => s.id !== 'tts'), hasSessions: false }), ['general', 'machine', 'services', 'about']);   // no agent, no speech mods, no sessions
  assert.ok(ids({ services: [...services, { id: 'tts', name: 'Speech', manifest_errors: [] }] }).includes('speech'));
});

test('2.1: the summaries render from a fixed draft', () => {
  const ctx = { services: ALL, draft: FULL, theme: 'dark', density: 'compact', nav: { services: 'counts' }, system: { hub: { version: '0.1.0' }, disk: { free_bytes: 500e9, total_bytes: 2000e9 } } };
  const secs = S.sections(ctx), sum = ref => { const [s, g] = ref.split('/'); return S.summaryOf(secs.find(x => x.id === s).groups.find(x => x.id === g), ctx); };
  assert.equal(sum('machine/memory'), 'Reserve 12 GB · auto make room off · 1 never unloaded');
  assert.equal(sum('permissions/judge'), 'gemma4-26B via decide · 3 command rules');
  assert.equal(sum('permissions/rules'), '0 never · 1 ask · 1 allow');
  assert.equal(sum('general/interface'), 'Dark theme · compact · sidebar counts');
  assert.equal(sum('general/outputs'), 'Saved web pages kept 7 days');
  assert.equal(sum('machine/storage'), '500 GB free of 2.0 TB');
  assert.equal(sum('speech/voice'), 'Hope · read every reply off');
  for (const s of secs) for (const g of s.groups) assert.ok(S.summaryOf(g, ctx), `${s.id}/${g.id}`);
});

test('2.1: Save sends only what changed', () => {
  const secs = S.sections({ services: ALL, draft: FULL });
  const d = JSON.parse(JSON.stringify(FULL));
  d.judge.threshold = '0.5'; d.memory.reserve_gb = '14';
  assert.deepEqual(S.saveBody(d, FULL, secs), { memory: { reserve_gb: 14 }, judge: { threshold: 0.5 } });
});

test('4.2: changedRows compares with the defaults: numbers as numbers, chips as sets, orders in order', () => {
  const ctx = { services: ALL, draft: FULL, theme: 'dark', density: 'compact', nav: { services: 'list', folded: false } };
  const secs = S.sections(ctx);
  const defaults = JSON.parse(JSON.stringify(FULL));
  defaults.ui.theme = 'system';
  assert.deepEqual(S.changedRows(secs, FULL, defaults, ctx).map(c => c.ref), ['general/interface/theme']);   // instant rows read ctx
  const d = JSON.parse(JSON.stringify(FULL));
  d.memory.reserve_gb = '12';                            // the same number as a string
  d.memory.never_unload = ['lcpp'];
  defaults.memory.never_unload = ['lcpp'];
  d.memory.priority = ['relay', 'tts', 'lcpp'];          // reordered
  d.judge.allow_commands = ['ls *', 'pytest *'];          // a list in another order is a change too
  d.web.relevance = 'off';
  const ch = S.changedRows(secs, d, defaults, ctx);
  assert.deepEqual(ch.map(c => c.ref), ['general/interface/theme', 'machine/memory/priority', 'agent/web/relevance', 'permissions/judge/allowCommands']);
  assert.deepEqual(ch.find(c => c.path === 'web.relevance'), { ref: 'agent/web/relevance', section: 'agent', group: 'web', row: 'relevance', path: 'web.relevance', key: 'agent.web.relevance', value: 'off', default: 'auto' });
  const chips = S.rowFor(secs, 'memory.never_unload');
  assert.equal(S.sameValue(chips, ['a', 'b'], ['b', 'a']), true);
  const m = S.changedMatch(ch);
  assert.deepEqual(m.perSection, { general: 1, machine: 1, agent: 1, permissions: 1 });
  assert.equal(S.changedRows(secs, d, null, ctx).length, 0);   // no defaults yet: nothing to compare
  assert.equal(S.showValue(S.rowFor(secs, 'web.relevance'), 'auto'), 'Automatic');
  assert.equal(S.showValue(S.rowFor(secs, 'memory.reserve_gb'), 12), '12 GB');
  assert.equal(S.showValue(S.rowFor(secs, 'memory.auto_make_room'), false), 'off');
  assert.equal(S.showValue(S.rowFor(secs, 'permissions.deny'), []), 'none');
});
