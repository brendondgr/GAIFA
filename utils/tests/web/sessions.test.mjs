// Wire 15 (sessions) and Wire 13 (tool runs from the API tab): api.js's session methods, the mock's
// session plan and restore, and the API tab's form → tool arguments.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const { createHttpApi, METHOD_AREA, EVENT_AREA } = await load('api.js');
const { createSessionMocks } = await load('mock-sessions.js');
const { toolArgs } = await load('api-tool.js');
await load('sessions.js');   // imports cleanly

test('api.js: the session methods and their routes', async () => {
  const seen = [];
  const http = createHttpApi('', { fetch: async (url, init) => { seen.push([init.method, url, init.body]); return new Response(init.method === 'DELETE' ? null : '{}', { status: init.method === 'DELETE' ? 204 : 200 }); } });
  await http.listSessions(); await http.saveSession('Image work'); await http.renameSession('ss 1', 'B'); await http.deleteSession('ss_1');
  await http.restoreSession('ss_1', { dryRun: true }); await http.restoreSession('ss_1'); await http.getSessionState();
  assert.deepEqual(seen.map(([m, u]) => `${m} ${u}`), ['GET /api/sessions', 'POST /api/sessions', 'PUT /api/sessions/ss%201', 'DELETE /api/sessions/ss_1',
    'POST /api/sessions/ss_1/restore?dry_run=1', 'POST /api/sessions/ss_1/restore', 'GET /api/sessions/state']);
  assert.equal(seen[1][2], '{"name":"Image work"}');
  for (const m of ['listSessions', 'saveSession', 'renameSession', 'deleteSession', 'restoreSession', 'getSessionState']) assert.equal(METHOD_AREA[m], 'sessions');
  assert.equal(EVENT_AREA.session, 'sessions'); assert.equal(EVENT_AREA.session_step, 'sessions');
});

function fakeHub() {
  const svcs = { relay: ['ready', 'n/a'], lcpp: ['ready', 'loaded'], tts: ['ready', 'unloaded'], gen3d: ['stopped', 'unloaded'], comfy: ['ready', 'loaded'], example: ['stopped', 'n/a'] };
  const list = () => Object.entries(svcs).map(([id, [state, load]]) => ({ id, state, load, manifest_errors: [], memory: { used_bytes: load === 'loaded' ? 20e9 : 0, estimate_bytes: 24e9 } }));
  const calls = [];
  return { calls, api: {
    listServices: async () => list(), getMemory: async () => ({ available_bytes: 60e9, reserve_bytes: 12e9 }),
    startService: async id => { calls.push('start ' + id); svcs[id][0] = 'ready'; }, loadService: async id => { calls.push('load ' + id); svcs[id][1] = 'loaded'; },
    unloadService: async id => { calls.push('unload ' + id); svcs[id][1] = 'unloaded'; },
  } };
}

test('mock sessions: a plan, a restore with step events, save, rename and delete', async () => {
  const events = [], { api, calls } = fakeHub();
  const m = createSessionMocks({ emit: e => events.push(e), net: async () => {}, err: (s, c, d) => Object.assign(new Error(d), { status: s, code: c, detail: d }), later: (ms, fn) => setTimeout(fn, 1), now: () => 1e9, api });
  const list = await m.listSessions();
  assert.equal(list.at(-1).auto, true, 'the auto session is last');
  const image = list.find(s => s.name === 'Image work');
  assert.match(image.summary, /loaded: comfy/);
  const plan = await m.restoreSession(image.id, { dryRun: true });
  assert.equal(plan.dry_run, true);
  assert.deepEqual(plan.steps.map(s => `${s.action} ${s.target}`), ['stop_llm gemma4-26B-7071', 'unload lcpp', 'start gen3d']);
  assert.equal(plan.memory.freed_bytes, 18.6e9 + 20e9);
  assert.equal(plan.memory.fits, true);
  const r = await m.restoreSession(image.id);
  assert.equal(r.ok, true); assert.equal(r.results.length, 3);
  assert.deepEqual(events.filter(e => e.type === 'session_step').map(e => e.step.action), ['stop_llm', 'unload', 'start']);
  assert.deepEqual(calls, ['unload lcpp', 'start gen3d']);
  assert.equal((await m.restoreSession(image.id, { dryRun: true })).steps.length, 0, 'already there');
  const saved = await m.saveSession('Mine');
  assert.ok(events.some(e => e.type === 'session' && e.session.name === 'Mine' && !e.session.snapshot));
  await assert.rejects(m.renameSession(saved.id, 'Image work'), e => e.code === 'conflict');
  assert.equal((await m.renameSession(saved.id, 'Mine 2')).name, 'Mine 2');
  await m.deleteSession(saved.id);
  assert.ok(!(await m.listSessions()).some(s => s.id === saved.id));
  const st = await m.getSessionState();
  assert.equal(st.unclean_shutdown, true); assert.equal(st.last_auto.name, 'Last session');
});

test('API tab: form values → flat tool arguments (numbers cast, nested bodies kept, files left out)', () => {
  const fields = [
    { key: 'p.name', sch: { type: 'string' } }, { key: 'p.n', sch: { type: 'integer' } },
    { key: 'b.prompt', sch: { type: 'string' } }, { key: 'b.budget', group: true }, { key: 'b.budget.faces', sch: { type: 'integer' } },
    { key: 'b.audio', sch: { type: 'string', format: 'binary' } }, { key: 'b.empty', sch: { type: 'string' } }, { key: 'b.tags', sch: { type: 'array' } },
  ];
  assert.deepEqual(toolArgs(fields, { 'p.name': 'Hope', 'p.n': '3', 'b.prompt': 'a fox', 'b.budget.faces': '20000', 'b.audio': 'x.wav', 'b.empty': '', 'b.tags': [] }),
    { name: 'Hope', n: 3, prompt: 'a fox', budget: { faces: 20000 } });
});
