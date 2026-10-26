// Settings → LLMs (plan llm-servers 4.1): servers grouped by where they run, key and health states, what
// "Add a server" sends for each preset and a URL, the summaries, the engine rows, and the section's place.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { render, all, text, find } from './tinyreact.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const V = await load('settings/llm-view.js');
const B = await load('settings/blocks-llm.js');
const S = await load('settings/schema.js');

const EPS = [
  { id: 'a', name: 'Claude', alias: 'claude', kind: 'cloud', protocol: 'anthropic', has_key: true, key_hint: '…abcd', health: 'healthy' },
  { id: 'b', name: 'OpenAI', alias: 'openai', kind: 'cloud', protocol: 'openai', has_key: false, health: 'failed' },
  { id: 'c', name: 'gemma4-26B-7071', alias: 'gemma4-26B', kind: 'local', protocol: 'openai', owner: 'lcpp', health: 'healthy' },
  { id: 'd', name: 'skynet', alias: 'skynet', kind: 'remote_tunnel', protocol: 'openai', health: 'unknown' },
  { id: 'e', name: 'opencode', alias: 'agent', kind: 'local', protocol: 'opencode', has_key: true },
];

test('groups by where a server runs', () => {
  assert.deepEqual(V.grouped(EPS).map(g => [g.id, g.items.map(e => e.id)]), [['local', ['c']], ['remote', ['d']], ['cloud', ['a', 'b']], ['agent', ['e']]]);
  assert.deepEqual(V.grouped([]), []);
});

test('key and health states', () => {
  assert.deepEqual(V.keyState(EPS[0]), { tone: 'green', text: 'key …abcd' });
  assert.deepEqual(V.keyState(EPS[1]), { tone: 'red', text: 'no key' });
  assert.deepEqual(V.keyState(EPS[2]), { tone: 'dim', text: 'no key needed' });
  assert.equal(V.healthState(EPS[1]).text, 'failing');
  assert.equal(V.healthState({ health: 'unknown', enabled: false }).text, 'off');
});

test('what Add a server sends', () => {
  assert.deepEqual(V.addBody({ preset: 'anthropic', key: ' sk-ant-1 ' }), { body: { name: 'Anthropic (Claude)', preset: 'anthropic', upstream_key: 'sk-ant-1' } });
  assert.deepEqual(V.addBody({ preset: 'gemini', key: 'AIza1', name: 'Work', alias: 'g' }), { body: { name: 'Work', preset: 'gemini', upstream_key: 'AIza1', alias: 'g' } });
  assert.match(V.addBody({ preset: 'openai' }).error, /needs an API key/);
  assert.deepEqual(V.addBody({ preset: 'url', url: 'http://10.0.0.4:8000/v1', alias: 'box' }),
    { body: { name: '10.0.0.4:8000/v1', base_url: 'http://10.0.0.4:8000/v1', alias: 'box', list_models: true } });
  assert.match(V.addBody({ preset: 'url', url: 'ftp://x' }).error, /http/);
  assert.match(V.addBody({ preset: 'url', url: 'http://x/v1', alias: 'a/b' }).error, /short name/);
  assert.match(V.addBody({}).error, /Pick a provider/);
});

test('summaries and model facts', () => {
  assert.equal(V.serversSummary(EPS), '5 servers · 2 cloud · 1 failing');
  assert.equal(V.serversSummary(null), 'The relay’s servers');
  assert.equal(V.enginesSummary([{ models: [{ loaded: true }, { loaded: false }] }, { models: [] }]), '2 engines · 1 model loaded');
  assert.equal(V.enginesSummary([]), 'No engine mods');
  assert.equal(V.modelFacts({ size_gb: 16.99, context: 262144, format: 'gguf' }), '17 GB · 262k context · GGUF');
  assert.equal(V.modelFacts({ size_gb: 0.1, memory_gb: 40, context: 512, format: 'hf' }), '0.1 GB · needs 40 GB · 512 context · HF');
});

test('Add a server draws a provider choice and a key field', () => {
  const t = render(B.AddLlmServer({ ctx: { api: {} } }));
  const sel = find(t, n => n.type === 'select');
  assert.deepEqual(all(sel, n => n.type === 'option').map(o => o.props.value), ['anthropic', 'openai', 'gemini', 'url']);
  assert.equal(find(t, n => n.type === 'input' && n.props['aria-label'] === 'API key').props.type, 'password');
  assert.match(text(t), /picked as claude\/<model>\. Cloud models answer chats only/);
});

test('engines without the hub route say so', () => {
  assert.match(text(render(B.LlmEngines({ ctx: { api: {} } }))), /doesn’t serve \/api\/llm/);
});

test('the section sits between Services and Agent', () => {
  const secs = S.sections({ services: [{ id: 'relay' }, { id: 'agent' }], llm: { endpoints: EPS, engines: [] } });
  assert.deepEqual(secs.map(s => s.id).slice(0, 4), ['general', 'machine', 'services', 'llms']);
  const llms = secs.find(s => s.id === 'llms');
  assert.deepEqual(llms.groups.map(g => g.id), ['servers', 'add', 'engines', 'defaults']);
  assert.equal(llms.groups[0].summary({}), '5 servers · 2 cloud · 1 failing');
  assert.ok(!S.sections({ services: [{ id: 'agent' }] }).some(s => s.id === 'llms'));        // no relay: no section
  for (const r of S.rowsOf(secs).filter(r => r.control === 'block' && r.section === 'llms')) assert.ok(B.LLM_BLOCKS[r.block], r.block);
});

test('the settings search finds the section by provider and engine', async () => {
  const Q = await load('settings/search.js');
  const services = [{ id: 'relay' }, { id: 'agent' }].map(s => ({ ...s, name: s.id, manifest_errors: [] }));
  const secs = S.sections({ services, draft: { web: {}, memory: {}, judge: {} } });
  const ix = Q.indexRows(secs, { services });
  for (const q of ['Claude', 'API key', 'OpenAI', 'Gemini', 'llama.cpp', 'vLLM'])
    assert.ok(Q.matches(ix, q).rows.some(r => r.section === 'llms' || r.id.startsWith('llms/')), q);
});
