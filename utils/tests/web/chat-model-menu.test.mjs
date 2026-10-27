// Plan llm-servers 5.1: the Chat model menu, server → model. Groups (This machine, Remote, Cloud) with one header per
// server, the search, local models to load from /api/llm/engines, the cloud badge, `/model` completion, and the load.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const M = await import(pathToFileURL(path.join(root, 'web', 'chat', 'chat-model-menu.js')).href);

const MODELS = { default: 'skynet', models: [
  { id: 'gemma4-26B', server: 'gemma4-26B', group: 'local', provider: 'openai', health: 'healthy', meta: { context_length: 262144, tools: true } },
  { id: 'skynet', server: 'skynet', group: 'remote', provider: 'openai', health: 'healthy', meta: { context_length: 131072, tools: true, vision: true } },
  { id: 'claude/claude-opus-5-5', server: 'claude', group: 'cloud', provider: 'anthropic', cloud: true, health: 'healthy', meta: { context_length: 1000000, reasoning: true } },
  { id: 'claude/claude-haiku-5-5', server: 'claude', group: 'cloud', provider: 'anthropic', cloud: true, meta: {} },
  { id: 'gemini/gemini-3.7-flash', server: 'gemini', group: 'cloud', provider: 'gemini', cloud: true, health: 'failed', meta: {} },
] };
const ENGINES = [
  { id: 'lcpp', name: 'LLM Launcher', running: false, models: [
    { id: 'gemma-4-26b', name: 'Gemma 4 26B', relay_model: 'gemma4-26B', loaded: false, downloaded: true },     // already served: not offered twice
    { id: 'qwen-coder', name: 'Qwen Coder', relay_model: 'qwen-coder', loaded: false, downloaded: true, size_gb: 18, context: 131072 },
    { id: 'big', name: 'Big', loaded: false, downloaded: false }] },                                                 // not downloaded: not offered
  { id: 'vllm', name: 'vLLM', running: true, models: [{ id: 'q3', name: 'Qwen3', relay_model: 'vllm/q3', loaded: true }] },
];

test('groups by where the server runs, then by server, with its health', () => {
  const g = M.menuGroups(MODELS, null);
  assert.deepEqual(g.map(x => x.label), ['This machine', 'Remote', 'Cloud']);
  const cloud = g.find(x => x.id === 'cloud');
  assert.deepEqual(cloud.servers.map(s => [s.name, s.health, s.items.length]), [['claude', 'healthy', 2], ['gemini', 'failed', 1]]);
  assert.equal(M.modelFacts(MODELS.models[1]), '131k · tools · vision');
  const twice = { models: [MODELS.models[0], MODELS.models[0]] };                                   // the relay listed it twice
  assert.equal(M.menuGroups(twice, null)[0].servers[0].items.length, 1);
});

test('local models not loaded are offered with Load, under their engine', () => {
  const l = M.loadables(ENGINES, MODELS.models.map(m => m.id));
  const stopped = M.loadables([{ id: 'lcpp', name: 'LLM Launcher', running: false, models: [] }]);      // stopped: no catalog yet, so Start
  assert.deepEqual(stopped.map(m => [m.id, m.server, m.health, m.start]), [['start:lcpp', 'LLM Launcher', 'stopped', { sid: 'lcpp', engine: 'LLM Launcher' }]]);
  assert.deepEqual(l.map(m => [m.id, m.server, m.health, m.load.sid, m.load.id, m.load.running]), [['qwen-coder', 'LLM Launcher', 'stopped', 'lcpp', 'qwen-coder', false]]);
  const local = M.menuGroups(MODELS, ENGINES).find(x => x.id === 'local');
  assert.deepEqual(local.servers.map(s => s.name), ['gemma4-26B', 'LLM Launcher']);
});

test('the search finds by model, server and provider', () => {
  const ids = q => M.menuGroups(MODELS, ENGINES, q).flatMap(g => g.servers.flatMap(s => s.items.map(m => m.id)));
  assert.deepEqual(ids('claude'), ['claude/claude-opus-5-5', 'claude/claude-haiku-5-5']);
  assert.deepEqual(ids('Gemini'), ['gemini/gemini-3.7-flash']);
  assert.deepEqual(ids('launcher'), ['qwen-coder']);
  assert.deepEqual(ids('nothing here'), []);
});

