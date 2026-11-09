// The side column of a scheduled task's page (plan scheduled-tasks 4.4), and a project's Scheduled panel (4.5). The page's: the run's judgement log, the
// pre-allows a test run suggests (each with Add), the task's notes on how to do it (edit, remove, add), its own folders,
// and what it's allowed. Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, Badge, inputSt, label11, MONO } from './chat-ui.js';
import { Panel } from './chat-project-panels.js';
import { whenWords } from './chat-when.js';
import { TaskEditor } from './chat-task-edit.js';

const R = () => globalThis.React;
const LEVELS = [['read', 'Read'], ['edit', 'Edit'], ['run', 'Run'], ['run_net', 'Run + internet']];
export const OUTCOME_TONE = { allowed: 'green', refused: 'red', denied: 'red', asked: 'purple', pending: 'dim' };
export const BY_WORD = { 'pre-allow': 'pre-allowed', rules: 'rules', judge: 'the judge', mode: 'the mode', you: 'you', local: 'the agent' };
const muted = text => h('div', { style: { fontSize: 12, color: T.mut } }, text);
const rowSt = { display: 'flex', alignItems: 'center', gap: 8, minHeight: 28, fontSize: 12.5, minWidth: 0 };
const ell = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 };
const iconBtn = (icon, label, onClick) => h('button', { type: 'button', onClick, title: label, 'aria-label': label,
  style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 3, display: 'flex', flex: 'none' } }, h(Icon, { d: icon, size: 13 }));

/** A suggestion's words: "the tool workspace_write", "the site example.com", "the MCP server blender". */
export const allowWords = s => ({ tool: 'the tool ', site: 'the site ', mcp: 'the MCP server ' }[s.kind] || '') + s.value;
/** A suggestion as `POST …/allow`'s body. */
export const allowBody = s => ({ [{ tool: 'tools', site: 'sites', mcp: 'mcp' }[s.kind]]: [s.value] });

export function LogPanel({ c, t, run }) {
  const React = R(), [rows, setRows] = React.useState(null);
  React.useEffect(() => { setRows(null); if (run?.thread_id) c.runLog(t.id, run.id).then(setRows, () => setRows([])); else setRows([]); }, [run?.id, run?.ended, run?.state]);
  return h(Panel, { title: 'Judgement log', icon: 'shield', count: rows ? rows.length : null },
    !run ? muted('No run yet.') : rows == null ? muted('Loading…') : !rows.length ? muted('This run called no tools.') :
      rows.map(r => h('div', { key: r.seq, style: { display: 'flex', flexDirection: 'column', gap: 2, padding: '5px 0', borderBottom: '1px solid ' + T.bd } },
        h('div', { style: rowSt }, h(Badge, { tone: OUTCOME_TONE[r.outcome] || 'dim' }, r.outcome),
          h('span', { title: r.summary, style: { ...ell, flex: 1, fontFamily: MONO, fontSize: 11.5 } }, r.summary)),
        h('span', { style: { fontSize: 11.5, color: T.mut } }, `By ${BY_WORD[r.by] || r.by}: ${r.reason}`))));
}

