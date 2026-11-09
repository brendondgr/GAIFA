// web/chat/ (plan agent-workflows 3.1–3.5): the sub-agent calls on the live client and on the mock (the tree, the
// requests, deciding one from the parent, the workflow watch), the sidebar tree's rows, the fold's words and the
// request cards' helpers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const capi = await load('chat/chat-api.js');
const cmock = await load('chat/chat-mock.js');
const tree = await load('chat/chat-tree.js');
const agents = await load('chat/chat-agents.js');
const steps = await load('chat/chat-steps.js');
const cards = await load('chat/chat-cards.js');

test('the live client: tree, requests, deciding one, the workflow watch (3.1)', async () => {
  const seen = [];
  const c = capi.createLiveClient({ base: 'http://h', fetch: async (url, o = {}) => { seen.push([o.method || 'GET', url, o.body || null]);
    return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }); }, EventSource: null });
  await c.tree('t_a');
  await c.requests('t_a', { waiting: true });
  await c.requests('t_a');
  await c.decideRequest('t_a', 'rq_1', { approve: true, remember: 'thread' });
  assert.deepEqual(seen.map(([m, u]) => [m, u.replace('http://h/api/s/agent', '')]), [
    ['GET', '/v1/threads/t_a/tree'], ['GET', '/v1/threads/t_a/requests?waiting=true'], ['GET', '/v1/threads/t_a/requests'],
    ['POST', '/v1/threads/t_a/requests/rq_1']]);
  assert.deepEqual(JSON.parse(seen[3][2]), { approve: true, remember: 'thread' });
  const opened = [];
  class ES { constructor(u) { opened.push(u); this.close = () => {}; } }
  const w = capi.createLiveClient({ base: '', fetch: async () => new Response('{}'), EventSource: ES }).watchWorkflows(() => {});
  assert.match(opened[0], /\/v1\/streams\?threads=&watch=workflows$/);
  w.close();
});

test('the mock: a workflow, its tree and requests, deciding from the parent (3.1)', async () => {
  const c = cmock.createMockClient({}, { speed: 400 });
  const list = await c.threads();
  const parent = list.find(t => t.title === 'Compare the folders');
  assert.ok(parent && parent.children === 3);
  assert.ok(!list.some(t => t.spawn), 'sub-agents stay out of the list');
  assert.ok((await c.threads({ q: 'Read src' })).some(t => t.spawn?.parent === parent.id), 'a search finds them');
  const tree = await c.tree(parent.id);
  assert.equal(tree.root.id, parent.id);
  assert.deepEqual(tree.children.map(n => [n.label, n.state, n.seen, n.write]),
    [['Read tests', 'idle', false, false], ['Read src', 'running', true, false], ['Add a header', 'waiting', true, true]]);
  assert.equal((await c.tree(tree.children[0].id)).root.id, parent.id, 'asked from a sub-agent: its workflow');
  const [rq] = await c.requests(parent.id, { waiting: true });
  assert.equal(rq.tool, 'workspace_edit'); assert.equal(rq.review.action, 'forward'); assert.equal(rq.open, false);
  const evs = [];
  const w = c.watchWorkflows(ev => evs.push(ev));
  const out = await c.decideRequest(parent.id, rq.id, { approve: true });
  assert.equal(out.action, 'approve');
  assert.equal(evs[0].type, 'agent_child'); assert.equal(evs[0].child.state, 'idle'); assert.equal(evs[0].root, parent.id);
  assert.deepEqual(await c.requests(parent.id, { waiting: true }), []);
  await assert.rejects(c.decideRequest(parent.id, rq.id, { approve: true }), e => e.code === 'already_decided');
  await assert.rejects(c.decideRequest(parent.id, 'rq_nope', {}), e => e.status === 404);
  const done = (await c.events(parent.id)).filter(e => e.type === 'agent_done');
  assert.equal(done.at(-1).payload.answer, 'Added the header to src/store.py.');
  w.close();
});

test('the fold: step words, the sub-agent of a row, answers, the strip, the cards registered (3.3)', () => {
  const w = steps.stepFor('agent');
  assert.equal(w.done({ background: true }), 'Started a sub-agent'); assert.equal(w.done({}), 'Ran a sub-agent');
  assert.equal(w.detail({ label: 'Read src' }), 'Read src');
  assert.equal(steps.stepFor('agent_review').done({ action: 'deny' }), 'Said no to a sub-agent');
  assert.ok(steps.stepFor('agent_list').lookup);
  assert.deepEqual(agents.childOfRow({ item: { result: { data: { agent: { child: 't_a', label: 'A', background: true } } } } }),
    { id: 't_a', label: 'A', background: true, answer: undefined, state: undefined });
  assert.equal(agents.childOfRow({ item: { result: { data: { agent: { child: 't_a' } }, content: JSON.stringify({ answer: 'done' }) } } }).answer, 'done');
  assert.equal(agents.childOfRow({ progress: { live: { agent: { child: 't_b', label: 'B' } } }, item: {} }).id, 't_b');
  assert.equal(agents.childOfRow({ item: { result: { content: JSON.stringify({ child: 't_c', label: 'C', answer: 'x', state: 'idle' }) } } }).answer, 'x');
  assert.equal(agents.childOfRow({ item: { result: { content: 'nope' } } }), null);
  assert.equal(agents.answerText('<untrusted source="sub-agent A">\nThe answer.\n</untrusted>'), 'The answer.');
  assert.equal(agents.answerText('x'.repeat(400), 10).length, 10);
  const t = { children: [{ id: 'a', parent: 'p', state: 'running' }, { id: 'b', parent: 'p', state: 'idle' }, { id: 'c', parent: 'p', state: 'waiting' }, { id: 'd', parent: 'q', state: 'running' }] };
  assert.deepEqual(agents.atWork(t, 'p').map(n => n.id), ['a', 'c']);
  for (const k of ['live:agent', 'agent_done', 'agent_request', 'agent_review']) assert.ok(cards.hasCard(k), k);
});

