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
  // numbered items split by bullets, a paragraph or blank lines keep counting
  assert.equal(md.renderMarkdown('1. a\n- x\n\nNote.\n\n2. b\n\n3. c'), '<ol><li>a</li></ol><ul><li>x</li></ul><p>Note.</p><ol start="2"><li>b</li></ol><ol start="3"><li>c</li></ol>');
  assert.equal(md.renderMarkdown('0. zero\n7) seven'), '<ol start="0"><li>zero</li><li>seven</li></ol>');
  assert.equal(md.renderMarkdown('```js\nconst x = "<b>";\n```'), '<div class="aichat-code"><div class="aichat-code-bar"><span>js</span><button type="button" class="aichat-copy" title="Copy code">Copy</button></div>'
    + '<pre data-lang="js"><code><span class="k">const</span> x = <span class="s">&quot;&lt;b&gt;&quot;</span>;</code></pre></div>');
  assert.equal(md.renderMarkdown('`**not bold**`'), '<p><code>**not bold**</code></p>');
  assert.equal(md.renderMarkdown('line one\nline two'), '<p>line one<br>line two</p>');
  assert.equal(md.renderMarkdown('## Title\n---'), '<h4>Title</h4><hr>');
  assert.ok(md.renderMarkdown('```\nunclosed').endsWith('<pre><code>unclosed</code></pre></div>'));  // while streaming
});

test('markdown tables: cells, alignment, escaping, ragged rows, pipes in code', () => {
  const t = md.renderMarkdown('Boots:\n\n| Kind | Weight | Dries |\n|:---|---:|:-:|\n| **Leather** | 1.4 kg | slow |\n| Synthetic <b> | 0.9 kg |\n| `a|b` | x \\| y | z | extra |\n\nAfter.');
  assert.ok(t.startsWith('<p>Boots:</p><div class="aichat-table"><table><thead><tr><th>Kind</th><th style="text-align:right">Weight</th><th style="text-align:center">Dries</th></tr></thead><tbody>'), t);
  assert.ok(t.includes('<tr><td><strong>Leather</strong></td><td style="text-align:right">1.4 kg</td><td style="text-align:center">slow</td></tr>'), t);
  assert.ok(t.includes('<td>Synthetic &lt;b&gt;</td><td style="text-align:right">0.9 kg</td><td style="text-align:center"></td>'), t);   // short row padded
  assert.ok(t.includes('<td><code>a|b</code></td><td style="text-align:right">x | y</td><td style="text-align:center">z</td></tr>'), t);   // extra cell dropped
  assert.ok(t.endsWith('</tbody></table></div><p>After.</p>'), t);
  assert.ok(!md.renderMarkdown('a | b\nnot a delimiter').includes('<table>'));
  assert.equal(md.renderMarkdown('| only | head |\n|---|---|'), '<div class="aichat-table"><table><thead><tr><th>only</th><th>head</th></tr></thead></table></div>');
  assert.equal(md.renderMarkdown('## T\n---'), '<h4>T</h4><hr>');   // a bare --- is still a rule
});

