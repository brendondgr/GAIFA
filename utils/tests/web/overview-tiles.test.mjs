// web/overview-tiles.js and web/overview-day.js (plan overview-bento 2.1–2.2): the Overview tiles' rows.
import './tinyreact.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const t = await load('overview-tiles.js');
const d = await load('overview-day.js');

const svc = (id, o = {}) => ({ id, name: id.toUpperCase(), state: 'ready', load: 'n/a', memory: { used_bytes: 0.1e9 }, stats: [], manifest_errors: [], ...o });

test('Needs you: failures first, then approvals, warnings and memories to review', () => {
  const rows = t.needsRows({
    alerts: [{ id: 'w', level: 'warn', text: 'Disk low' }, { id: 'e', level: 'error', text: 'Speech failed to start', service: 'tts', action: { label: 'Logs', route: '#/s/tts/logs' } }],
    services: [svc('tts', { state: 'failed' }), svc('vllm', { state: 'failed', last_error: 'exit 1' }), svc('bad', { manifest_errors: ['port missing'] })],
    approvals: [{ tool: 'web_fetch' }, { tool: 'web_fetch' }, { tool: 'calendar_add' }], memReview: 3,
  });
  assert.deepEqual(rows.map(r => r.key), ['a:e', 'f:vllm', 'f:bad', 'ap', 'a:w', 'mem']);   // tts's failure is already its alert
  assert.equal(rows[1].href, '#/s/vllm/logs');
  assert.equal(rows[2].text, 'BAD has a manifest error');
  assert.equal(rows[3].text, '3 approvals waiting');
  assert.equal(rows[3].sub, 'web_fetch, calendar_add');
  assert.equal(rows[5].text, '3 memories to review');
  assert.deepEqual(t.needsRows({}), []);
  assert.equal(t.needsRows({ memReview: 1 })[0].text, '1 memory to review');
});

test('Running now: running jobs, then queued, then models in memory', () => {
  const rows = t.runningRows({
    jobs: [{ id: 'q', state: 'queued', label: 'Later', service: 'comfy' }, { id: 'r', state: 'running', label: 'Image', service: 'comfy', progress: 0.4, route: '#/s/comfy' }, { id: 'd', state: 'done', label: 'Old' }],
    services: [svc('comfy'), svc('lcpp', { load: 'loaded', memory: { used_bytes: 18.6e9 } }), svc('tts', { load: 'loading', memory: { used_bytes: 2e9 } })],
  });
  assert.deepEqual(rows.map(r => r.key), ['j:r', 'j:q', 'm:lcpp', 'm:tts']);
  assert.equal(rows[0].status, '40%');
  assert.equal(rows[0].sub, 'COMFY');
  assert.equal(rows[1].progress, null);
  assert.equal(rows[2].status, '18.6 GB');
  assert.equal(rows[3].sub, 'loading');
});

test('the memory bar: the three largest users over 0.5 GB, then the rest, never past the total', () => {
  const memory = { total_bytes: 100e9, used_bytes: 60e9, reserve_bytes: 12e9, other_bytes: 20e9,
    by_service: [{ id: 'a', used_bytes: 20e9 }, { id: 'b', used_bytes: 10e9 }, { id: 'c', used_bytes: 5e9 }, { id: 'd', used_bytes: 3e9 }, { id: 'e', used_bytes: 0.1e9 }] };
  const m = t.memorySplit(memory, [svc('a'), svc('b'), svc('c'), svc('d'), svc('e')]);
  assert.deepEqual(m.segs.map(s => s.key), ['a', 'b', 'c', 'rest']);
  assert.equal(m.segs[3].bytes, 25e9);
  assert.equal(m.free, 40e9);
  assert.equal(m.reservePct, 88);
  assert.equal(m.segs[0].label, 'A');
  // only small users: one "In use" segment
  const small = t.memorySplit({ total_bytes: 130e9, used_bytes: 25e9, by_service: [{ id: 'a', used_bytes: 0.06e9 }] }, []);
  assert.deepEqual(small.segs.map(s => [s.key, s.label]), [['rest', 'In use']]);
  assert.equal(small.reservePct, null);
  // a reading past the total doesn't make free negative
  assert.equal(t.memorySplit({ total_bytes: 10, used_bytes: 12, by_service: [] }, []).free, 0);
  assert.equal(t.memorySplit(null), null);
});

test('Services: problems first, then the busy ones by memory, the rest folded', () => {
  const list = [svc('idle'), svc('stopped', { state: 'stopped' }), svc('big', { memory: { used_bytes: 20e9 } }), svc('loaded', { load: 'loaded', memory: { used_bytes: 5e9 } }),
    svc('starting', { state: 'starting' }), svc('failed', { state: 'failed' }), svc('mf', { manifest_errors: ['x'] })];
  const r = t.serviceRows(list);
  assert.deepEqual(r.top.map(s => s.id), ['failed', 'mf', 'starting', 'big', 'loaded']);
  assert.deepEqual(r.rest.map(s => s.id), ['idle', 'stopped']);
  assert.deepEqual(r.counts, { ready: 4, stopped: 1, failed: 2, total: 7 });
  assert.deepEqual(t.serviceRows([]).top, []);
});

