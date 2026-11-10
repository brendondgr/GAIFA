// calendar 6.3: an event's prep task: the task the agent gets, and the item's mark once it's made.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const P = await load('cal-prep.js');

test('the task body', () => {
  const b = P.prepBody({ id: 'c_1', title: 'Design review', project_id: 'p_x' }, { title: 'Design review', prepText: ' Gather my notes on the review. ', prepBefore: 60 });
  assert.deepEqual(b, { name: 'Prep: Design review', instructions: 'Gather my notes on the review.', enabled: true, mode: 'auto',
    schedule: { kind: 'event', item: 'c_1', before_min: 60, title: 'Design review' }, project_id: 'p_x' });
});

test('saving makes the task and marks the item; nothing without words or for a to-do', async () => {
  const calls = [], patched = [];
  const agent = async (m, p, json) => { calls.push([m, p, json.schedule]); return { id: 'k_abc' }; };
  const client = { patch: async (id, body) => patched.push([id, body]) };
  const item = { id: 'c_1', kind: 'event', title: 'Review' };
  assert.equal(await P.savePrep(item, { prepOn: true, prepText: '' }, agent, client), null);
  assert.equal(await P.savePrep({ ...item, kind: 'todo' }, { prepOn: true, prepText: 'x' }, agent, client), null);
  assert.equal(await P.savePrep({ ...item, prep: { task_id: 'k_old' } }, { prepOn: true, prepText: 'x' }, agent, client), null);
  const t = await P.savePrep(item, { prepOn: true, prepText: 'Brief me', prepBefore: 30 }, agent, client);
  assert.equal(t.id, 'k_abc');
  assert.deepEqual(calls, [['POST', '/v1/tasks', { kind: 'event', item: 'c_1', before_min: 30, title: 'Review' }]]);
  assert.deepEqual(patched, [['c_1', { prep: { task_id: 'k_abc', before_min: 30 } }]]);
});
