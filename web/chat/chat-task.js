// A scheduled task's page (plan scheduled-tasks 4.4): `#/chat/tasks/<id>` in the Chat page's main area. The left
// column has the name, the schedule and its next run, the on/off switch, Run now, Test run, Edit and Delete, the
// instructions, and the runs, newest first: each with its state (done, failed, skipped, late, test, how many calls were
// refused) and a dot while unread; picking one shows its judgement log on the right, Open chat opens its chat (which
// marks it seen). The right column (chat-task-panels.js) has the log, a test run's suggested pre-allows, the notes, the
// folders and what's allowed. The page follows the agent's `task` and `task_run` events. Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, Badge, label11, useWidth } from './chat-ui.js';
import { whenWords } from './chat-when.js';
import { runWords, runTone, Switch } from './chat-tasks.js';
import { TaskEditor } from './chat-task-edit.js';
import { LogPanel, AllowsPanel, NotesPanel, TaskFoldersPanel, AllowedPanel } from './chat-task-panels.js';

const R = () => globalThis.React;
const enc = encodeURIComponent;
export const DELETE_BODY = 'Its runs stay, as ordinary chats in your history. Its notes, its schedule and its own folders’ environment are '
  + 'deleted (the folders’ files are left alone).';
/** The run the log shows: the one picked, else the newest that ran. */
export const pickRun = (runs, id) => (runs || []).find(r => r.id === id) || (runs || []).find(r => r.thread_id) || null;