test('request cards: buttons for the workflow, the review in words, when to read them again (3.4)', async () => {
  const rq = await load('chat/chat-agent-requests.js'), appr = await load('chat/chat-approvals.js');
  const labels = rq.requestButtons({ risk: 'write' }).map(b => b.label);
  assert.ok(labels.includes('Allow in this workflow') && labels.includes('Allow once') && !labels.some(l => l.includes('this chat')));
  assert.ok(rq.requestButtons({ risk: 'network', grant_key: 'url:host' }).some(b => b.remember === 'sites'));
  assert.equal(rq.reviewWords({}), 'The chat’s agent is reviewing it…');
  assert.equal(rq.reviewWords({ review: { action: 'forward', reason: 'your call' } }), 'The chat’s agent passed it to you: “your call”');
  assert.equal(rq.reviewWords({ review: { action: 'forward', auto: true } }), 'The chat’s agent passed it to you.');
  assert.equal(rq.requestStamp([{ type: 'user' }, { type: 'agent_request' }, { type: 'agent_review' }]), 2);
  assert.ok(cards.hasCard('agent_request_card'));
  assert.equal(appr.originText({ service: 'agent', thread: 't_c', parent: 't_p' }), 'from a sub-agent');
  assert.equal(appr.originText({ service: 'agent', thread: 't_c' }), 'from a chat');
});

test('a sub-agent\'s header: the way back and what it may do (3.5)', async () => {
  const hd = await load('chat/chat-header.js');
  assert.deepEqual(hd.spawnBits({ settings: { spawn: { parent: 't_p', write: false } } }), { parent: 't_p', rights: 'reads only', by: null });
  assert.deepEqual(hd.spawnBits({ spawn: { parent: 't_p', write: true, by: 'mcp' } }), { parent: 't_p', rights: 'writer', by: 'from another agent' });
  assert.equal(hd.spawnBits({ settings: {} }), null);
});

test('a background sub-agent\'s end or request heads the turn it starts (3.3)', async () => {
  const turn = await load('chat/chat-turn.js'), thread = await load('chat/chat-thread.js');
  const ev = (seq, type, payload) => ({ seq, ts: seq, type, payload });
  const view = thread.buildView([ev(1, 'user', { text: 'go' }), ev(2, 'assistant', { text: 'started', step: 's1' }),
    ev(3, 'agent_done', { child: 't_a', label: 'A', state: 'idle', answer: 'x' }), ev(4, 'assistant', { text: 'A found x', step: 's2' }),
    ev(5, 'agent_request', { id: 'rq_1', child: 't_b', kind: 'approval', tool: 'fake_wipe', in_result: false }), ev(6, 'assistant', { text: 'over to you', step: 's3' })]);
  const turns = turn.groupTurns(view).filter(b => b.kind === 'turn');
  assert.deepEqual(turns.map(t => t.user.kind), ['user', 'agent_done', 'agent_request']);
});

test('the sidebar tree: rows in order with their connectors, looks, following events, open rows (3.2)', async () => {
  const t = { root: { id: 'r', children: 2 }, children: [
    { id: 'a', parent: 'r', label: 'Read src', state: 'running', seen: true },
    { id: 'b', parent: 'r', label: 'Read tests', state: 'idle', seen: false },
    { id: 'a1', parent: 'a', label: 'Deeper', state: 'queued', seen: true }] };
  assert.deepEqual(tree.treeRows(t).map(r => [r.node.id, r.depth, r.last]), [['a', 0, false], ['a1', 1, true], ['b', 0, true]]);
  assert.deepEqual([tree.childLook(t.children[0]).state, tree.childLook(t.children[0]).unread], ['running', false]);
  assert.deepEqual([tree.childLook(t.children[1]).word, tree.childLook(t.children[1]).unread], ['finished, new', true]);
  assert.equal(tree.childLook({ state: 'waiting', seen: true }).word, 'waiting for you');
  assert.equal(tree.childLook({ state: 'queued' }).word, 'waiting for a free slot');
  const moved = tree.applyChild(t, { root: 'r', child: { id: 'b', parent: 'r', label: 'Read tests', state: 'idle', seen: true } });
  assert.equal(moved.children.find(n => n.id === 'b').seen, true);
  const added = tree.applyChild(t, { root: 'r', child: { id: 'c', parent: 'r', label: 'New', state: 'queued', seen: true } });
  assert.equal(added.children.length, 4); assert.equal(added.root.children, 3);
  assert.equal(tree.applyChild(t, { root: 'other', child: { id: 'x' } }), null);
  const c = cmock.createMockClient({}, { speed: 400 });
  const parent = (await c.threads()).find(x => x.title === 'Compare the folders');
  const first = (await c.tree(parent.id)).children[0];
  assert.equal(first.seen, false);
  await c.seenChild(first.id);
  assert.equal((await c.tree(parent.id)).children[0].seen, true);
});
