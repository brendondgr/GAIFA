// A project's page (plan projects 5.2): `#/chat/projects/<id>` in the Chat page's main area. The left column has the
// name (rename in place) and description, a composer for a new chat in the project (a bare ChatPane: the shared
// composer with the project's model and mode, changeable for this chat; its first message makes the chat, which opens
// in the panes), and Recents: the project's chats, newest first, 20 then Show all. The right column has the panels
// (chat-project-panels.js) and Delete project, whose confirm says what stays. The page follows the agent's `project`
// and `project_source` events. Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, inputSt, label11, fmtAgo, useWidth } from './chat-ui.js';
import { ChatPane } from './chat-pane.js';
import { InstructionsPanel, FilesPanel, PagesPanel, MemoryPanel, FoldersPanel, DefaultsPanel } from './chat-project-panels.js';

const R = () => globalThis.React;
export const RECENTS = 20;

/** What deleting a project removes and what stays (the confirm's words). */
export const DELETE_BODY = 'Its chats stay, as ordinary chats in your history. Its memory stays in Memory (you can delete it there). '
  + 'Its uploaded files stay in Outputs. The project, its instructions, its page links, its search index and its own folders’ '
  + 'environment are deleted (the folders’ files are left alone).';

/** The settings a new chat in the project starts with (the agent fills the rest of its defaults). */
export const newChatPreset = p => ({ model: p?.defaults?.model || null, mode: p?.defaults?.mode || 'manual',
  settings: { project: p.id, ...((p.environments || [])[0] ? { environment: p.environments[0] } : {}) } });

export function ProjectPage({ shared, pid, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect } = React;
  const { c, api, toast, confirm, fail, models, tools, envs, settings, openOutput } = shared;
  const [p, setP] = useState(null), [chats, setChats] = useState(null), [all, setAll] = useState(false), [gone, setGone] = useState(false);
  const [ref, width] = useWidth(1000), narrow = width < 860;
  const load = () => c.project(pid).then(x => { setP(x); setGone(false); }, e => { if (e?.status === 404) setGone(true); else fail(e); });
  const loadChats = (n = all ? 200 : RECENTS + 1) => c.projectThreads(pid, { limit: n }).then(setChats, () => setChats([]));
  useEffect(() => { setP(null); setChats(null); load(); loadChats(); }, [pid]);
  useEffect(() => {
    const w = c.watchProjects?.(ev => { if (ev.id === pid) { if (ev.type === 'project' && ev.project === null) setGone(true); else load(); } });
    return () => w?.close();
  }, [pid]);
  if (gone) return h('div', { ref, style: { flex: 1, padding: 32, color: T.mut } }, 'This project was deleted. ', h('a', { href: '#/chat/projects' }, 'All projects'));
  if (!p) return h('div', { ref, style: { flex: 1, padding: 32, color: T.mut } }, 'Loading…');
  const save = patch => c.patchProject(pid, patch).then(setP, e => { toast(e?.detail || 'Not saved', 'error'); throw e; });
  const remove = async () => {
    const ok = confirm ? await confirm({ title: `Delete the project “${p.name}”?`, body: DELETE_BODY, confirmLabel: 'Delete project', danger: true }) : window.confirm(DELETE_BODY);
    if (!ok) return;
    try { await c.deleteProject(pid); toast('Project deleted; its chats stay', 'success'); shared.relist?.(); go('#/chat/projects'); } catch (e) { fail(e); }
  };
  const shownChats = (chats || []).slice(0, all ? undefined : RECENTS);
  const left = h('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 } },
    h('a', { href: '#/chat/projects', style: { fontSize: 12.5, color: T.mut, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 } }, h(Icon, { d: 'chevL', size: 12 }), 'All projects'),
    h(InPlace, { value: p.name, label: 'Project name', big: true, onSave: name => save({ name }) }),
    h(InPlace, { value: p.description || '', label: 'Description', placeholder: 'Add a description', multiline: true, onSave: description => save({ description }) }),
    h('div', { style: { border: '1px solid ' + T.bd, borderRadius: 12, overflow: 'hidden', minHeight: 120, display: 'flex' } },
      h(ChatPane, { shared, tid: null, bare: true, preset: newChatPreset(p), placeholder: `New chat in ${p.name}`,
        onOpen: id => { if (id) go('#/chat/' + encodeURIComponent(id)); } })),
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } },
      h('span', { style: { ...label11, marginBottom: 4 } }, 'Recents'),
      chats == null ? h('div', { style: { color: T.mut, fontSize: 12.5 } }, 'Loading…') :
      !chats.length ? h('div', { style: { color: T.mut, fontSize: 12.5 } }, 'No chats yet: start one above.') :
      shownChats.map(t => h('a', { key: t.id, href: '#/chat/' + encodeURIComponent(t.id), className: 'aichat-precent',
        style: { display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, color: T.tx, textDecoration: 'none', borderBottom: '1px solid ' + T.bd } },
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 } }, t.title || 'New chat'),
        h('span', { style: { fontSize: 11.5, color: T.dim, flex: 'none' } }, fmtAgo(t.updated)))),
      !all && (chats || []).length > RECENTS ? h('button', { type: 'button', onClick: () => { setAll(true); loadChats(200); },
        style: { alignSelf: 'flex-start', marginTop: 6, border: 0, background: 'none', color: T.mut, font: 'inherit', fontSize: 12.5, cursor: 'pointer' } }, 'Show all') : null));
  const right = h('aside', { 'aria-label': 'Project', style: { width: narrow ? '100%' : 330, flex: 'none', display: 'flex', flexDirection: 'column', gap: 10 } },
    h(InstructionsPanel, { p, onSave: save }),
    h(FilesPanel, { p, c, api, toast, openOutput }),
    h(PagesPanel, { p, c, toast }),
    h(MemoryPanel, { p, c, toast }),
    h(FoldersPanel, { p, c, api, envs, toast }),
    h(DefaultsPanel, { p, models, tools, skills: settings?.skills || [], onSave: save }),
    h('button', { type: 'button', onClick: remove, style: { alignSelf: 'flex-start', border: 0, background: 'none', color: T.rd, font: 'inherit', fontSize: 12.5, cursor: 'pointer', padding: '6px 2px' } },
      'Delete project…'));
  return h('div', { ref, style: { flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', background: T.bg } },
    h('div', { style: { maxWidth: 1120, margin: '0 auto', padding: narrow ? '14px 16px 28px' : '24px 28px 40px', display: 'flex', flexDirection: narrow ? 'column' : 'row', gap: 24, alignItems: narrow ? 'stretch' : 'flex-start' } },
      shared.onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: shared.onMenu }) : null, left, right));
}

