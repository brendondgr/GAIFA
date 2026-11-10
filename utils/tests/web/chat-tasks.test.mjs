// web/chat/ (plan scheduled-tasks 4.1–4.5): schedules in the browser (words, next run, checks), the Scheduled row's
// and grid's helpers, the editor's fields and body, the routes, the task page's helpers, and the mock's task calls.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const when = await load('chat/chat-when.js');
const tk = await load('chat/chat-tasks.js');
const ed = await load('chat/chat-task-edit.js');
const page = await load('chat/chat-task.js');
const panels = await load('chat/chat-task-panels.js');
const cmock = await load('chat/chat-mock.js');
const chat = await load('chat/chat.js');

const at = (y, mo, d, h = 0, mi = 0) => new Date(y, mo - 1, d, h, mi).getTime() / 1000;
const local = t => { const d = new Date(t * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };

test('schedules: next run, the month’s last day, hourly windows, words, checks (as tasks/when.py)', () => {
  const mon = at(2026, 11, 9, 8);
  assert.equal(local(when.nextAfter({ kind: 'daily', time: '07:00' }, mon)), '2026-11-10 07:00');
  assert.equal(local(when.nextAfter({ kind: 'weekdays', time: '07:00' }, at(2026, 11, 13, 8))), '2026-11-16 07:00');
  assert.equal(local(when.nextAfter({ kind: 'weekly', day: 2, time: '21:30' }, mon)), '2026-11-11 21:30');
  assert.equal(local(when.nextAfter({ kind: 'monthly', day: 31, time: '09:00' }, at(2027, 1, 31, 10))), '2027-02-28 09:00');
  const w = { kind: 'hourly', every: 1, minute: 0, from: '08:00', to: '18:00', weekdays: true };
  assert.equal(local(when.nextAfter(w, at(2026, 11, 13, 18, 30))), '2026-11-16 08:00');
  assert.equal(local(when.nextAfter({ kind: 'hourly', every: 2, minute: 15 }, at(2026, 11, 9, 9))), '2026-11-09 10:15');
  assert.equal(when.describe({ kind: 'hourly', every: 2, minute: 15, from: '08:00', to: '18:00' }), 'Every 2 hours at :15, 08:00–18:00');
  assert.equal(when.describe({ kind: 'monthly', day: 31, time: '09:00' }), 'Monthly on the 31st at 09:00 (or the month’s last day)');
  assert.equal(when.describe({ kind: 'weekly', day: 0, time: '09:00' }), 'Mondays at 09:00');
  assert.deepEqual(when.check({ kind: 'daily', time: '07:00' }), []);
  assert.ok(when.check({ kind: 'daily', time: '7:00' }).length && when.check({ kind: 'hourly', from: '08:00' }).length);
  assert.ok(when.check({ kind: 'hourly', every: 5, minute: 30, from: '01:00', to: '04:00' })[0].includes('no hour'));
  assert.equal(when.nextAfter({ kind: 'nope' }), null);
  assert.equal(when.whenWords(at(2026, 11, 10, 7), at(2026, 11, 9, 8)), 'tomorrow 07:00');
  assert.equal(when.whenWords(at(2026, 11, 9, 9), at(2026, 11, 9, 8)), 'today 09:00');
  assert.equal(when.whenWords(at(2026, 11, 16, 7), at(2026, 11, 9, 8)), 'Mon 16 Nov 07:00');
});

test('the row and the grid: on first then next run, search, unread, a run in words', () => {
  const L = [{ id: 'k_a', name: 'b', enabled: true, next_due: 50, unread: 1, instructions: 'feed' }, { id: 'k_b', name: 'A', enabled: false, next_due: null, instructions: '' },
    { id: 'k_c', name: 'c', enabled: true, next_due: 10, unread: 2, instructions: 'Backup' }];
  assert.deepEqual(tk.sortTasks(L).map(t => t.id), ['k_c', 'k_a', 'k_b']);
  assert.deepEqual(tk.filterTasks(L, 'BACK').map(t => t.id), ['k_c']);
  assert.equal(tk.unreadOf(L), 3);
  assert.equal(tk.dropdownTasks(L, 1)[0].id, 'k_c');
  assert.equal(tk.runWords({ state: 'done', refused: 2 }), 'Done · 2 refused');
  assert.equal(tk.runWords({ state: 'skipped', why: 'still running' }), 'Skipped (still running)');
  assert.equal(tk.runWords({ state: 'running', test: true, late: 3 }), 'Running · test · late');
  assert.equal(tk.runWords(null), 'No runs yet');
  assert.equal(tk.runTone({ state: 'failed' }), 'red');
  assert.equal(tk.cardLine({ enabled: false, when: 'Weekdays at 07:00' }), 'Weekdays at 07:00 · off');
  assert.equal(tk.cardLine({ enabled: true, when: 'Every day at 07:00', next_due: at(2026, 11, 10, 7) }, at(2026, 11, 9, 8)), 'Every day at 07:00 · next tomorrow 07:00');
});

test('the editor: fields from a task, the schedule they make, the body and its checks', () => {
  const f = ed.formOf(null, { project_id: 'p_1' });
  assert.equal(f.kind, 'daily'); assert.equal(f.mode, 'auto'); assert.equal(f.project_id, 'p_1'); assert.ok(f.use_profile && f.use_project_memory);
  assert.deepEqual(ed.taskBody(f).error, 'A task needs a name.');
  assert.match(ed.taskBody({ ...f, name: 'x' }).error, /instructions/);
  const ok = ed.taskBody({ ...f, name: '  Morning   digest ', instructions: 'Read it.', tools: 'web_*, workspace_write web_*', sites: 'https://News.ycombinator.com/front, weather.gov', anySite: true, mcp: ['blender'] });
  assert.deepEqual(ok.body.allow, { tools: ['web_*', 'workspace_write'], sites: ['news.ycombinator.com', 'weather.gov', '*'], mcp: ['blender'] });
  assert.equal(ok.body.name, 'Morning digest'); assert.equal(ok.body.project_id, 'p_1'); assert.equal(ok.body.only_own, false);
  assert.deepEqual(ed.scheduleOf({ ...f, kind: 'hourly', every: '2', minute: '15', windowOn: true, from: '08:00', to: '18:00', weekdays: true }),
    { kind: 'hourly', every: 2, minute: 15, from: '08:00', to: '18:00', weekdays: true });
  assert.deepEqual(ed.scheduleOf({ ...f, kind: 'monthly', day: '40', time: '09:00' }), { kind: 'monthly', day: 31, time: '09:00' });
  assert.deepEqual(ed.scheduleOf({ ...f, kind: 'weekly', day: '4', time: '06:30' }), { kind: 'weekly', day: 4, time: '06:30' });
  assert.match(ed.taskBody({ ...f, name: 'x', instructions: 'y', kind: 'hourly', windowOn: true, from: '18:00', to: '08:00' }).error, /^The schedule: /);
  const back = ed.formOf({ name: 'T', instructions: 'i', schedule: { kind: 'hourly', every: 3, minute: 5, from: '09:00', to: '17:00' }, mode: 'bypass',
    allow: { tools: ['a'], sites: ['x.org', '*'], mcp: [] }, skills: ['s'], use_profile: false, use_project_memory: true, keep_days: 7, only_own: true, project_id: 'p_2' });
  assert.equal(back.windowOn, true); assert.equal(back.anySite, true); assert.equal(back.sites, 'x.org'); assert.equal(back.use_profile, false);
  assert.deepEqual(ed.taskBody(back).body.schedule, { kind: 'hourly', every: 3, minute: 5, from: '09:00', to: '17:00' });
  assert.equal(ed.taskBody(back).body.only_own, true);
  assert.equal(ed.preview({ ...f, kind: 'weekdays', time: '07:00' }, at(2026, 11, 13, 8)).next, 'Mon 16 Nov 07:00');
  assert.ok(ed.BYPASS_WARNING.includes('only the folders’ levels'));
});

test('the routes: #/chat/tasks and #/chat/tasks/<id> are pages', () => {
  assert.deepEqual(chat.subPage({ parts: ['chat', 'tasks'] }), { page: 'tasks' });
  assert.deepEqual(chat.subPage({ parts: ['chat', 'tasks', 'k_0a1b'] }), { page: 'task', kid: 'k_0a1b' });
  assert.deepEqual(chat.subPage({ parts: ['chat', 'projects'] }), { page: 'projects' });
  assert.equal(chat.subPage({ parts: ['chat', 't_abc'] }), null);
});

test('the task page: the run its log shows; suggestions in words and as a body', () => {
  const runs = [{ id: 'r_q', thread_id: null }, { id: 'r_b', thread_id: 't_b' }, { id: 'r_a', thread_id: 't_a' }];
  assert.equal(page.pickRun(runs, null).id, 'r_b');
  assert.equal(page.pickRun(runs, 'r_a').id, 'r_a');
  assert.equal(page.pickRun([], null), null);
  assert.equal(panels.allowWords({ kind: 'site', value: 'example.com' }), 'the site example.com');
  assert.deepEqual(panels.allowBody({ kind: 'mcp', value: 'blender' }), { mcp: ['blender'] });
  assert.deepEqual(panels.allowBody({ kind: 'tool', value: 'web_fetch' }), { tools: ['web_fetch'] });
});

test('tasks on the mock: list, create with a check, 409 on problems, runs, unread, notes, folders, allows, log, delete (4.1)', async () => {
  const c = cmock.createMockClient({}, { speed: 400 });
  await c.threads();                                           // seeds the chats, the projects and the tasks
  const list = await c.tasks();
  assert.deepEqual(list.map(t => t.name).sort(), ['Morning digest', 'Thesis backup']);
  const digest = list.find(t => t.name === 'Morning digest'), backup = list.find(t => t.name === 'Thesis backup');
  assert.equal(digest.when, 'Weekdays at 07:00'); assert.equal(digest.unread, 1); assert.ok(backup.project_id);
  assert.deepEqual((await c.tasks({ project: backup.project_id })).map(t => t.id), [backup.id]);
  assert.deepEqual((await c.tasksUnread()).tasks, { [digest.id]: 1 });
  const runs = await c.taskRuns(digest.id);
  assert.equal(runs.length, 3); assert.ok(runs.some(r => r.refused === 1)); assert.ok(runs.some(r => r.state === 'skipped'));
  const unseen = runs.find(r => !r.seen);
  assert.equal((await c.threads({ task: digest.id })).length, 2);
  await c.seeRun(digest.id, unseen.id);
  assert.equal((await c.tasksUnread()).count, 0);
  const log = await c.runLog(digest.id, runs.find(r => r.refused).id);
  assert.deepEqual(log.map(r => [r.outcome, r.by]), [['allowed', 'pre-allow'], ['refused', 'judge']]);
  // a new task with a problem is saved off, with its check
  const bad = await c.createTask({ name: 'Odd', schedule: { kind: 'daily', time: '06:00' }, instructions: 'x', allow: { tools: ['nothing_*'] } });
  assert.equal(bad.enabled, false); assert.equal(bad.check.problems[0].field, 'allow');
  await assert.rejects(c.patchTask(bad.id, { enabled: true }), e => e.code === 'task_problems' && e.data.task.enabled === false);
  await assert.rejects(c.createTask({ name: 'x', schedule: { kind: 'daily', time: '25:00' } }), e => e.code === 'invalid_schedule');
  const good = await c.createTask({ name: 'Weather', schedule: { kind: 'hourly', every: 1, minute: 0 }, instructions: 'Log the forecast.' });
  assert.ok(good.enabled && good.next_due && good.check.problems.length === 0);
  // run now, a test run, its suggestion, adding it
  const r = await c.runTask(good.id);
  assert.equal(r.state, 'done'); assert.ok(r.thread_id);
  const tr = await c.testTask(good.id);
  assert.equal(tr.test, true);
  assert.deepEqual((await c.runAllows(good.id, tr.id)).map(s => s.value), ['workspace_write']);
  assert.deepEqual((await c.addAllows(good.id, { tools: ['workspace_write'] })).allow.tools, ['workspace_write']);
  assert.deepEqual(await c.runAllows(good.id, tr.id), []);
  // notes and folders
  const n = await c.addTaskNote(good.id, ' The feed   is at /srv. ');
  assert.equal(n.text, 'The feed is at /srv.');
  assert.equal((await c.patchTaskNote(good.id, n.id, 'moved')).text, 'moved');
  await c.removeTaskNote(good.id, n.id);
  assert.deepEqual(await c.taskNotes(good.id), []);
  await c.addTaskFolder(good.id, { path: '/home/u/logs', level: 'edit' });
  assert.equal((await c.taskFolders(good.id))[0].level, 'edit');
  await assert.rejects(c.addTaskFolder(good.id, { path: '/home/u/Agents/GAIFA', level: 'edit' }), e => e.code === 'capped');
  // events, and delete leaving the runs as chats
  const seen = [];
  const w = c.watchTasks(ev => seen.push(ev.type));
  const done = await c.deleteTask(good.id);
  assert.equal(done.chats, 2);
  assert.ok(seen.includes('task')); w.close();
  await assert.rejects(c.task(good.id), e => e.status === 404);
});

test('calendar 6.1: once in the rules, the picker and its preview; an event schedule as it is', async () => {
  const W = await import(pathToFileURL(path.join(root, 'web/chat/chat-when.js')).href);
  const E = await import(pathToFileURL(path.join(root, 'web/chat/chat-task-edit.js')).href);
  const T = await import(pathToFileURL(path.join(root, 'web/chat/chat-tasks.js')).href);
  const s = { kind: 'once', at: '2026-11-14T07:00' }, t = new Date(2026, 10, 14, 7).getTime() / 1000;
  assert.deepEqual(W.check(s), []);
  assert.ok(W.check({ kind: 'once', at: '2026-02-30T07:00' }).length);
  assert.equal(W.nextAfter(s, t - 60), t);
  assert.equal(W.nextAfter(s, t), null);
  assert.equal(W.describe(s), 'Once, Sat 14 Nov 07:00');
  assert.equal(W.describe({ kind: 'event', item: 'c_1', before_min: 30, title: 'Review' }), '30 min before “Review”, each time');
  const f = E.formOf(null, { kind: 'once', at: '2026-11-14T07:00' });
  assert.deepEqual(E.scheduleOf(f), s);
  assert.equal(E.preview(f, t - 3600).words, 'Once, Sat 14 Nov 07:00');
  assert.ok(E.preview(f, t + 60).error);
  const ev = { kind: 'event', item: 'c_1', before_min: 15, title: 'Review' };
  assert.deepEqual(E.scheduleOf(E.formOf({ schedule: ev, name: 'Prep', instructions: 'x' })), ev);
  assert.deepEqual(T.presetOf('#/chat/tasks?new=once&at=2026-11-14T15:00'), { kind: 'once', at: '2026-11-14T15:00' });
  assert.equal(T.presetOf('#/chat/tasks'), null);
  assert.match(E.defaultAt(new Date(2026, 10, 9, 18, 31)), /^2026-11-09T19:00$/);
});
