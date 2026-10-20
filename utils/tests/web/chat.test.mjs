// web/chat/: the Chat page's pure parts (plan 14.1): the Markdown renderer's escaping, the thread
// view built from events, the card registry's fallback, the actions registry and its derivation
// from the tool catalog, slash commands, the live client's error parsing, and the scripted mock
// agent end to end (question → parameter card → result with outputs).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const md = await load('chat/chat-md.js');
const th = await load('chat/chat-thread.js');
const cards = await load('chat/chat-cards.js');
const acts = await load('chat/chat-actions.js');
const composer = await load('chat/chat-composer.js');
const capi = await load('chat/chat-api.js');
const cmock = await load('chat/chat-mock.js');
const tmock = await load('mock-tools.js');
await load('chat/chat.js');            // every module of the page imports cleanly (no DOM at import time)
await load('chat/chat-settings.js');
await load('chat/chat-approvals.js');

test('markdown escapes HTML and keeps only safe links', () => {
  const out = md.renderMarkdown('<script>alert(1)</script> & <img src=x onerror=alert(1)>');
  assert.ok(!out.includes('<script>') && !out.includes('<img'), out);
  assert.ok(out.includes('&lt;script&gt;') && out.includes('&amp;'));
  assert.equal(md.renderMarkdown('[x](javascript:alert(1))').includes('href'), false);
  assert.ok(md.renderMarkdown('[docs](https://example.com/a?b=1&c=2)').includes('<a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">docs</a>'));
  assert.ok(md.renderMarkdown('see "https://x.dev/" now').includes('&quot;'));
  const attr = md.renderMarkdown('[a](https://x.dev/"onmouseover="alert(1))');
  assert.ok(!/href="[^"]*"onmouseover/.test(attr), attr);
});

test('markdown blocks and inline spans', () => {
  assert.equal(md.renderMarkdown('**bold** and *it* and `a<b`'), '<p><strong>bold</strong> and <em>it</em> and <code>a&lt;b</code></p>');
  assert.equal(md.renderMarkdown('- one\n- two\n\n1. a\n2. b'), '<ul><li>one</li><li>two</li></ul><ol><li>a</li><li>b</li></ol>');
  assert.equal(md.renderMarkdown('```js\nconst x = "<b>";\n```'), '<pre data-lang="js"><code>const x = &quot;&lt;b&gt;&quot;;</code></pre>');
  assert.equal(md.renderMarkdown('`**not bold**`'), '<p><code>**not bold**</code></p>');
  assert.equal(md.renderMarkdown('line one\nline two'), '<p>line one<br>line two</p>');
  assert.equal(md.renderMarkdown('## Title\n---'), '<h4>Title</h4><hr>');
  assert.equal(md.renderMarkdown('```\nunclosed'), '<pre><code>unclosed</code></pre>');  // while streaming
});

const ev = (seq, type, payload) => ({ thread_id: 't', seq, ts: seq, type, payload });