export function TaskPage({ shared, kid, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect } = React;
  const { c, api, toast, confirm, fail } = shared;
  const [t, setT] = useState(null), [runs, setRuns] = useState(null), [gone, setGone] = useState(false), [pick, setPick] = useState(null);
  const [editing, setEditing] = useState(false), [busy, setBusy] = useState(null);
  const [ref, width] = useWidth(1000), narrow = width < 860;
  const load = () => c.task(kid).then(x => { setT(x); setGone(false); }, e => { if (e?.status === 404) setGone(true); else fail(e); });
  const loadRuns = () => c.taskRuns(kid, { limit: 100 }).then(setRuns, () => setRuns([]));
  useEffect(() => { setT(null); setRuns(null); setPick(null); load(); loadRuns(); }, [kid]);
  useEffect(() => {
    const w = c.watchTasks?.(ev => {
      if (ev.type === 'task' && ev.id === kid) { if (ev.task === null) setGone(true); else setT(ev.task); }
      if (ev.type === 'task_run' && ev.task_id === kid) loadRuns();
    });
    return () => w?.close();
  }, [kid]);
  if (gone) return h('div', { ref, style: { flex: 1, padding: 32, color: T.mut } }, 'This task was deleted. ', h('a', { href: '#/chat/tasks' }, 'All scheduled tasks'));
  if (!t) return h('div', { ref, style: { flex: 1, padding: 32, color: T.mut } }, 'Loading…');
  const problems = e => toast([e?.detail, e?.data?.problems?.[0]?.fix].filter(Boolean).join(' — ') || 'Not done', 'error');
  const toggle = async () => { try { setT(await c.patchTask(kid, { enabled: !t.enabled })); } catch (e) { load(); problems(e); } };
  const start = async test => {
    setBusy(test ? 'test' : 'run');
    try {
      const r = await (test ? c.testTask(kid) : c.runTask(kid));
      await loadRuns(); setPick(r.id);
      if (test && r.thread_id) go('#/chat/' + enc(r.thread_id));            // a test run is watched: open its chat
      else toast(r.state === 'skipped' ? `Skipped: ${r.why}` : r.state === 'queued' ? 'Queued: other runs are going' : 'Started; it runs in the background', r.state === 'skipped' ? 'error' : 'success');
    } catch (e) { problems(e); }
    setBusy(null);
  };
  const remove = async () => {
    const ok = confirm ? await confirm({ title: `Delete the task “${t.name}”?`, body: DELETE_BODY, confirmLabel: 'Delete task', danger: true }) : window.confirm(DELETE_BODY);
    if (!ok) return;
    try { await c.deleteTask(kid); toast('Task deleted; its runs stay as chats', 'success'); shared.relist?.(); go('#/chat/tasks'); } catch (e) { fail(e); }
  };
  const project = (shared.projects || []).find(p => p.id === t.project_id) || null;
  const run = pickRun(runs, pick);
  const open = r => { if (!r.seen) c.seeRun(kid, r.id).catch(() => {}); go('#/chat/' + enc(r.thread_id)); };
  const left = h('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 } },
    h('a', { href: '#/chat/tasks', style: { fontSize: 12.5, color: T.mut, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 } }, h(Icon, { d: 'chevL', size: 12 }), 'All scheduled'),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
      h('h1', { style: { margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-.01em', flex: 1, minWidth: 0 } }, t.name),
      h(Switch, { on: t.enabled, label: t.enabled ? 'Turn off' : 'Turn on', onChange: toggle })),
    h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 13, color: T.mut } },
      h(Icon, { d: 'clock', size: 13 }), t.when, h('span', null, '·'), t.enabled && t.next_due ? `next ${whenWords(t.next_due)}` : 'off',
      project ? h('a', { href: '#/chat/projects/' + enc(project.id), style: { display: 'inline-flex', alignItems: 'center', gap: 4, color: T.pu, textDecoration: 'none' } },
        h(Icon, { d: 'folder', size: 12 }), project.name) : null,
      h(Badge, { tone: t.mode === 'bypass' ? 'accent' : 'dim' }, { plan: 'Plan', accept_edits: 'Accept edits', auto: 'Auto', bypass: 'Bypass' }[t.mode] || t.mode)),
    h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
      h(Btn, { kind: 'pri', sm: true, icon: 'play', label: busy === 'run' ? 'Starting…' : 'Run now', disabled: !!busy, onClick: () => start(false), title: 'A run with no one watching, as if it were due' }),
      h(Btn, { kind: 'sec', sm: true, icon: 'eye', label: busy === 'test' ? 'Starting…' : 'Test run', disabled: !!busy, onClick: () => start(true),
        title: 'You watch it: its calls show cards, and what you approve can be allowed ahead of time' }),
      h(Btn, { kind: 'ghost', sm: true, icon: 'edit', label: 'Edit', onClick: () => setEditing(true) }),
      h(Btn, { kind: 'ghost', sm: true, icon: 'trash', label: 'Delete', onClick: remove })),
    h('div', { style: { border: '1px solid ' + T.bd, borderRadius: 10, background: T.card, padding: '10px 12px', fontSize: 12.5, color: T.tx, whiteSpace: 'pre-wrap', maxHeight: 180, overflow: 'auto', lineHeight: 1.5 } },
      t.instructions || h('span', { style: { color: T.dim } }, 'No instructions yet.')),
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } },
      h('span', { style: { ...label11, marginBottom: 4 } }, 'Runs'),
      runs == null ? h('div', { style: { color: T.mut, fontSize: 12.5 } }, 'Loading…') :
      !runs.length ? h('div', { style: { color: T.mut, fontSize: 12.5 } }, 'No runs yet. Run now, or try a test run first.') :
      runs.map(r => h('div', { key: r.id, role: 'button', tabIndex: 0, onClick: () => setPick(r.id), onKeyDown: e => { if (e.key === 'Enter') setPick(r.id); },
        'aria-pressed': run?.id === r.id ? 'true' : 'false', className: 'aichat-precent',
        style: { display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', background: run?.id === r.id ? T.hov : 'transparent', borderBottom: '1px solid ' + T.bd } },
        h('span', { 'aria-label': r.seen ? undefined : 'new', style: { width: 7, height: 7, borderRadius: 99, background: r.seen ? 'transparent' : T.acc, flex: 'none' } }),
        h('span', { style: { fontSize: 12.5, color: T.tx, minWidth: 128 } }, whenWords(r.started || r.due)),
        h('span', { style: { flex: 1, minWidth: 0 } }, h(Badge, { tone: runTone(r) }, runWords(r))),
        r.thread_id ? h('button', { type: 'button', onClick: e => { e.stopPropagation(); open(r); }, style: { border: 0, background: 'none', color: T.cy, font: 'inherit', fontSize: 12, cursor: 'pointer' } },
          'Open chat') : null))));
  const right = h('aside', { 'aria-label': 'Task', style: { width: narrow ? '100%' : 340, flex: 'none', display: 'flex', flexDirection: 'column', gap: 10 } },
    h(LogPanel, { c, t, run }),
    h(AllowsPanel, { c, t, run, toast, onAdded: load }),
    h(NotesPanel, { c, t, toast }),
    h(TaskFoldersPanel, { c, t, api, toast, project }),
    h(AllowedPanel, { t }));
  return h('div', { ref, style: { flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', background: T.bg } },
    h('div', { style: { maxWidth: 1120, margin: '0 auto', padding: narrow ? '14px 16px 28px' : '24px 28px 40px', display: 'flex', flexDirection: narrow ? 'column' : 'row', gap: 24, alignItems: narrow ? 'stretch' : 'flex-start' } },
      shared.onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: shared.onMenu }) : null, left, right),
    editing ? h(TaskEditor, { shared, task: t, onClose: () => setEditing(false), onSaved: x => { setEditing(false); setT(x); } }) : null);
}
