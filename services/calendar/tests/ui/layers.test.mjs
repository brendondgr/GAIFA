// calendar 6.4: the scheduled tasks layer: marks for due times, runs coloured by state, where a click goes, and the
// link that schedules a task at a sheet's time.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
const L = await load('cal-layers.js');

test('marks and runs', () => {
  const went = [];
  const occ = L.taskOccs([{ id: 'k_1', name: 'Digest', when: 'Every day at 07:00', due: [1000],
    runs: [{ id: 'r_1', due: 500, state: 'done', seen: false, thread_id: 't_9', late: 1, refused: 2 }, { id: 'r_2', due: 600, state: 'failed', seen: true }] }], h => went.push(h));
  assert.deepEqual(occ.map(o => [o.title, o.ts, o.color]), [['◷ Digest', 1000, '#8A94A6'], ['● Digest · done · 2 refused (late)', 500, L.RUN_COLOR.done],
    ['Digest · failed', 600, L.RUN_COLOR.failed]]);
  assert.ok(occ.every(o => o.layer === 'tasks' && o.end_ts - o.ts === 900 && !o.all_day));
  occ[0].open(); occ[1].open(); occ[2].open();
  assert.deepEqual(went, ['#/chat/tasks/k_1', '#/chat/t_9', '#/chat/tasks/k_1']);
});

test('schedule a task here', () => {
  assert.equal(L.scheduleHere({ date: '2026-11-14', time: '15:00' }), '#/chat/tasks?new=once&at=2026-11-14T15%3A00');
  assert.equal(L.scheduleHere({ date: '2026-11-14', time: '15:00', project_id: 'p_1' }), '#/chat/tasks?new=once&at=2026-11-14T15%3A00&project=p_1');
});

test('history: chats as blocks of at least 15 minutes, outputs as marks', () => {
  const went = [];
  const occ = L.historyOccs([{ thread_id: 't_1', title: 'Plan the trip', day: '2026-11-10', first: 1000, last: 1100, turns: 3 },
    { thread_id: 't_2', title: 'Digest · Mon', day: '2026-11-10', first: 5000, last: 9000, turns: 1, task: 'k_1' }],
  [{ id: 'o_1', title: 'chart.png', created_ts: 2000, service: 'agent' }], h => went.push(h));
  assert.deepEqual(occ.map(o => [o.title, o.ts, o.end_ts, o.location]), [['Plan the trip', 1000, 1900, '3 messages'], ['◷ Digest · Mon', 5000, 9000, '1 message'],
    ['▣ chart.png', 2000, 2600, 'agent']]);
  assert.ok(occ.every(o => o.layer === 'history'));
  occ[0].open(); occ[2].open();
  assert.deepEqual(went, ['#/chat/t_1', '#/outputs/o_1']);
});