test('buildView folds tool calls, approvals, questions and results into cards', () => {
  const out = { n: 1, output_id: 'o1', kind: 'image', title: 'fox' };
  const events = [
    ev(1, 'user', { text: 'fox please' }),
    ev(2, 'thinking', { text: 'hmm', seconds: 2, step: 's1' }),
    ev(3, 'assistant', { text: 'Choices first', step: 's1' }),
    ev(4, 'tool_call', { id: 'q1', name: 'ask_user', arguments: {}, step: 's1' }),
    ev(5, 'question', { id: 'q1', questions: [{ question: 'Style?', options: [{ label: 'A' }, { label: 'B' }] }] }),
    ev(6, 'answer', { id: 'q1', answers: { 'Style?': 'A' } }),
    ev(7, 'tool_result', { id: 'q1', name: 'ask_user', status: 'done', content: '{}' }),
    ev(8, 'tool_call', { id: 'c1', name: 'comfy_generate_image', arguments: { prompt: 'fox' }, step: 's2' }),
    ev(9, 'approval', { id: 'c1', approval_id: 'ap1', tool: 'comfy_generate_image', arguments: { prompt: 'fox' }, ask_fields: ['aspect'], schema: {} }),
    ev(10, 'decision', { id: 'c1', approval_id: 'ap1', approve: true }),
    ev(11, 'call', { id: 'c1', call_id: 'call1' }),
    ev(12, 'tool_result', { id: 'c1', name: 'comfy_generate_image', status: 'done', outputs: [out] }),
    ev(13, 'tool_call', { id: 'c2', name: 'hub_memory_status', arguments: {}, step: 's3' }),
    ev(14, 'todos', { items: [{ text: 'a', state: 'done' }, { text: 'b', state: 'pending' }] }),
    ev(15, 'usage', { prompt_tokens: 10 }), ev(16, 'state', { state: 'running' }),
    ev(17, 'brand_new_event', { x: 1 }),
  ];
  const v = th.buildView(events, { deltas: { s4: { text: 'stream', thinking: 'th' } }, progress: { c2: { id: 'c2', progress: 0.5 } } });
  assert.deepEqual(v.items.map(i => i.kind), ['user', 'thinking', 'assistant', 'question', 'approval', 'result', 'tool', 'todos', 'brand_new_event', 'thinking', 'assistant']);
  const q = v.items[3], ap = v.items[4], tool = v.items[6];
  assert.equal(q.answer.answers['Style?'], 'A');
  assert.equal(ap.decision.approve, true); assert.equal(ap.run.call_id, 'call1'); assert.equal(ap.result.status, 'done');
  assert.equal(tool.progress.progress, 0.5);
  assert.deepEqual(v.outputs.map(o => o.output_id), ['o1']);
  assert.equal(v.state, 'running'); assert.equal(v.lastSeq, 17); assert.equal(v.pending.length, 0);
  assert.ok(v.items.at(-1).streaming);
  assert.equal(th.todosOpen(v.todos), true);
  // a pending approval and an unanswered question are "pending"
  const p = th.buildView([ev(1, 'tool_call', { id: 'c', name: 'x', arguments: {} }), ev(2, 'approval', { id: 'c', approval_id: 'a', tool: 'x' }),
    ev(3, 'tool_call', { id: 'q', name: 'ask_user' }), ev(4, 'question', { id: 'q', questions: [] })]);
  assert.deepEqual(p.pending.map(i => i.kind), ['approval', 'question']);
});

test('live deltas, progress and replays merge without duplicates', () => {
  let live = { deltas: {}, progress: {}, meter: null };
  live = th.applyTransient(live, { type: 'delta', seq: null, payload: { kind: 'text', text: 'Hel', step: 's' } });
  live = th.applyTransient(live, { type: 'delta', seq: null, payload: { kind: 'text', text: 'lo', step: 's' } });
  assert.equal(live.deltas.s.text, 'Hello');
  live = th.settleLive(live, ev(5, 'assistant', { text: 'Hello', step: 's' }));
  assert.deepEqual(live.deltas, {});
  live = th.applyTransient(live, { type: 'context', payload: { used: 5, window: 10 } });
  assert.equal(live.meter.used, 5);
  const merged = th.mergeEvents([ev(1, 'user', {}), ev(2, 'assistant', {})], [ev(2, 'assistant', {}), ev(3, 'note', {})]);
  assert.deepEqual(merged.map(e => e.seq), [1, 2, 3]);
  // a queued message keeps its chip until the model writes again
  const v = th.buildView([ev(1, 'user', { text: 'a' }), ev(2, 'user', { text: 'b', queued: true })]);
  assert.equal(v.items[1].queued, true);
  assert.equal(th.buildView([ev(1, 'user', { text: 'b', queued: true }), ev(2, 'assistant', { text: 'ok', step: 'x' })]).items[0].queued, false);
});