/** Text that turns into a box on click: Enter (or leaving it) saves, Escape goes back. */
function InPlace({ value, label, onSave, big = false, multiline = false, placeholder = '' }) {
  const React = R(), [edit, setEdit] = React.useState(null);
  const done = async () => { const v = (edit ?? '').trim(); setEdit(null); if (v !== value && (v || !big)) { try { await onSave(v); } catch { /* toasted */ } } };
  const st = big ? { fontSize: 22, fontWeight: 600, letterSpacing: '-.01em' } : { fontSize: 13, color: T.mut, lineHeight: 1.5 };
  if (edit != null) {
    const props = { autoFocus: true, value: edit, 'aria-label': label, onChange: e => setEdit(e.target.value), onBlur: done,
      onKeyDown: e => { if (e.key === 'Enter' && (!multiline || !e.shiftKey)) { e.preventDefault(); done(); } if (e.key === 'Escape') setEdit(null); },
      style: { ...inputSt, ...st, height: big ? 40 : 'auto', padding: '6px 9px', width: '100%', resize: 'vertical', fontFamily: 'inherit' } };
    return multiline ? h('textarea', { ...props, rows: 3 }) : h('input', props);
  }
  return h('button', { type: 'button', onClick: () => setEdit(value), title: `Edit the ${label.toLowerCase()}`, 'aria-label': `${label}: ${value || 'none'} (edit)`,
    style: { border: 0, background: 'none', padding: 0, color: value ? (big ? T.tx : T.mut) : T.dim, fontFamily: 'inherit', ...st, cursor: 'text', textAlign: 'left', whiteSpace: 'pre-wrap' } },
    value || placeholder);
}
