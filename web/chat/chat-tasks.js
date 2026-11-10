// Scheduled tasks on the Chat page (plan scheduled-tasks 4.2–4.3): the sidebar's Scheduled row under Projects (an
// accordion like Projects: the row opens `#/chat/tasks`, its chevron folds the tasks open under it, each with its next
// time and a dot while it has unread runs; open or folded kept on the hub as `hub.chat.tasks.open`), and the tasks page:
// a title, a search, New task, and the tasks as cards (on first, then by their next run) with the schedule in words,
// the next and last run, a project chip and an on/off switch. A card opens `#/chat/tasks/<id>` (chat-task.js). Pure
// helpers first (tested in utils/tests/web/chat-tasks.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, inputSt, useWidth } from './chat-ui.js';
import { store } from '../ui-store.js';
import { whenWords } from './chat-when.js';
import { TaskEditor } from './chat-task-edit.js';

const R = () => globalThis.React;
export const OPEN_KEY = 'hub.chat.tasks.open';
const enc = encodeURIComponent;

/** On first, then by the next run (soonest first), then by name, as the agent lists them. */
export function sortTasks(list) {
  return [...(list || [])].sort((a, b) => (!!b.enabled - !!a.enabled) || ((a.next_due ?? 1e18) - (b.next_due ?? 1e18))
    || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
}
/** The tasks whose name or instructions have `q` (any case). */
export function filterTasks(list, q) {
  const s = String(q || '').trim().toLowerCase();
  return s ? (list || []).filter(t => t.name.toLowerCase().includes(s) || String(t.instructions || '').toLowerCase().includes(s)) : [...(list || [])];
}
export const dropdownTasks = (list, n = 8) => sortTasks(list).slice(0, n);
/** Runs not opened yet, over all tasks. */
export const unreadOf = list => (list || []).reduce((n, t) => n + (t.unread || 0), 0);
/** A run's state in a few words: "Done", "Done · 2 refused", "Failed", "Skipped (still running)", "Running", "Late". */
export function runWords(r) {
  if (!r) return 'No runs yet';
  const base = { done: 'Done', failed: 'Failed', skipped: 'Skipped', running: 'Running', queued: 'Queued' }[r.state] || r.state;
  const bits = [r.state === 'skipped' && r.why ? `${base} (${r.why})` : base];
  if (r.test) bits.push('test');
  if (r.late) bits.push('late');
  if (r.refused) bits.push(`${r.refused} refused`);
  return bits.join(' · ');
}
export const runTone = r => (!r ? 'dim' : r.state === 'failed' ? 'red' : r.refused ? 'accent' : r.state === 'done' ? 'green' : r.state === 'running' ? 'cyan' : 'dim');
/** A card's line: "Weekdays at 07:00 · next tomorrow 07:00", or "Off". */
export function cardLine(t, now = Date.now() / 1000) {
  return t.enabled && t.next_due ? `${t.when} · next ${whenWords(t.next_due, now)}` : `${t.when} · off`;
}

export function TasksEntry({ tasks, active = false, current = null, onGo = () => {} }) {
  const React = R(), [open, setOpenS] = React.useState(() => !!store.get(OPEN_KEY, false));
  const setOpen = v => { setOpenS(v); store.set(OPEN_KEY, v); };
  const all = tasks || [], shown = dropdownTasks(all), unread = unreadOf(all);
  const row = { display: 'flex', alignItems: 'center', gap: 8, height: 28, borderRadius: 6, fontSize: 12.5, textDecoration: 'none' };
  const dot = h('span', { 'aria-hidden': true, style: { width: 7, height: 7, borderRadius: 99, background: T.acc, flex: 'none' } });
  return h('div', { style: { display: 'flex', flexDirection: 'column', padding: '0 10px 4px 8px', marginTop: -4 } },
    h('div', { className: 'aichat-newbar', style: { display: 'flex', alignItems: 'center', height: 28, borderRadius: 7, background: active && !current ? T.hov : 'transparent' } },
      h('a', { href: '#/chat/tasks', onClick: () => onGo(), 'aria-current': active && !current ? 'page' : undefined,
        'aria-label': unread ? `Scheduled, ${unread} new run${unread === 1 ? '' : 's'}` : 'Scheduled',
        style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 9, height: 28, padding: '0 6px', color: T.tx, fontSize: 13, textDecoration: 'none' } },
        h('span', { style: { width: 20, height: 20, display: 'grid', placeItems: 'center', color: T.mut, flex: 'none' } }, h(Icon, { d: 'clock', size: 14 })),
        h('span', { style: { flex: 1 } }, 'Scheduled'), unread ? dot : null),
      h('button', { type: 'button', onClick: () => setOpen(!open), 'aria-label': open ? 'Hide scheduled tasks' : 'Show scheduled tasks', 'aria-expanded': open ? 'true' : 'false',
        title: open ? 'Hide scheduled tasks' : 'Show scheduled tasks',
        style: { width: 26, height: 26, marginRight: 1, display: 'grid', placeItems: 'center', border: 0, borderRadius: 6, background: 'transparent', color: T.mut, cursor: 'pointer', flex: 'none' } },
        h(Icon, { d: open ? 'chevD' : 'chevR', size: 12 }))),
    open ? h('div', { role: 'list', 'aria-label': 'Scheduled tasks', style: { display: 'flex', flexDirection: 'column', gap: 1, padding: '1px 0 2px 16px' } },
      shown.length ? shown.map(t => h('a', { key: t.id, role: 'listitem', href: '#/chat/tasks/' + enc(t.id), onClick: () => onGo(), title: `${t.name}: ${cardLine(t)}`,
        'aria-label': t.unread ? `${t.name}, ${t.unread} new` : t.name,
        className: 'aichat-item', 'aria-current': current === t.id ? 'page' : undefined,
        style: { ...row, padding: '0 8px 0 10px', color: current === t.id ? T.tx : t.enabled ? T.mut : T.dim, fontWeight: current === t.id ? 500 : 400, background: current === t.id ? T.hov : 'transparent' } },
        h(Icon, { d: 'clock', size: 12 }),
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t.name),
        t.unread ? dot : h('span', { style: { fontSize: 10.5, color: T.dim, flex: 'none' } }, t.enabled && t.next_due ? whenWords(t.next_due).replace(/^(today|tomorrow) /, '') : 'off')))
        : h('a', { href: '#/chat/tasks', onClick: () => onGo(), style: { ...row, padding: '0 10px', color: T.dim } }, 'No scheduled tasks yet: make one'),
      all.length > shown.length ? h('a', { href: '#/chat/tasks', onClick: () => onGo(), className: 'aichat-item',
        style: { ...row, padding: '0 10px', color: T.dim, fontSize: 12 } }, `All scheduled · ${all.length}`) : null) : null);
}

