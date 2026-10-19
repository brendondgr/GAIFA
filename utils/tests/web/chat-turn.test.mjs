// web/chat/chat-turn.js (plan 19.2): the design study's sample turn at each of its seven stages
// (the live status, the summary, answer vs update), a button-started turn, a queued message, the
// failed-call-and-retry turn, and a replay giving the same turns.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { EVENTS, STAGES, stageData, ERROR_EVENTS } from './chat-sample.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const th = await load('chat/chat-thread.js');
const ct = await load('chat/chat-turn.js');

const turnsAt = i => { const d = stageData(i); return ct.groupTurns(th.buildView(d.events, d.live), { running: d.running, now: d.now }).filter(b => b.kind === 'turn'); };
const rowTypes = t => t.steps.map(s => s.rows.map(r => r.type === 'tool' ? `tool:${r.name}:${r.status}` : r.type));

test('the sample turn: the live status at every stage', () => {
  const st = STAGES.map((_, i) => turnsAt(i)[0].status);
  assert.equal(st[0].kind, 'thinking');
  assert.ok(st[0].row.seconds >= 1.9 && st[0].row.seconds <= 2.1, 'thinking seconds count from the delta\'s start');
  assert.equal(st[1].kind, 'lookup');
  assert.equal(st[2].kind, 'tool'); assert.equal(st[2].row.name, 'comfy_generate_image'); assert.equal(st[2].pct, 0.42); assert.equal(st[2].note, 'sampling 4/8');
  assert.equal(st[3].kind, 'waiting'); assert.equal(st[3].item.call.name, 'gen3d_make_3d');
  assert.equal(st[4].kind, 'tool'); assert.equal(st[4].row.name, 'gen3d_make_3d'); assert.equal(st[4].pct, 0.63);
  assert.equal(st[5].kind, 'writing');
  assert.equal(st[6], null, 'no status once done');
});