test('the card registry falls back to the generic card and takes per-tool cards', () => {
  assert.equal(cards.cardFor({ kind: 'something_new' }), cards.GenericCard);
  assert.notEqual(cards.cardFor({ kind: 'user' }), cards.GenericCard);
  for (const k of ['user', 'assistant', 'approval', 'question', 'result', 'todos', 'memory', 'note', 'error', 'compact', 'toolform']) assert.ok(cards.hasCard(k), k);
  assert.ok(!cards.hasCard('tool') && !cards.hasCard('thinking'), 'tool calls and thinking are rows in the activity fold (plan 19.4)');
  const Mine = () => null, off = cards.registerCard('step:gen3d_make_3d', Mine);
  assert.ok(cards.hasCard('step:gen3d_make_3d'));
  assert.equal(cards.cardFor({ kind: 'step', call: { name: 'gen3d_make_3d' } }), Mine);
  assert.notEqual(cards.cardFor({ kind: 'step', call: { name: 'other' } }), Mine);
  off();
  assert.notEqual(cards.cardFor({ kind: 'step', call: { name: 'gen3d_make_3d' } }), Mine);
  assert.throws(() => cards.registerCard('x', 'not a component'));
});

const TOOLS = [
  { name: 'comfy_animate_image', mod: 'comfy', risk: 'generate', parameters: { properties: { image: { 'x-kind': 'image' }, prompt: {} }, required: ['image', 'prompt'] } },
  { name: 'comfy_edit_image', mod: 'comfy', risk: 'generate', parameters: { properties: { image: { 'x-kind': 'image' } } } },
  { name: 'comfy_upscale_image', mod: 'comfy', risk: 'generate', parameters: { properties: { image: { 'x-kind': 'image' }, mask: { 'x-kind': 'image' } }, required: ['image'] } },
  { name: 'tts_clone_voice', mod: 'tts', risk: 'write', parameters: { properties: { audio: { 'x-kind': 'audio' } } } },
  { name: 'gen3d_delete_job', mod: 'gen3d', risk: 'destructive', parameters: { properties: { glb: { 'x-kind': 'mesh' } } } },
  { name: 'gen3d_make_3d', mod: 'gen3d', risk: 'generate', parameters: { properties: { prompt: {} } } },
  { name: 'hub_get_output', mod: 'hub', risk: 'read', parameters: { properties: { file: { 'x-kind': 'image' } } } },
  { name: 'comfy_generate_image', mod: 'comfy', risk: 'generate', parameters: { properties: { prompt: {} } } },
];

test('actions: built-ins by kind, hidden without their tool, plus ones derived from the catalog', () => {
  const ids = (kind, tools) => acts.actionsFor(kind, { tools }).map(a => a.id);
  // no catalog yet: only prompt and attach actions
  assert.deepEqual(ids('image', null), ['image.describe', 'image.reference']);
  const img = ids('image', TOOLS);
  assert.deepEqual(img.slice(0, 2), ['image.animate', 'image.edit']);
  assert.ok(!img.includes('image.removebg'), 'its tool is not in the catalog');
  assert.ok(img.includes('image.make3d'));
  assert.ok(img.includes('tool:comfy_upscale_image'), 'derived from the x-kind file input');
  assert.ok(!img.includes('tool:comfy_animate_image') && !img.includes('tool:comfy_edit_image'), 'deduped with built-ins');
  assert.ok(!img.includes('tool:hub_get_output'), 'hub tools are not result actions');
  assert.deepEqual(ids('audio', TOOLS), ['tool:tts_clone_voice']);
  assert.deepEqual(ids('model3d', TOOLS), ['model3d.rig'], 'destructive tools are never derived');
  assert.deepEqual(ids('composer', TOOLS), ['quick.image', 'quick.3d', 'quick.edit'], 'quick actions whose tool is missing are hidden');
  const up = acts.actionsFor('image', { tools: TOOLS }).find(a => a.id === 'tool:comfy_upscale_image');
  assert.equal(up.label, 'Upscale image');
  assert.deepEqual(up.args({ output_id: 'o9', n: 2 }), { image: { $file: 'output:o9' } });
  assert.equal(acts.fileInputFor(TOOLS[2], 'image'), 'image', 'required file input first');
});