/** calendar 6.4: `#/chat/tasks?new=once&at=2026-11-14T15:00` (the Calendar's Schedule a task here) opens a new task. */
export function presetOf(hash) {
  const q = new URLSearchParams(String(hash || '').split('?')[1] || '');
  if (q.get('new') !== 'once') return null;
  return { kind: 'once', at: q.get('at') || '', ...(q.get('project') ? { project_id: q.get('project') } : {}) };
}

export function TasksPage({ shared, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect } = React;
  const { c, toast } = shared;
  const [list, setList] = useState(null), [q, setQ] = useState(''), [editing, setEditing] = useState(() => presetOf(globalThis.location?.hash) || false);
  const [ref, width] = useWidth(900), narrow = width < 640;
  const load = () => c.tasks().then(setList, e => { setList([]); toast(e?.detail || 'The scheduled tasks didn’t load', 'error'); });
  useEffect(() => { load(); const w = c.watchTasks?.(() => load()); return () => w?.close(); }, []);
  const toggle = async t => {
    try { await c.patchTask(t.id, { enabled: !t.enabled }); load(); toast(t.enabled ? `${t.name} is off` : `${t.name} is on`, 'success'); }
    catch (e) { load(); toast([e?.detail, e?.data?.problems?.[0]?.fix].filter(Boolean).join(' — ') || 'Not changed', 'error'); }
  };
  const shown = sortTasks(filterTasks(list, q));
  return h('div', { ref, style: { flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', background: T.bg } },
    h('div', { style: { maxWidth: 920, margin: '0 auto', padding: narrow ? '14px 16px 28px' : '28px 28px 40px', display: 'flex', flexDirection: 'column', gap: 16 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
        shared.onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: shared.onMenu }) : null,
        h('h1', { style: { margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-.01em', flex: 1 } }, 'Scheduled'),
        h(Btn, { kind: 'pri', sm: true, icon: 'plus', label: 'New task', onClick: () => setEditing(true) })),
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 7, ...inputSt, height: 34, borderRadius: 8 } },
        h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: 'search', size: 14 })),
        h('input', { value: q, onChange: e => setQ(e.target.value), placeholder: 'Search scheduled tasks', 'aria-label': 'Search scheduled tasks',
          style: { flex: 1, minWidth: 0, border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 13 } })),
      list == null ? h('div', { style: { color: T.mut, padding: 20 } }, 'Loading…') :
      !list.length ? h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '48px 0', color: T.mut, textAlign: 'center' } },
        h('span', null, 'A scheduled task starts a chat on its own: hourly, daily, on weekdays, weekly or monthly. No one watches it, so what it may do is set ahead of time.'),
        h(Btn, { kind: 'pri', sm: true, icon: 'plus', label: 'New task', onClick: () => setEditing(true) })) :
      !shown.length ? h('div', { style: { color: T.mut, padding: 20 } }, `No tasks match “${q}”.`) :
      h('div', { role: 'list', style: { display: 'grid', gridTemplateColumns: narrow ? '1fr' : '1fr 1fr', gap: 10 } },
        shown.map(t => h(TaskCard, { key: t.id, t, project: (shared.projects || []).find(p => p.id === t.project_id), onToggle: () => toggle(t) })))),
    editing ? h(TaskEditor, { shared, preset: editing === true ? {} : editing, onClose: () => setEditing(false), onSaved: t => { setEditing(false); go('#/chat/tasks/' + enc(t.id)); } }) : null);
}