test('cloud models carry the provider badge; the menu draws it and Load', () => {
  assert.equal(M.cloudBadge(MODELS.models[2]), 'Claude');
  assert.equal(M.cloudBadge(MODELS.models[1]), null);
  const expand = n => (n == null || typeof n !== 'object') ? n : Array.isArray(n) ? n.map(expand)
    : typeof n.type === 'function' ? expand(n.type(n.props)) : { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
  const all = (n, p, o = []) => { if (Array.isArray(n)) n.forEach(x => all(x, p, o)); else if (n && typeof n === 'object') { if (p(n)) o.push(n); all(n.props?.children, p, o); } return o; };
  const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
  const el = expand(M.ModelMenu({ models: MODELS, value: 'skynet', onChange() {} }));
  const rows = all(el, n => n.props?.role === 'menuitemradio');
  assert.equal(rows.length, 0);                                                                   // shut
  const got = [];
  const React0 = globalThis.React.useState;
  globalThis.React.useState = init => [init === false ? true : (typeof init === 'function' ? init() : init), () => {}];   // open
  try {
    const open = expand(M.ModelMenu({ models: MODELS, value: 'skynet', onChange: id => got.push(id) }));
    const items = all(open, n => n.props?.role === 'menuitemradio');
    assert.deepEqual(items.map(r => r.props['aria-checked']), ['false', 'true', 'false', 'false', 'false']);
    assert.match(text(items[2]), /claude\/claude-opus-5-5.*Claude/);
    items[2].props.onClick();
    assert.deepEqual(got, ['claude/claude-opus-5-5']);
    assert.deepEqual(all(open, n => n.props?.role === 'group').map(g => g.props['aria-label']), ['This machine', 'Remote', 'Cloud']);
  } finally { globalThis.React.useState = React0; }
});

test('/model completes server/model', () => {
  assert.deepEqual(M.modelCompletions('/model cla', MODELS).map(c => c.cmd), ['model claude/claude-opus-5-5', 'model claude/claude-haiku-5-5']);
  assert.match(M.modelCompletions('/model opus', MODELS)[0].hint, /claude · Cloud · Claude/);
  assert.equal(M.modelCompletions('/model ', MODELS).length, 5);
  assert.deepEqual(M.modelCompletions('/model skynet', MODELS), []);                              // typed out: nothing to complete
  assert.deepEqual(M.modelCompletions('/mod', MODELS), []);
  assert.equal(M.modelCompletions('/model gem', { models: [MODELS.models[0], MODELS.models[0]] }).length, 1);
});

test('Load starts a stopped engine, loads, and waits for the relay name', async () => {
  const calls = [];
  let running = false, loaded = false, polls = 0;
  const api = {
    startService: async id => { calls.push('start ' + id); running = true; },
    getLlmEngines: async () => { polls++; if (calls.includes('load')) loaded = polls > 4;
      return [{ id: 'lcpp', running, engine: { state: loaded ? 'ready' : 'loading' }, models: [{ id: 'qwen-coder', relay_model: 'qwen-coder', loaded }] }]; },
    loadLlm: async (sid, id, room) => { calls.push('load'); assert.deepEqual([sid, id, room], ['lcpp', 'qwen-coder', false]); },
  };
  const steps = [];
  const id = await M.loadModel(api, { sid: 'lcpp', id: 'qwen-coder', engine: 'LLM Launcher', running: false }, { every: 0, onStep: s => steps.push(s) });
  assert.equal(id, 'qwen-coder');
  assert.deepEqual(calls, ['start lcpp', 'load']);
  assert.deepEqual(steps, ['Starting LLM Launcher…', 'Loading qwen-coder…']);
  const room = Object.assign(new Error('room'), { code: 'needs_room', data: { plan: { unload: [{ id: 'comfy' }] } } });
  await assert.rejects(M.loadModel({ ...api, loadLlm: async () => { throw room; } }, { sid: 'lcpp', id: 'x', engine: 'L', running: true }, { every: 0 }), e => e.code === 'needs_room');
});