test('actions: registering, running and validation', () => {
  const off = acts.registerAction({ id: 'test.x', on: 'image', label: 'X', prompt: o => `do #${o.n}`, order: 1 });
  assert.equal(acts.actionsFor('image', { tools: [] })[0].id, 'test.x');
  const calls = [];
  const ctx = { sendPrompt: t => calls.push(['prompt', t]), openTool: (t, a) => calls.push(['tool', t, a]), attach: o => calls.push(['attach', o.n]) };
  const out = { output_id: 'o1', n: 3, kind: 'image' };
  for (const a of acts.actionsFor('image', { tools: TOOLS })) if (['test.x', 'image.animate', 'image.reference'].includes(a.id)) acts.runAction(a, out, ctx);
  assert.deepEqual(calls, [['prompt', 'do #3'], ['tool', 'comfy_animate_image', { image: { $file: 'output:o1' } }], ['attach', 3]]);
  off();
  assert.ok(!acts.actionsFor('image', { tools: [] }).some(a => a.id === 'test.x'));
  assert.throws(() => acts.registerAction({ id: 'bad', on: 'image', label: 'Nothing to do' }));
});

test('slash commands: built-ins and skills', () => {
  assert.deepEqual(composer.slashMatches('/', []).map(c => c.cmd), ['compact', 'clear', 'model', 'context']);
  assert.deepEqual(composer.slashMatches('/co', [{ name: 'comfy', description: 'workflows' }]).map(c => c.cmd), ['compact', 'context', 'comfy']);
  assert.deepEqual(composer.slashMatches('/model gemma', []), []);
  assert.deepEqual(composer.slashMatches('hello /c', []), []);
});

test('the live client parses the agent\'s and the hub\'s error shapes', async () => {
  const res = (status, body) => new Response(JSON.stringify(body), { status });
  let e = await capi.errorFrom(res(422, { detail: { code: 'invalid_arguments', detail: 'megapixels: too big', data: { problems: [1] } } }));
  assert.deepEqual([e.status, e.code, e.detail, e.data.problems.length], [422, 'invalid_arguments', 'megapixels: too big', 1]);
  e = await capi.errorFrom(res(503, { detail: 'Agent is not running', code: 'service_not_running' }));
  assert.deepEqual([e.code, e.detail], ['service_not_running', 'Agent is not running']);
  e = await capi.errorFrom(res(422, { detail: [{ loc: ['body', 'text'], msg: 'field required' }] }));
  assert.equal(e.detail, 'text: field required');
  e = await capi.errorFrom(res(409, { detail: 'a turn is running' }));
  assert.equal(e.detail, 'a turn is running');
  const seen = [];
  const live = capi.createLiveClient({ base: 'http://h', fetch: async (url, init) => { seen.push([init.method, url, init.body]); return res(202, { ok: 1 }); } });
  await live.action('t 1', 'comfy_edit_image', { image: { $file: 'output:o' } });
  assert.deepEqual(seen[0], ['POST', 'http://h/api/s/agent/v1/threads/t%201/action', '{"tool":"comfy_edit_image","arguments":{"image":{"$file":"output:o"}}}']);
});