export function Switch({ on, label, onChange }) {
  return h('button', { type: 'button', role: 'switch', 'aria-checked': on ? 'true' : 'false', 'aria-label': label, title: label, onClick: onChange,
    style: { width: 34, height: 20, borderRadius: 99, border: 0, padding: 2, background: on ? T.acc : T.bds, cursor: 'pointer', flex: 'none', display: 'flex',
      justifyContent: on ? 'flex-end' : 'flex-start', transition: 'background .15s' } },
    h('span', { style: { width: 16, height: 16, borderRadius: 99, background: on ? '#1a1300' : T.mut } }));
}

function TaskCard({ t, project, onToggle }) {
  const last = t.last_run;
  return h('div', { role: 'listitem', className: 'aichat-pcard', style: { position: 'relative' } },
    h('a', { href: '#/chat/tasks/' + enc(t.id), style: { display: 'flex', gap: 12, alignItems: 'flex-start', padding: '14px 14px', borderRadius: 10, border: '1px solid ' + T.bd,
      background: T.card, color: T.tx, textDecoration: 'none', minHeight: 92, opacity: t.enabled ? 1 : 0.75 } },
      h('span', { style: { width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: T.tcy, color: T.cy, flex: 'none' } }, h(Icon, { d: 'clock', size: 17 })),
      h('span', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 } },
        h('span', { style: { fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 40, display: 'flex', alignItems: 'center', gap: 6 } },
          t.name, t.unread ? h('span', { 'aria-label': `${t.unread} new`, style: { width: 7, height: 7, borderRadius: 99, background: T.acc, flex: 'none' } }) : null),
        h('span', { style: { fontSize: 12.5, color: T.mut } }, cardLine(t)),
        h('span', { style: { fontSize: 11.5, color: T.dim, marginTop: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } },
          project ? h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4, color: T.pu } }, h(Icon, { d: 'folder', size: 11 }), project.name) : null,
          h('span', { style: { color: last && (last.state === 'failed' || last.refused) ? (last.state === 'failed' ? T.rd : T.acc) : T.dim } },
            last ? `Last: ${runWords(last)}, ${whenWords(last.started || last.due)}` : 'No runs yet')))),
    h('span', { style: { position: 'absolute', top: 12, right: 12 } }, h(Switch, { on: t.enabled, label: `${t.enabled ? 'Turn off' : 'Turn on'} ${t.name}`, onChange: onToggle })));
}