test('code blocks: tilde fences, info strings, aliases and an escaped language', () => {
  const py = md.renderMarkdown('~~~py title="x.py"\ndef f(): return "<x>"  # hi\n~~~');
  assert.ok(py.includes('<span>py</span>') && py.includes('<span class="k">def</span>') && py.includes('<span class="c"># hi</span>') && py.includes('&quot;&lt;x&gt;&quot;'), py);
  const four = md.renderMarkdown('````md\n```js\nx\n```\n````');   // a longer fence holds a shorter one
  assert.ok(four.includes('<code>```js\nx\n```</code>'), four);
  const diff = md.renderMarkdown('```diff\n-old\n+new\n```');
  assert.ok(diff.includes('<span class="d">-old</span>\n<span class="s">+new</span>'), diff);
  assert.ok(md.renderMarkdown('```SQL\nSELECT 1\n```').includes('<span class="k">SELECT</span>'));
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
  assert.deepEqual(ids('image', null), ['image.describe', 'image.reference', 'image.download', 'image.copy']);   // + plan 48.4's (Save to… needs the workspace)
  const img = ids('image', TOOLS);
  assert.deepEqual(img.slice(0, 2), ['image.animate', 'image.edit']);
  assert.ok(!img.includes('image.removebg'), 'its tool is not in the catalog');
  assert.ok(img.includes('image.make3d'));
  assert.ok(img.includes('tool:comfy_upscale_image'), 'derived from the x-kind file input');
  assert.ok(!img.includes('tool:comfy_animate_image') && !img.includes('tool:comfy_edit_image'), 'deduped with built-ins');
  assert.ok(!img.includes('tool:hub_get_output'), 'hub tools are not result actions');
  assert.deepEqual(ids('audio', TOOLS), ['tool:tts_clone_voice', 'audio.download', 'audio.copy']);
  assert.deepEqual(ids('model3d', TOOLS), ['model3d.rig', 'model3d.download', 'model3d.copy'], 'destructive tools are never derived');
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
  assert.deepEqual(composer.slashMatches('/', []).map(c => c.cmd), ['compact', 'clear', 'model', 'context', 'clear-gpu']);
  assert.deepEqual(composer.slashMatches('/clear', []).map(c => c.cmd), ['clear', 'clear-gpu']);   // plan 46.2
  assert.deepEqual(composer.slashMatches('/co', [{ name: 'comfy', description: 'workflows' }]).map(c => c.cmd), ['compact', 'context', 'comfy']);
  assert.deepEqual(composer.slashMatches('/model gemma', []), []);
  assert.deepEqual(composer.slashMatches('hello /c', []), []);
  // skill-sources 2.3: a workspace folder's skill is /<folder>:<name>, found by either part, its folder in the hint
  const ws = composer.chatSkills([{ name: 'comfy', description: 'workflows' }],
    [{ id: 'gaifa:plan', name: 'plan', description: 'Write plans', folder: { id: 'gaifa', name: 'GAIFA' } }]);
  assert.equal(ws[1].source, 'workspace');
  const pl = composer.slashMatches('/pl', ws);
  assert.deepEqual(pl.map(c => [c.cmd, c.hint]), [['gaifa:plan', 'GAIFA: Write plans']]);
  assert.deepEqual(composer.slashMatches('/gaifa:', ws).map(c => c.cmd), ['gaifa:plan']);
  // mcp-client 4.1: an MCP server is its own tool group in the composer
  assert.equal(composer.groupOf({ mod: 'mcp', group: 'mcp:blender' }), 'mcp:blender');
  assert.equal(composer.groupOf({ mod: 'comfy' }), 'comfy');
  assert.equal(composer.groupLabel('mcp:blender'), 'blender (MCP server)');
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

test('pictures in a reply: this chat\'s outputs only (plan 47.3)', async () => {
  const mdm = await import(pathToFileURL(path.join(root, 'web/chat/chat-md.js')).href);
  mdm.setChatOutputs([{ n: 1, output_id: 'aaaaaaaaaaaa', kind: 'image', title: 'Fox', url: '/api/outputs/aaaaaaaaaaaa/file' },
    { n: 2, output_id: 'bbbbbbbbbbbb', kind: 'video', title: 'Clip', url: '/api/outputs/bbbbbbbbbbbb/file', preview: '/api/outputs/bbbbbbbbbbbb/preview' },
    { n: 3, output_id: 'cccccccccccc', kind: 'image', title: 'Evil', url: 'https://evil.example/x.png' }]);
  const img = mdm.renderMarkdown('Here: ![The fox](#1) done');
  assert.ok(img.includes('<img src="/api/outputs/aaaaaaaaaaaa/file" alt="The fox"') && img.includes('data-open="aaaaaaaaaaaa"') && img.includes('#1</span>The fox'), img);
  assert.ok(img.includes('data-src="![The fox](#1)"'));
  assert.ok(mdm.renderMarkdown('![](output:bbbbbbbbbbbb)').includes('<video src="/api/outputs/bbbbbbbbbbbb/file" poster='));
  assert.ok(!mdm.renderMarkdown('![x](#9)').includes('<img'));                                    // not this chat's
  assert.ok(!mdm.renderMarkdown('![x](https://evil.example/a.png)').includes('<img'));            // no outside pictures
  assert.ok(!mdm.renderMarkdown('![x](#3)').includes('evil.example'));                            // an output's outside URL isn't used
  mdm.setChatOutputs([]);
});

test('a reply\'s pictures are drawn once: a figure line is its result card, the turn\'s own outputs left out', async () => {
  // seen 2026-10-25 (chat t_e07a0ebfb485): the picture just made was in the output strip and again in the reply
  const mdm = await import(pathToFileURL(path.join(root, 'web/chat/chat-md.js')).href);
  const text = 'Made it.\n\n![The robot](#1)\n\nAnd the older one: ![Fox](output:bbbbbbbbbbbb) here.\n\n```\n![not a figure](#1)\n```\n![x](#2)';
  assert.deepEqual(mdm.splitFigures(text).map(p => p.ref ?? p.text.trim().split('\n')[0]), ['Made it.', '#1', 'And the older one: ![Fox](output:bbbbbbbbbbbb) here.', '#2']);
  assert.deepEqual(mdm.splitFigures(text)[1], { ref: '#1', caption: 'The robot', src: '![The robot](#1)' });
  assert.equal(mdm.splitFigures('![a](#1)')[0].ref, '#1');
  mdm.setChatOutputs([{ n: 1, output_id: 'aaaaaaaaaaaa', kind: 'image', title: 'Robot', url: '/api/outputs/aaaaaaaaaaaa/file' },
    { n: 2, output_id: 'bbbbbbbbbbbb', kind: 'image', title: 'Fox', url: '/api/outputs/bbbbbbbbbbbb/file' }]);
  assert.equal(mdm.outputByRef('output:bbbbbbbbbbbb').n, 2);
  const hide = new Set(['bbbbbbbbbbbb']);
  assert.ok(!mdm.renderMarkdown('see ![Fox](#2) here', { hide }).includes('<img'), 'a picture the turn shows is left out');
  assert.ok(!mdm.renderMarkdown('see ![Fox](#2) here', { hide }).includes('![Fox]'), 'not left as text either');
  assert.ok(mdm.renderMarkdown('see ![Robot](#1) here', { hide }).includes('<img'));
  assert.ok(mdm.renderMarkdown('see ![Fox](#2) here').includes('<img'), 'hide lasts one render');
  mdm.setChatOutputs([]);
});

test('each chat\'s reply draws its own #n: renderMarkdown takes the chat\'s outputs (chat-split plan 1.1)', async () => {
  const mdm = await import(pathToFileURL(path.join(root, 'web/chat/chat-md.js')).href);
  const a = [{ n: 1, output_id: 'aaaaaaaaaaaa', kind: 'image', title: 'Robot', url: '/api/outputs/aaaaaaaaaaaa/file' }];
  const b = [{ n: 1, output_id: 'cccccccccccc', kind: 'image', title: 'Cat', url: '/api/outputs/cccccccccccc/file' }];
  mdm.setChatOutputs(b);                                                     // the last pane that rendered
  assert.ok(mdm.renderMarkdown('![x](#1)', { outputs: a }).includes('aaaaaaaaaaaa'), 'its own chat\'s #1');
  assert.ok(mdm.renderMarkdown('![x](#1)').includes('cccccccccccc'), 'the fallback is back after the render');
  assert.ok(!mdm.renderMarkdown('![x](#1)', { outputs: [] }).includes('<img'), 'a chat without outputs draws none');
  mdm.setChatOutputs([]);
});

test('a new chat and its first message in one call, and the message body (chat-responsive 1.2)', async () => {
  assert.deepEqual(capi.messageBody('hi', [], {}, [{ text: 'q', seq: 3 }], [], 'c-1'),
    { text: 'hi', attachments: [], quotes: [{ text: 'q', reply: '', seq: 3 }], client_id: 'c-1' });
  assert.deepEqual(capi.messageBody('hi'), { text: 'hi', attachments: [] });
  const c = cmock.createMockClient({}, { speed: 400 });
  const plain = await c.create({});
  assert.equal(plain.event, undefined);
  const t = await c.create({ mode: 'auto', message: capi.messageBody('hello', [], {}, [], [], 'c-2') });
  assert.equal(t.mode, 'auto'); assert.equal(t.event.type, 'user'); assert.equal(t.event.payload.client_id, 'c-2');
  assert.equal((await c.events(t.id)).find(e => e.type === 'user').payload.text, 'hello');
  await c.cancel(t.id);
});

test('projects on the mock: list, sort, pins, defaults on a new chat, move in and out, sources, groups, delete (plan projects 1.3)', async () => {
  const c = cmock.createMockClient({}, { speed: 400 });
  const seen = [];
  const watch = c.watchProjects(ev => seen.push(ev));
  const list = await c.projects();
  assert.deepEqual(list.map(p => p.name), ['Thesis', 'Garden planner']);                 // Thesis is pinned
  const thesis = list[0];
  assert.ok(thesis.pinned && thesis.chats === 2 && thesis.source_count === 4);
  assert.deepEqual((await c.projects({ sort: 'name' })).map(p => p.name), ['Thesis', 'Garden planner']);
  await c.patchProject(thesis.id, { pinned: false });
  assert.deepEqual((await c.projects({ sort: 'name' })).map(p => p.name), ['Garden planner', 'Thesis']);
  assert.deepEqual((await c.projects({ q: 'plant' })).map(p => p.name), ['Garden planner']);
  const full = await c.project(thesis.id);
  assert.deepEqual(full.sources.map(s => s.kind), ['file', 'file', 'page', 'page']);
  assert.equal(full.sources[3].status, 'error');
  // a new chat takes the project's defaults; the request's own settings win
  const t = await c.create({ settings: { project: thesis.id } });
  assert.equal(t.model, 'skynet'); assert.equal(t.mode, 'accept_edits');
  assert.deepEqual(t.settings, { project: thesis.id, environment: 'thesis', disabled: ['comfy'] });
  const t2 = await c.create({ mode: 'plan', settings: { project: thesis.id, disabled: [] } });
  assert.equal(t2.mode, 'plan'); assert.deepEqual(t2.settings.disabled, []);
  assert.equal((await c.projectThreads(thesis.id)).filter(t => !t.settings?.task).length, 4);   // and the Thesis backup task's run chat (scheduled-tasks 4.1)
  // moving in sets the primary environment only; out keeps it
  const plain = await c.create({ model: 'gemma4-26B', settings: { environment: 'notes' } });
  let moved = await c.patch(plain.id, { settings: { project: thesis.id } });
  assert.equal(moved.settings.environment, 'thesis'); assert.equal(moved.model, 'gemma4-26B');
  moved = await c.patch(plain.id, { settings: { project: null } });
  assert.equal(moved.settings.project, undefined); assert.equal(moved.settings.environment, 'thesis');
  assert.ok((await c.threads({ project: 'none' })).some(x => x.id === plain.id));
  const groups = await c.threadGroups({ by: 'project' });
  assert.equal(groups.find(g => g.project === thesis.id).count, 5);                                // with the backup task's run chat
  assert.ok(groups.some(g => g.project === 'none'));
  // sources: add a page, refresh it, change its freshness, reorder, remove
  const page = await c.addSource(thesis.id, { kind: 'page', url: 'https://example.com/a' });
  assert.equal(page.max_age_s, 3600);
  await assert.rejects(c.addSource(thesis.id, { kind: 'page', url: 'https://example.com/a' }), e => e.code === 'exists');
  const fresh = await c.refreshSource(thesis.id, page.id);
  assert.equal(fresh.status, 'ok');
  assert.equal((await c.patchSource(thesis.id, page.id, { max_age_s: null, position: 0 })).max_age_s, null);
  assert.equal((await c.project(thesis.id)).sources[0].id, page.id);
  await c.removeSource(thesis.id, page.id);
  assert.equal((await c.project(thesis.id)).sources.length, 4);
  assert.ok(seen.some(e => e.type === 'project_source' && e.source.status === 'fetching'));
  // a new project, then delete: its chats become ordinary chats
  const p = await c.createProject({ name: ' Trip ', environments: ['default'] });
  assert.equal(p.name, 'Trip');
  await assert.rejects(c.createProject({ name: ' ' }), e => e.code === 'bad_name');
  const done = await c.deleteProject(thesis.id);
  assert.equal(done.chats, 5);                                           // with the backup task's run chat (scheduled-tasks 4.1)
  assert.equal((await c.get(t.id)).settings.project, undefined);
  await assert.rejects(c.project(thesis.id), e => e.status === 404);
  assert.equal(seen.at(-1).type, 'project'); assert.equal(seen.at(-1).project, null);
  watch.close();
});

test('projects on the live client: the routes it calls (plan projects 1.3)', async () => {
  const calls = [];
  const f = async (u, o = {}) => { calls.push(`${o.method || 'GET'} ${u}${o.body ? ' ' + o.body : ''}`); return { ok: true, status: 200, text: async () => '{}' }; };
  const c = capi.createLiveClient({ fetch: f, EventSource: null });
  await c.projects({ q: 'th', sort: 'name' }); await c.projects();
  await c.createProject({ name: 'A' }); await c.patchProject('p_1', { pinned: true }); await c.deleteProject('p_1');
  await c.projectThreads('p_1', { limit: 5 }); await c.threads({ project: 'none' }); await c.threadGroups({ by: 'project' });
  await c.addSource('p_1', { kind: 'page', url: 'u' }); await c.refreshSource('p_1', 'src_1'); await c.removeSource('p_1', 'src_1');
  assert.deepEqual(calls, ['GET /api/s/agent/v1/projects?q=th&sort=name', 'GET /api/s/agent/v1/projects', 'POST /api/s/agent/v1/projects {"name":"A"}',
    'PATCH /api/s/agent/v1/projects/p_1 {"pinned":true}', 'DELETE /api/s/agent/v1/projects/p_1', 'GET /api/s/agent/v1/projects/p_1/threads?limit=5',
    'GET /api/s/agent/v1/threads?project=none', 'GET /api/s/agent/v1/threads/groups?by=project',
    'POST /api/s/agent/v1/projects/p_1/sources {"kind":"page","url":"u"}', 'POST /api/s/agent/v1/projects/p_1/sources/src_1/refresh',
    'DELETE /api/s/agent/v1/projects/p_1/sources/src_1']);
});

// Plan chat-history 1.2: live chats, archived chats or both, and how many there are.
test('the client asks for archived: all and the count; the mock answers the same way', async () => {
  const seen = [];
  const live = capi.createLiveClient({ base: 'http://h', fetch: async url => { seen.push(url); return new Response('{"count": 3}', { status: 200, headers: { 'content-type': 'application/json' } }); } });
  await live.threads({ archived: 'all', limit: 20 });
  await live.threads({ archived: false });
  await live.threadGroups({ archived: 'all' });
  assert.equal((await live.threadCount({ q: 'fox', archived: true, environment: 'default,none' })).count, 3);
  assert.match(seen[0], /\/v1\/threads\?archived=all&limit=20$/);
  assert.doesNotMatch(seen[1], /archived/);
  assert.match(seen[2], /\/v1\/threads\/groups\?archived=all$/);
  assert.match(seen[3], /\/v1\/threads\/count\?q=fox&archived=true&environment=default%2Cnone$/);

  const m = cmock.createMockClient({}, { speed: 1000 });
  const live1 = await m.threads(), arch = await m.threads({ archived: true }), both = await m.threads({ archived: 'all' });
  assert.ok(live1.length > 20, 'enough chats for the sidebar\'s 20, then Show all');
  assert.ok(arch.length >= 2 && arch.every(t => t.archived) && live1.every(t => !t.archived));
  assert.equal(both.length, live1.length + arch.length);
  assert.ok(both.every((t, i) => !i || both[i - 1].updated >= t.updated), 'newest first');
  for (const [o, n] of [[{}, live1.length], [{ archived: true }, arch.length], [{ archived: 'all' }, both.length]]) assert.equal((await m.threadCount(o)).count, n);
  const ariadne = await m.threads({ environment: 'ariadne', archived: 'all' });
  assert.ok(ariadne.length > 5, 'an environment with more than 5 chats, for Show more');
  assert.equal((await m.threadCount({ environment: 'ariadne', archived: 'all' })).count, ariadne.length);
  assert.equal((await m.threadCount({ q: 'lighthouse' })).count, 1);
  const days = new Set(both.map(t => Math.floor((Date.now() / 1000 - t.updated) / 86400)));
  for (const d of [0, 2, 3, 5]) assert.ok(days.has(d), `a chat ${d} days old`);
  assert.ok([...days].some(d => d >= 8) && [...days].some(d => d > 365), 'older ones, and one from another year');
  assert.equal((await cmock.createMockClient({}, { speed: 1000, history: false }).threads({ archived: 'all' })).filter(t => !t.settings?.project && !t.settings?.task && !t.children && !t.settings?.external).length, 2);   // and the projects' fixture chats (plan projects 1.3), the tasks' runs (scheduled-tasks 4.1), a workflow and a chat another agent started (agent-workflows 3.1, 4.3)
});