test('Today: overdue, all-day, then by time; past and now marked; tasks due today only', () => {
  const now = new Date(2026, 10, 10, 15, 45).getTime() / 1000;   // Nov 10, 15:45 local
  const at = (h, m = 0, day = 10) => new Date(2026, 10, day, h, m).getTime() / 1000;
  const rows = d.todayRows({ now,
    agenda: { items: [
      { id: 'late', kind: 'event', title: 'Evening', start: '2026-11-10T19:00', end: '2026-11-10T20:00' },
      { id: 'mtg', kind: 'event', title: 'Meeting', start: '2026-11-10T15:30', end: '2026-11-10T16:30', calendar: 'Work' },
      { id: 'am', kind: 'event', title: 'Standup', start: '2026-11-10T09:00', end: '2026-11-10T09:15' },
      { id: 'hol', kind: 'event', title: 'Holiday', start: '2026-11-10', end: '2026-11-11', all_day: true },
      { id: 'td', kind: 'todo', title: 'Send draft', due: '2026-11-10T17:00' },
      { id: 'done', kind: 'todo', title: 'Done thing', due: '2026-11-10T10:00', done: true },
      { id: 'undated', kind: 'todo', title: 'Someday', due: null },
    ], overdue_todos: [{ id: 'od', kind: 'todo', title: 'Taxes', due: '2026-11-08T12:00' }] },
    tasks: [{ id: 'k1', name: 'Digest', enabled: true, next_due: at(18) }, { id: 'k2', name: 'Off', enabled: false, next_due: at(17) },
      { id: 'k3', name: 'Tomorrow', enabled: true, next_due: at(9, 0, 11) }, { id: 'k4', name: 'None', enabled: true, next_due: null }] });
  assert.deepEqual(rows.map(r => r.key), ['o:od', 'i:hol', 'i:undated', 'i:am', 'i:mtg', 'i:td', 't:k1', 'i:late']);
  const by = Object.fromEntries(rows.map(r => [r.key, r]));
  assert.ok(by['i:am'].past && !by['i:am'].now);
  assert.ok(by['i:mtg'].now && !by['i:mtg'].past);
  assert.equal(by['i:mtg'].time, '15:30');
  assert.equal(by['i:hol'].time, 'all day');
  assert.equal(by['o:od'].time, 'overdue');
  assert.equal(by['t:k1'].href, '#/chat/tasks/k1');
  assert.deepEqual(d.todayRows({ agenda: { items: [] }, now }), []);
  assert.deepEqual(d.todayRows({ agenda: null, tasks: [], now }), []);
});

test('the next task is the earliest one that is on', () => {
  const now = 1000;
  assert.deepEqual(d.nextTask([{ id: 'a', name: 'A', enabled: true, next_due: 5000 }, { id: 'b', name: 'B', enabled: true, next_due: 2000 }, { id: 'c', name: 'C', enabled: false, next_due: 1500 }], now), { id: 'b', name: 'B', ts: 2000 });
  assert.equal(d.nextTask([], now), null);
});

test('Recent chats: top-level ones, with their state', () => {
  const rows = d.chatRows([
    { id: 't1', title: 'One', state: 'idle', updated: 10 }, { id: 't2', title: '', state: 'waiting', updated: 9 },
    { id: 'sub', title: 'Child', parent_id: 't1', updated: 8 }, { id: 't3', title: 'Three', state: 'idle', updated: 7 }, { id: 'arc', title: 'Old', archived: true },
  ], [{ id: 't3', service: 'agent', state: 'running' }]);
  assert.deepEqual(rows.map(r => [r.id, r.title, r.state]), [['t1', 'One', null], ['t2', 'New chat', 'waiting'], ['t3', 'Three', 'running']]);
  assert.equal(d.chatRows(Array.from({ length: 20 }, (_, i) => ({ id: 'x' + i })), [], 8).length, 8);
});

test('ages read now, minutes, hours, days', () => {
  assert.equal(d.ago(1000, 1030), 'now');
  assert.equal(d.ago(1000, 1000 + 4 * 60), '4m');
  assert.equal(d.ago(1000, 1000 + 3 * 3600), '3h');
  assert.equal(d.ago(1000, 1000 + 2 * 86400), '2d');
});

test('capability-enablement 3.5: recommended mods that are not set up, once, until Not now', () => {
  const ns = (id, o = {}) => svc(id, { state: 'stopped', recommended: true, availability: { status: 'not_set_up' }, ...o });
  const services = [ns('web'), ns('decide'), svc('calendar', { recommended: true, availability: { status: 'on' } }), svc('stt', { availability: { status: 'not_set_up' } })];
  const [row] = t.needsRows({ services });
  assert.equal(row.text, '2 recommended mods not set up');
  assert.equal(row.sub, 'WEB, DECIDE');
  assert.deepEqual(row.setup, ['web', 'decide']);
  assert.equal(row.action, 'Set up');
  assert.deepEqual(t.needsRows({ services, setupNotNow: ['web', 'decide'] }), [], 'Not now: gone');
  assert.equal(t.needsRows({ services, setupNotNow: ['web'] }).length, 1, 'a new one brings it back');
});
