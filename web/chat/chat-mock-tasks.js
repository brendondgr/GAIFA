// The chat mock's scheduled tasks (plan scheduled-tasks 4.1, `?mock`): the agent's /v1/tasks routes on in-memory tasks,
// with the same shapes as services/agent/agent/api_tasks.py. Two fixture tasks: Morning digest (weekdays at 07:00, a
// pre-allowed site, notes, two runs: one with a refused call, unread) and Thesis backup (in the Thesis project, Sundays,
// folders of its own). Run now and Test run make a run chat with scripted events at once. Every change is a
// `{type: 'task'}` or `{type: 'task_run'}` event to the `watchTasks` listeners. `k` is chat-mock.js's helpers plus
// `projects()`, the projects mock's list.

import { check as checkSchedule, describe, nextAfter } from './chat-when.js';

const DAY = 86400;

export function createTaskMocks({ threads, newThread, emit, net, err, now, rid, projects }) {
  const tasks = new Map(), runs = new Map(), notes = new Map(), folders = new Map(), watchers = new Set();
  let seeded = false;

  const K = kid => { const t = tasks.get(kid); if (!t) throw err(404, `no task '${kid}'`, 'unknown_task'); return t; };
  const runsOf = kid => [...runs.values()].filter(r => r.task_id === kid).sort((a, b) => b.due - a.due);
  const row = t => {
    const last = runsOf(t.id).find(r => r.state !== 'queued') || null;
    return { ...structuredClone(t), when: describe(t.schedule), last_run: last && structuredClone(last), unread: runsOf(t.id).filter(r => !r.seen).length };
  };
  const tell = ev => watchers.forEach(f => { try { f(ev); } catch { /* a listener's own error */ } });
  const changed = kid => { const t = tasks.get(kid); tell({ type: 'task', thread_id: null, seq: null, id: kid, task: t ? row(t) : null }); };
  const runEvent = r => tell({ type: 'task_run', thread_id: null, seq: null, id: r.id, task_id: r.task_id, run: structuredClone(r) });

  function clean(body, old = {}) {
    const out = { ...old };
    for (const k of ['name', 'instructions', 'project_id', 'model', 'mode', 'skills', 'enabled', 'only_own', 'use_profile', 'use_project_memory', 'keep_days', 'schedule']) {
      if (body[k] !== undefined) out[k] = structuredClone(body[k]);
    }
    if (body.allow) out.allow = { tools: [...(body.allow.tools || [])], sites: [...(body.allow.sites || [])], mcp: [...(body.allow.mcp || [])] };
    if (body.settings) out.settings = structuredClone(body.settings);
    out.name = String(out.name || '').trim().replace(/\s+/g, ' ');
    if (!out.name) throw err(422, 'a task needs a name', 'bad_name');
    const bad = checkSchedule(out.schedule);
    if (bad.length) throw err(422, bad.join('; '), 'invalid_schedule');
    if (!['plan', 'accept_edits', 'auto', 'bypass'].includes(out.mode)) throw err(422, 'a task’s mode is one of plan, accept_edits, auto, bypass', 'bad_mode');
    return out;
  }
  function make(body, ts = now()) {
    const t = clean({ mode: 'auto', enabled: true, skills: [], use_profile: true, use_project_memory: true, only_own: false, keep_days: 30,
      instructions: '', project_id: null, model: null, ...body, allow: body.allow || {}, settings: body.settings || {} });
    Object.assign(t, { id: rid('k_').slice(0, 12), own_env: null, created: ts, updated: ts });
    t.next_due = t.enabled ? nextAfter(t.schedule, now()) : null;
    tasks.set(t.id, t); notes.set(t.id, []); folders.set(t.id, []);
    return t;
  }
  function runChat(t, run, script) {
    const th = newThread({ title: `${t.name} · ${new Date(run.due * 1000).toDateString().slice(0, 10)} ${new Date(run.due * 1000).toTimeString().slice(0, 5)}`,
      mode: t.mode, settings: { task: t.id, task_run: run.id, no_learn: true, ...(run.test ? {} : { unattended: true }), ...(t.project_id ? { project: t.project_id } : {}) } });
    emit(th, 'note', { text: `A scheduled run of “${t.name}” (${describe(t.schedule)}): ${run.test ? 'a test run, with cards as usual.' : 'no one is watching, so what would ask is refused.'}`, level: 'info' });
    emit(th, 'user', { text: t.instructions || t.name, by: 'schedule' });
    for (const [type, payload] of script) emit(th, type, payload);
    run.thread_id = th.thread.id;
    return th;
  }
  const SCRIPT = (refused = false) => [
    ['tool_call', { id: 'c1', name: 'web_fetch', arguments: { url: 'https://news.ycombinator.com/' }, by: 'model' }],
    ['tool_result', { id: 'c1', name: 'web_fetch', status: 'done', content: '…', grant_id: 'gr_mock' }],
    ...(refused ? [['tool_call', { id: 'c2', name: 'workspace_run', arguments: { folder: 'notes', command: 'git push' }, by: 'model' }],
      ['tool_result', { id: 'c2', name: 'workspace_run', status: 'denied', content: '', error: { code: 'unattended', detail: 'workspace_run: Auto: the judge asked; no one is here to approve it' },
        judge: { verdict: 'ask', source: 'model', reason: 'the instructions don’t ask to push', refused: true } }]] : []),
    ['assistant', { text: `Wrote today’s five stories to digest.md.${refused ? ' I didn’t push the notes: that was refused (no one to approve it).' : ''}`, step: rid('s_'), model: 'skynet' }],
  ];
  function addRun(t, o) {
    const r = { id: rid('r_').slice(0, 12), task_id: t.id, thread_id: null, due: o.due, started: o.due + 2, ended: o.due + 40, state: o.state || 'done',
      why: o.why || 'schedule', late: o.late || 0, test: !!o.test, refused: o.refused || 0, judge: t.mode === 'auto' ? (o.judge || 'ok') : null, seen: o.seen ?? true };
    runs.set(r.id, r);
    if (r.state !== 'skipped') runChat(t, r, SCRIPT(r.refused > 0));
    return r;
  }
  function seed() {
    if (seeded) return;
    seeded = true;
    const t0 = now();
    const a = make({ name: 'Morning digest', schedule: { kind: 'weekdays', time: '07:00' },
      instructions: 'Read https://news.ycombinator.com and write the five most-discussed stories to digest.md in my notes folder.',
      allow: { sites: ['news.ycombinator.com'], tools: [], mcp: [] }, skills: [] }, t0 - 12 * DAY);
    notes.get(a.id).push({ id: 'n_mock1', task_id: a.id, text: 'The front page’s comment counts are in the subtext rows; skip “Ask HN”.', thread_id: null, added: t0 - 5 * DAY, updated: t0 - 5 * DAY });
    addRun(a, { due: t0 - 2 * DAY, refused: 1 });
    addRun(a, { due: t0 - DAY, seen: false });
    addRun(a, { due: t0 - 3 * DAY, state: 'skipped', why: 'still running' });
    const pid = (projects() || [])[0]?.id || null;
    const b = make({ name: 'Thesis backup', schedule: { kind: 'weekly', day: 6, time: '21:00' }, project_id: pid, only_own: true, mode: 'accept_edits',
      instructions: 'Copy this week’s chapter drafts into the backup folder and list what changed.' }, t0 - 20 * DAY);
    b.own_env = 'task-' + b.id.slice(2);
    folders.set(b.id, [{ id: 'backups', path: '/home/user/Backups/thesis', level: 'edit', name: '', exists: true }]);
    addRun(b, { due: t0 - 4 * DAY });
  }
  function check(t) {
    const problems = [], warnings = [];
    if (!String(t.instructions || '').trim()) problems.push({ field: 'instructions', detail: 'the instructions are empty', fix: 'say what each run should do' });
    for (const g of t.allow?.tools || []) if (!/^(web|workspace|hub|comfy|tts|gen3d|agent|mcp)_/.test(g)) problems.push({ field: 'allow', detail: `no tool matches ${g}`, fix: 'name a tool from the catalog, or a glob such as web_*' });
    if (t.mode === 'bypass') warnings.push({ field: 'mode', detail: 'Bypass: the judge isn’t asked; only the folders’ levels limit what a run does' });
    return { problems, warnings };
  }
  const problems409 = (found, t) => err(409, `${found.problems[0].field}: ${found.problems[0].detail}`, 'task_problems', { ...found, task: row(t) });
  function start(t, why, test = false) {
    const r = { id: rid('r_').slice(0, 12), task_id: t.id, thread_id: null, due: now(), started: now(), ended: test ? null : now() + 1, state: test ? 'running' : 'done',
      why, late: 0, test, refused: 0, judge: t.mode === 'auto' ? 'ok' : null, seen: test };
    runs.set(r.id, r);
    const th = runChat(t, r, test ? [['tool_call', { id: 'c1', name: 'workspace_write', arguments: { folder: 'notes', path: 'digest.md' }, by: 'model' }],
      ['approval', { id: 'c1', approval_id: rid('ap_'), tool: 'workspace_write', arguments: { folder: 'notes', path: 'digest.md' }, ask_fields: [], risk: 'write', description: 'Write a file' }]]
      : SCRIPT(false));
    if (test) th.thread.state = 'waiting';
    runEvent(r); changed(t.id);
    return structuredClone(r);
  }

  return {
    seed,
    async tasks({ q, project } = {}) {
      seed(); await net();
      const qq = (q || '').toLowerCase();
      return [...tasks.values()].filter(t => (!qq || t.name.toLowerCase().includes(qq) || t.instructions.toLowerCase().includes(qq))
        && (!project || (project === 'none' ? !t.project_id : t.project_id === project)))
        .sort((x, y) => (y.enabled - x.enabled) || ((x.next_due ?? 1e18) - (y.next_due ?? 1e18)) || x.name.localeCompare(y.name)).map(row);
    },
    async task(kid) { seed(); await net(); return row(K(kid)); },
    async createTask(body = {}) {
      seed(); await net();
      const t = make(body), found = check(t);
      if (t.enabled && found.problems.length) { t.enabled = false; t.next_due = null; }
      changed(t.id);
      return { ...row(t), check: found };
    },
    async patchTask(kid, patch = {}) {
      seed(); await net();
      const t = K(kid), was = t.enabled, next = clean(patch, t);
      Object.assign(t, next, { updated: now() });
      if (!t.enabled) t.next_due = null;
      else if (patch.schedule || !was || t.next_due == null) t.next_due = nextAfter(t.schedule, now());
      const found = check(t);
      if (t.enabled && found.problems.length) { t.enabled = false; t.next_due = null; changed(kid); throw problems409(found, t); }
      changed(kid);
      return row(t);
    },
    async deleteTask(kid) {
      seed(); await net(); K(kid);
      let n = 0;
      for (const t of threads.values()) if (t.thread.settings?.task === kid) { delete t.thread.settings.task; delete t.thread.settings.task_run; delete t.thread.settings.unattended; n++; }
      for (const r of runsOf(kid)) runs.delete(r.id);
      tasks.delete(kid); changed(kid);
      return { deleted: kid, chats: n, environment: 'none' };
    },
    async taskRuns(kid) { seed(); await net(); K(kid); return structuredClone(runsOf(kid)); },
    async seeRun(kid, rid_, seen = true) { seed(); await net(); const r = runs.get(rid_); if (!r || r.task_id !== kid) throw err(404, `no run '${rid_}'`, 'unknown_run'); r.seen = seen; runEvent(r); changed(kid); return structuredClone(r); },
    async tasksUnread() { seed(); await net(); const out = {}; for (const r of runs.values()) if (!r.seen) out[r.task_id] = (out[r.task_id] || 0) + 1;
      return { count: Object.values(out).reduce((a, b) => a + b, 0), tasks: out }; },
    async runTask(kid) { seed(); await net(); const t = K(kid), found = check(t); if (found.problems.length) throw problems409(found, t); return start(t, 'run now'); },
    async testTask(kid) { seed(); await net(); return start(K(kid), 'test', true); },
    async checkTask(kid) { seed(); await net(); return check(K(kid)); },
    async taskNotes(kid) { seed(); await net(); K(kid); return structuredClone(notes.get(kid)); },
    async addTaskNote(kid, text) {
      seed(); await net(); K(kid);
      const s = String(text || '').trim().replace(/\s+/g, ' ');
      if (!s) throw err(422, 'a note needs some text', 'empty_note');
      if (s.length > 500) throw err(422, 'a note is at most 500 characters', 'too_long');
      if (notes.get(kid).length >= 20) throw err(409, 'a task keeps at most 20 notes; replace or remove one', 'too_many_notes');
      const n = { id: rid('n_').slice(0, 12), task_id: kid, text: s, thread_id: null, added: now(), updated: now() };
      notes.get(kid).push(n); return structuredClone(n);
    },
    async patchTaskNote(kid, nid, text) { seed(); await net(); const n = (notes.get(kid) || []).find(x => x.id === nid); if (!n) throw err(404, `no note '${nid}'`, 'unknown_note');
      n.text = String(text).trim(); n.updated = now(); return structuredClone(n); },
    async removeTaskNote(kid, nid) { seed(); await net(); notes.set(kid, (notes.get(kid) || []).filter(x => x.id !== nid)); return { deleted: nid }; },
    async taskFolders(kid) { seed(); await net(); K(kid); return structuredClone(folders.get(kid)); },
    async addTaskFolder(kid, { path, level = 'read' } = {}) {
      seed(); await net(); const t = K(kid);
      if (/\/GAIFA(\/|$)/.test(path) && level !== 'read') throw err(422, `${path} can't go above Read`, 'capped');
      const f = { id: path.replace(/\/+$/, '').split('/').pop().toLowerCase(), path, level, name: '', exists: true };
      t.own_env = t.own_env || 'task-' + t.id.slice(2); folders.get(kid).push(f); changed(kid); return structuredClone(f);
    },
    async patchTaskFolder(kid, fid, { level }) { seed(); await net(); const f = (folders.get(kid) || []).find(x => x.id === fid); if (!f) throw err(404, `no folder ${fid}`, 'unknown_folder'); f.level = level; return structuredClone(f); },
    async removeTaskFolder(kid, fid) { seed(); await net(); folders.set(kid, (folders.get(kid) || []).filter(x => x.id !== fid)); return { removed: fid }; },
    async runAllows(kid, rid_) {
      seed(); await net(); const r = runs.get(rid_), t = K(kid);
      if (!r || r.task_id !== kid) throw err(404, `no run '${rid_}'`, 'unknown_run');
      return r.test && !(t.allow.tools || []).includes('workspace_write') ? [{ kind: 'tool', value: 'workspace_write', tool: 'workspace_write', count: 1 }] : [];
    },
    async addAllows(kid, body = {}) {
      seed(); await net(); const t = K(kid);
      for (const k of ['tools', 'sites', 'mcp']) for (const v of body[k] || []) if (!t.allow[k].includes(v)) t.allow[k].push(v);
      changed(kid); return row(t);
    },
    async runLog(kid, rid_) {
      seed(); await net(); const r = runs.get(rid_);
      if (!r || r.task_id !== kid) throw err(404, `no run '${rid_}'`, 'unknown_run');
      const th = threads.get(r.thread_id);
      if (!th) return [];
      const ev = th.events, res = id => ev.find(e => e.type === 'tool_result' && e.payload.id === id)?.payload, ap = id => ev.find(e => e.type === 'approval' && e.payload.id === id);
      return ev.filter(e => e.type === 'tool_call').map(e => {
        const x = res(e.payload.id), base = { seq: e.seq, tool: e.payload.name, summary: `${e.payload.name}: ${JSON.stringify(e.payload.arguments)}` };
        if (x?.grant_id) return { ...base, outcome: 'allowed', by: 'pre-allow', reason: 'the task allows it ahead of time' };
        if (x?.error?.code === 'unattended') return { ...base, outcome: 'refused', by: x.judge ? 'judge' : 'mode', reason: x.judge?.reason || x.error.detail };
        if (ap(e.payload.id)) return { ...base, outcome: 'pending', by: 'you', reason: 'waiting for your answer' };
        return { ...base, outcome: 'allowed', by: 'mode', reason: 'the mode and the tool’s risk let it run' };
      });
    },
    watchTasks(onEvent) { seed(); watchers.add(onEvent); return { close() { watchers.delete(onEvent); } }; },
  };
}