test('the scripted mock agent: question, parameter card, result, actions, fork', async () => {
  const events = [], api = {
    listOutputs: async ({ kind }) => ({ items: [{ id: 'o_' + kind, kind, title: kind + ' one', service: 'comfy', url: 'data:,x', preview: 'data:,p', meta: {} }] }),
    ...tmock.createToolMocks({ emit: () => {}, net: async () => {}, err: (s, c, d) => Object.assign(new Error(d), { status: s, code: c, detail: d }), later: (ms, fn) => setTimeout(fn, 1), now: () => Date.now() / 1000 }),
  };
  const c = cmock.createMockClient(api, { speed: 200 });
  const until = async (pred, what) => { for (let i = 0; i < 400; i++) { const e = events.find(pred); if (e) return e; await new Promise(r => setTimeout(r, 5)); } throw new Error('timed out waiting for ' + what); };
  const t = await c.create({});
  const s = c.stream(t.id, 0, { onEvent: e => events.push(e) });
  await c.send(t.id, 'make me an image of a fox');
  const q = await until(e => e.type === 'question', 'the question');
  assert.equal(q.payload.questions.length, 3);
  assert.ok(events.some(e => e.type === 'delta' && e.seq === null), 'text streams as deltas');
  await until(e => e.type === 'state' && e.payload.state === 'waiting', 'waiting');
  await c.answer(t.id, q.payload.id, { [q.payload.questions[0].question]: 'Watercolor', [q.payload.questions[1].question]: '1:1' });
  const ap = await until(e => e.type === 'approval', 'the parameter card');
  assert.equal(ap.payload.arguments.workflow, 'zimage-intorealism');
  assert.ok(ap.payload.schema.properties.aspect);
  await assert.rejects(c.approval(t.id, { approval_id: ap.payload.approval_id, approve: true, arguments: { ...ap.payload.arguments, megapixels: 9 } }), e => e.status === 422);
  await c.approval(t.id, { approval_id: ap.payload.approval_id, approve: true, arguments: ap.payload.arguments });
  const res = await until(e => e.type === 'tool_result' && e.payload.outputs, 'the result');
  assert.deepEqual([res.payload.outputs[0].n, res.payload.outputs[0].kind, res.payload.outputs[0].output_id], [1, 'image', 'o_image']);
  await until(e => e.type === 'state' && e.payload.state === 'idle', 'idle');
  await c.action(t.id, 'comfy_animate_image', { image: { $file: 'output:o_image' }, prompt: 'blink' });
  const vid = await until(e => e.type === 'tool_result' && e.payload.name === 'comfy_animate_image', 'the action result');
  assert.equal(vid.payload.outputs[0].kind, 'video'); assert.equal(vid.payload.outputs[0].n, 2);
  const fork = await c.fork(t.id, res.seq);
  const fevs = await c.events(fork.id);
  assert.equal(fevs.at(-1).type, 'tool_result');
  assert.ok((await c.threads()).some(x => x.id === fork.id));
  s.close();
});

test('mock tools: catalog, approvals and decisions', async () => {
  const emitted = [], m = tmock.createToolMocks({ emit: e => emitted.push(e), net: async () => {}, err: (s, c, d, data) => Object.assign(new Error(d), { status: s, code: c, detail: d, data }), later: (ms, fn) => setTimeout(fn, 1), now: () => 1000 });
  const ix = await m.getToolIndex();
  assert.ok(ix.find(t => t.name === 'tts_speak').risk === 'generate');
  assert.equal((await m.listApprovals()).length, 2);   // an MCP card and an execute card (plan 25.3)
  const r = await m.callTool('comfy_generate_image', { prompt: 'fox' }, { mode: 'ask' });
  assert.equal(r.status, 'needs_approval');
  await assert.rejects(m.decideApproval(r.approval_id, { approve: true, args: { megapixels: 9 } }), e => e.code === 'invalid_arguments');
  const d = await m.decideApproval(r.approval_id, { approve: true, args: { aspect: '16:9' } });
  assert.equal(d.status, 'running');
  await assert.rejects(m.decideApproval(r.approval_id, { approve: false }), e => e.code === 'already_decided');
  assert.ok(emitted.some(e => e.type === 'approval' && e.approval.state === 'approved'));
  assert.equal((await m.callTool('comfy_generate_image', { prompt: 'x' }, { mode: 'auto' })).status, 'running');
  await assert.rejects(m.listTools({ names: 'nope' }), e => e.code === 'unknown_tool');
});

test('uploads from the composer: which files qualify, chips, and per-file errors', async () => {
  const f = (name, type) => ({ name, type });
  assert.deepEqual(composer.uploadable([f('a.png', 'image/png'), f('b.txt', 'text/plain'), f('c.MOV', ''), f('d.wav', 'audio/wav'), f('e.exe', ''), null]).map(x => x.name), ['a.png', 'b.txt', 'c.MOV', 'd.wav']);
  assert.deepEqual(composer.uploadable(undefined), []);
  const api = { uploadOutput: async file => {
    if (file.name === 'bad.png') throw Object.assign(new Error('x'), { detail: 'too large' });
    return { id: 'o_' + file.name, kind: 'image', title: file.name, url: '/api/outputs/o/file', preview: null };
  } };
  const r = await composer.uploadAll(api, [f('cat.png', 'image/png'), f('bad.png', 'image/png')]);
  assert.deepEqual(r.chips, [{ id: 'o_cat.png', kind: 'image', title: 'cat.png', preview: '/api/outputs/o/file' }]);
  assert.deepEqual(r.errors, ['bad.png: too large']);
  assert.deepEqual(composer.toChip({ id: 'o1', kind: 'audio', title: 't', url: '/u', preview: null }), { id: 'o1', kind: 'audio', title: 't', preview: null });
});