test('the sample turn when done: steps, rows, outputs, the answer and the summary', () => {
  const [t] = turnsAt(6);
  assert.equal(t.user.ev.payload.text, EVENTS[0].payload.text);
  assert.deepEqual(rowTypes(t), [
    ['thinking', 'tool:find_tools:done', 'tool:load_tools:done'],
    ['thinking', 'update', 'tool:comfy_generate_image:done'],
    ['thinking', 'update', 'tool:gen3d_make_3d:done'],
    ['thinking']]);
  assert.match(t.answer.text, /^Here's your samurai/);
  assert.deepEqual(t.outputs.map(o => [o.n, o.kind, o.tool]), [[1, 'image', 'comfy_generate_image'], [2, 'model3d', 'gen3d_make_3d']]);
  assert.deepEqual([t.summary.text, t.summary.work, t.summary.lookups], ['Ran 2 tools', 2, 2]);
  assert.equal(t.elapsed, 178);
  const tools = t.steps.flatMap(s => s.rows).filter(r => r.type === 'tool');
  assert.deepEqual(tools.map(r => r.seconds), [1, 1, 18, 130], 'the 3D call counts from its approval');
  assert.deepEqual(tools.map(r => r.lookup), [true, true, false, false]);
  assert.deepEqual(t.pending, []);
});

test('the sample turn while running: answers stream as the answer, waiting rows, queued vs running', () => {
  const ans = turnsAt(5)[0];
  assert.ok(ans.answer.streaming); assert.match(ans.answer.text, /^Here's your samurai/);
  const ap = turnsAt(3)[0];
  assert.equal(ap.pending.length, 1);
  assert.equal(ap.steps.at(-1).rows.at(-1).status, 'waiting');
  assert.equal(ap.answer, null, 'text in a step with tools is an update, not the answer');
  // a call without its `call` event yet, after a running one in the same step: queued
  const d = stageData(2), evs = [...d.events, { seq: 11, ts: d.now, type: 'tool_call', payload: { id: 'cx', name: 'comfy_edit_image', arguments: {}, step: 's2', by: 'model' } }];
  const t = ct.groupTurns(th.buildView(evs, d.live), { running: true, now: d.now })[0];
  assert.deepEqual(t.steps[1].rows.filter(r => r.type === 'tool').map(r => r.status), ['running', 'queued']);
  const stopped = ct.groupTurns(th.buildView(evs, {}), { running: false, now: d.now })[0];
  assert.deepEqual(stopped.steps[1].rows.filter(r => r.type === 'tool').map(r => r.status), ['stopped', 'stopped']);
});

test('a turn a button started, a queued message, and standalone items', () => {
  const evs = [
    { seq: 1, ts: 10, type: 'user', payload: { text: 'hi' } },
    { seq: 2, ts: 11, type: 'assistant', payload: { text: 'Hello!', step: 'a' } },
    { seq: 3, ts: 20, type: 'compact', payload: { stage: 'summary', summary: 'x' } },
    { seq: 4, ts: 30, type: 'tool_call', payload: { id: 'b1', name: 'comfy_upscale_image', arguments: { scale: 2 }, step: 'b', by: 'user' } },
    { seq: 5, ts: 40, type: 'tool_result', payload: { id: 'b1', name: 'comfy_upscale_image', status: 'done', outputs: [{ n: 3, output_id: 'o3', kind: 'image' }] } },
    { seq: 6, ts: 50, type: 'user', payload: { text: 'and another', queued: true } },
    { seq: 7, ts: 51, type: 'note', payload: { text: 'the model\'s reply was empty; asked again', level: 'info' } },
    { seq: 8, ts: 52, type: 'assistant', payload: { text: 'Sure.', step: 'c' } },
  ];
  const blocks = ct.groupTurns(th.buildView(evs), { running: false, now: 60 });
  assert.deepEqual(blocks.map(b => b.kind === 'turn' ? (b.action ? 'action' : 'turn') : b.item.kind), ['turn', 'compact', 'action', 'turn']);
  const [hi, , act, q] = blocks;
  assert.equal(hi.answer.text, 'Hello!'); assert.deepEqual(hi.steps, []); assert.equal(hi.summary.text, 'Done');
  assert.equal(act.user, null); assert.equal(act.action.call.name, 'comfy_upscale_image');
  assert.deepEqual(act.outputs.map(o => o.n), [3]); assert.equal(act.summary.text, 'Ran 1 tool');
  assert.equal(q.answer.text, 'Sure.'); assert.deepEqual(rowTypes(q), [['note']]);
});

test('the retry turn: the error, the note and the retry are rows; lookups are grey', () => {
  const [t] = ct.groupTurns(th.buildView(ERROR_EVENTS), { running: false, now: 200 });
  assert.deepEqual(rowTypes(t), [['tool:read_skill:done'], ['tool:gen3d_make_3d:error', 'note'], ['tool:gen3d_make_3d:done']]);
  assert.equal(t.answer.text, 'Done: **#2** is the 3D model of the samurai.');
  assert.equal(t.summary.text, 'Ran 2 tools');
  const bad = t.steps[1].rows[0];
  assert.equal(bad.item.result.error.code, 'invalid_arguments');
  assert.ok(ct.isLookup('read_skill'));
  assert.ok(ct.isLookup('hub_list_services', [{ name: 'hub_list_services', risk: 'read' }]));
  assert.ok(!ct.isLookup('hub_stop_service', [{ name: 'hub_stop_service', risk: 'write' }]));
  ct.addLookup('my_lookup'); assert.ok(ct.isLookup('my_lookup'));
});

test('a replay (the same events again, and in two halves) gives the same turns', () => {
  const evs = stageData(6).events;
  const once = ct.groupTurns(th.buildView(evs), { running: false, now: 0 });
  const twice = ct.groupTurns(th.buildView(th.mergeEvents(th.mergeEvents([], evs.slice(0, 9)), evs)), { running: false, now: 0 });
  const shape = bs => JSON.stringify(bs.map(b => b.kind === 'turn' ? [b.key, rowTypes(b), b.answer?.text, b.outputs.map(o => o.n), b.summary] : b.item.key));
  assert.equal(shape(twice), shape(once));
});