export function AllowsPanel({ c, t, run, toast, onAdded }) {
  const React = R(), [list, setList] = React.useState(null);
  const load = () => (run?.thread_id ? c.runAllows(t.id, run.id).then(setList, () => setList([])) : setList([]));
  React.useEffect(() => { load(); }, [run?.id, run?.state, t.updated]);
  if (!run?.test) return null;
  const add = async s => {
    try { await c.addAllows(t.id, allowBody(s)); toast(`Allowed ${allowWords(s)} ahead of time`, 'success'); load(); onAdded?.(); }
    catch (e) { toast([e?.detail, e?.data?.problems?.[0]?.fix].filter(Boolean).join(' — ') || 'Not added', 'error'); onAdded?.(); }
  };
  return h(Panel, { title: 'From this test run', icon: 'check', count: list ? list.length : null },
    muted('What you approved while watching. Allow it ahead of time, and the scheduled runs won’t need a card for it.'),
    list == null ? muted('Loading…') : !list.length ? muted('Nothing to add: everything you approved is allowed already.') :
      list.map(s => h('div', { key: s.kind + s.value, style: rowSt }, h('span', { style: { ...ell, flex: 1 } }, allowWords(s), s.count > 1 ? ` (${s.count}×)` : ''),
        h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Allow', onClick: () => add(s) }))));
}

export function NotesPanel({ c, t, toast }) {
  const React = R(), [list, setList] = React.useState(null), [text, setText] = React.useState(''), [edit, setEdit] = React.useState(null);
  const load = () => c.taskNotes(t.id).then(setList, () => setList([]));
  React.useEffect(() => { load(); }, [t.id, t.last_run?.id]);
  const fail = e => toast(e?.detail || 'Not saved', 'error');
  const add = async e => { e?.preventDefault?.(); if (!text.trim()) return; try { await c.addTaskNote(t.id, text); setText(''); load(); } catch (x) { fail(x); } };
  const save = async () => { try { await c.patchTaskNote(t.id, edit.id, edit.text); setEdit(null); load(); } catch (x) { fail(x); } };
  return h(Panel, { title: 'Notes on how to do it', icon: 'bulb', count: list ? list.length : null },
    muted('Its runs keep these with task_note, and read them next time. Not results, nothing about you.'),
    list == null ? muted('Loading…') : list.map(n => edit?.id === n.id
      ? h('div', { key: n.id, style: { display: 'flex', gap: 6 } },
        h('input', { autoFocus: true, value: edit.text, maxLength: 500, onChange: e => setEdit({ ...edit, text: e.target.value }), 'aria-label': 'Note',
          onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); save(); } if (e.key === 'Escape') setEdit(null); }, style: { ...inputSt, flex: 1, height: 28 } }),
        h(Btn, { kind: 'pri', sm: true, label: 'Save', onClick: save }))
      : h('div', { key: n.id, style: { ...rowSt, alignItems: 'flex-start' } },
        h('span', { style: { flex: 1, minWidth: 0, color: T.tx, lineHeight: 1.45 } }, n.text),
        iconBtn('edit', 'Change this note', () => setEdit({ id: n.id, text: n.text })),
        iconBtn('x', 'Remove this note', () => c.removeTaskNote(t.id, n.id).then(load, fail)))),
    h('form', { onSubmit: add, style: { display: 'flex', gap: 6 } },
      h('input', { value: text, onChange: e => setText(e.target.value), maxLength: 500, placeholder: 'Add a note', 'aria-label': 'Add a note', style: { ...inputSt, flex: 1, height: 28 } }),
      h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Add', onClick: add })));
}

export function TaskFoldersPanel({ c, t, api, toast, project }) {
  const React = R(), [own, setOwn] = React.useState(null), [adding, setAdding] = React.useState(false), [path, setPath] = React.useState('');
  const load = () => c.taskFolders(t.id).then(setOwn, () => setOwn([]));
  React.useEffect(() => { load(); }, [t.id, t.updated]);
  const fail = e => toast([e?.detail, e?.data?.fix].filter(Boolean).join(' — ') || 'Not changed', 'error');
  const addFolder = async v => {
    const fp = String(v || '').trim();
    if (!fp) return;
    try { await c.addTaskFolder(t.id, { path: fp, level: 'read' }); setPath(''); setAdding(false); load(); } catch (e) { fail(e); }
  };
  const pick = async () => {
    try {
      const r = (await api.callService('workspace', 'POST', '/v1/pick-folder', { json: { start: '/', title: 'Add a folder to the task' } })).json;
      if (r?.path) addFolder(r.path); else if (!r?.cancelled) setAdding(true);
    } catch { setAdding(true); }
  };
  const where = !project ? 'A run works only in these (or in Default when there are none).'
    : t.only_own ? `A run works only in these, not in ${project.name}’s folders.` : `A run works in these and in ${project.name}’s folders.`;
  return h(Panel, { title: 'Folders', icon: 'folder', actions: h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Add folder', onClick: pick }) },
    muted(where + ' They start at Read; a level above lets runs change things there.'),
    adding ? h('form', { onSubmit: e => { e.preventDefault(); addFolder(path); }, style: { display: 'flex', gap: 6 } },
      h('input', { autoFocus: true, value: path, onChange: e => setPath(e.target.value), placeholder: '/home/you/folder', 'aria-label': 'Folder path', style: { ...inputSt, flex: 1, height: 28, fontFamily: MONO, fontSize: 12 } }),
      h(Btn, { kind: 'pri', sm: true, label: 'Add', onClick: () => addFolder(path) })) : null,
    own == null ? muted('Loading…') : own.map(f => h('div', { key: f.id, style: rowSt },
      h(Icon, { d: 'folder', size: 13 }), h('span', { title: f.path, style: { ...ell, flex: 1, fontFamily: MONO, fontSize: 11.5, color: f.exists === false ? T.rd : T.tx } }, f.path),
      h('select', { value: f.level, 'aria-label': `Level of ${f.path}`, onChange: e => c.patchTaskFolder(t.id, f.id, { level: e.target.value }).then(load, fail),
        style: { ...inputSt, height: 26, fontSize: 11.5, cursor: 'pointer' } }, LEVELS.map(([k, l]) => h('option', { key: k, value: k }, l))),
      iconBtn('x', `Remove ${f.path} from the task (its files are left alone)`, () => c.removeTaskFolder(t.id, f.id).then(load, fail)))));
}

/** A project's page's Scheduled panel (plan scheduled-tasks 4.5): its tasks with their next run (a dot while one has
 * unread runs), and New task with the project chosen. */
export function ScheduledPanel({ p, shared, go = x => { location.hash = x; } }) {
  const React = R(), { c } = shared, [list, setList] = React.useState(null), [editing, setEditing] = React.useState(false);
  const load = () => (c.tasks ? c.tasks({ project: p.id }).then(setList, () => setList([])) : setList([]));
  React.useEffect(() => { load(); const w = c.watchTasks?.(() => load()); return () => w?.close(); }, [p.id]);
  return h(Panel, { title: 'Scheduled', icon: 'clock', count: list ? list.length : null,
    actions: h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'New task', onClick: () => setEditing(true) }) },
    list == null ? muted('Loading…') : !list.length ? muted('Tasks that run in this project on a schedule, with its instructions, folders and memory.') :
      list.map(t => h('a', { key: t.id, href: '#/chat/tasks/' + encodeURIComponent(t.id), style: { ...rowSt, color: t.enabled ? T.tx : T.dim, textDecoration: 'none' } },
        h(Icon, { d: 'clock', size: 13 }), h('span', { style: { ...ell, flex: 1 } }, t.name),
        t.unread ? h('span', { 'aria-label': `${t.unread} new`, style: { width: 7, height: 7, borderRadius: 99, background: T.acc, flex: 'none' } }) : null,
        h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, t.enabled && t.next_due ? whenWords(t.next_due) : 'off'))),
    editing ? h(TaskEditor, { shared, preset: { project_id: p.id }, onClose: () => setEditing(false),
      onSaved: t => { setEditing(false); go('#/chat/tasks/' + encodeURIComponent(t.id)); } }) : null);
}

export function AllowedPanel({ t }) {
  const a = t.allow || {}, any = (a.tools || []).length + (a.sites || []).length + (a.mcp || []).length;
  const line = (label, list) => (list || []).length ? h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', fontSize: 12 } },
    h('span', { style: { color: T.mut, width: 74 } }, label), list.map(x => h(Badge, { key: x, mono: true }, x === '*' ? 'every site' : x))) : null;
  return h(Panel, { title: 'Allowed ahead of time', icon: 'check', count: any, open: false },
    any ? null : muted('Nothing yet: what would ask is refused. A test run shows what to allow.'),
    line('Tools', a.tools), line('Sites', a.sites), line('MCP', a.mcp),
    h('span', { style: { ...label11, marginTop: 6 } }, 'Memory'),
    muted(`${t.use_profile ? 'Uses your profile' : 'Leaves your profile out'}${t.project_id ? `; ${t.use_project_memory ? 'uses' : 'leaves out'} the project’s memory` : ''}.`));
}