test('the live thread event: the agent sends the thread itself, older mocks wrapped it', () => {
  assert.deepEqual(th.threadOf({ id: 't1', title: 'Fox' }), { id: 't1', title: 'Fox' });
  assert.deepEqual(th.threadOf({ thread: { id: 't1', title: 'Fox' } }), { id: 't1', title: 'Fox' });
  assert.equal(th.threadOf({}), null);
  assert.equal(th.threadOf(null), null);
});

test('the mock agent plays the design study turn: lookups, an image, a 3D approval, the answer (plan 19.1)', async () => {
  const events = [], api = {
    listOutputs: async ({ kind }) => ({ items: [{ id: 'o_' + kind, kind, title: kind + ' one', service: 'comfy', url: 'data:,x', preview: 'data:,p', meta: {} }] }),
    ...tmock.createToolMocks({ emit: () => {}, net: async () => {}, err: (s, c, d) => Object.assign(new Error(d), { status: s, code: c, detail: d }), later: (ms, fn) => setTimeout(fn, 1), now: () => Date.now() / 1000 }),
  };
  const c = cmock.createMockClient(api, { speed: 400 });
  const until = async (pred, what) => { for (let i = 0; i < 600; i++) { const e = events.find(pred); if (e) return e; await new Promise(r => setTimeout(r, 5)); } throw new Error('timed out waiting for ' + what); };
  const t = await c.create({});
  let ready = null; const isReady = new Promise(r => { ready = r; });
  const s = c.stream(t.id, 0, { onEvent: e => events.push(e), onReady: () => ready() });
  await isReady;
  await c.send(t.id, 'Make me a samurai character, then turn it into a 3D model.');
  const ap = await until(e => e.type === 'approval', 'the 3D approval');
  assert.equal(ap.payload.tool, 'gen3d_make_3d');
  assert.equal(ap.payload.arguments.engine, 'trellis2');
  assert.equal(ap.payload.arguments.image, 'output:o_image');
  const stored = events.filter(e => e.seq != null && !['state', 'usage'].includes(e.type)).map(e => e.type + (e.payload.name ? ':' + e.payload.name : ''));
  assert.deepEqual(stored, ['user', 'thinking', 'tool_call:find_tools', 'tool_call:load_tools', 'tool_result:find_tools', 'tool_result:load_tools',
    'thinking', 'assistant', 'tool_call:comfy_generate_image', 'call', 'tool_result:comfy_generate_image', 'thinking', 'assistant', 'tool_call:gen3d_make_3d', 'approval']);
  const steps = events.filter(e => e.type === 'tool_call').map(e => e.payload.step);
  assert.equal(steps[0], steps[1], 'the lookups share a step');
  assert.ok(events.some(e => e.type === 'delta' && e.payload.kind === 'thinking'), 'thinking streams');
  assert.ok(events.some(e => e.type === 'progress'), 'the image reports progress');
  assert.ok(events.some(e => e.type === 'thread' && th.threadOf(e.payload)?.title), 'the title arrives live');
  await c.approval(t.id, { approval_id: ap.payload.approval_id, approve: true, arguments: ap.payload.arguments });
  const res = await until(e => e.type === 'tool_result' && e.payload.name === 'gen3d_make_3d', 'the 3D result');
  assert.equal(res.payload.outputs[0].kind, 'model3d');
  await until(e => e.type === 'state' && e.payload.state === 'idle', 'idle');
  assert.match(events.filter(e => e.type === 'assistant').at(-1).payload.text, /#1.*#2/s);
  s.close();
});
