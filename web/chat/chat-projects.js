// The projects page (plan projects 5.1): `#/chat/projects` draws `ProjectsPage` in the Chat page's main area. A title,
// a search (name and description), a sort menu (Recent activity, Name, Created; the choice kept on the hub) and New
// project; then the projects as cards in a two-column grid (one column when narrow), pinned first, each with its icon,
// name, description and last activity, and a pin toggle on hover. A card opens `#/chat/projects/<id>`. New project asks
// for a name (required), a description and instructions, makes it and opens it. Pure helpers first (tested in
// utils/tests/web/chat-projects.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, Popover, inputSt, label11, fmtAgo, useWidth, SHADOW, ON_ACC } from './chat-ui.js';
import { store } from '../ui-store.js';

const R = () => globalThis.React;
export const SORTS = [['activity', 'Recent activity'], ['name', 'Name'], ['created', 'Created']];
export const SORT_KEY = 'hub.chat.projects.sort';
const enc = encodeURIComponent;

/** Pinned first, then by `sort` (activity: newest first; name: A to Z; created: newest first), as the agent sorts. */
export function sortProjects(list, sort = 'activity') {
  const by = { name: (a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()), created: (a, b) => (b.created || 0) - (a.created || 0) }[sort]
    || ((a, b) => (b.activity || b.updated || 0) - (a.activity || a.updated || 0));
  return [...(list || [])].sort((a, b) => (!!b.pinned - !!a.pinned) || by(a, b));
}
/** The projects whose name or description has `q` (any case). */
export function filterProjects(list, q) {
  const s = String(q || '').trim().toLowerCase();
  return s ? (list || []).filter(p => p.name.toLowerCase().includes(s) || String(p.description || '').toLowerCase().includes(s)) : [...(list || [])];
}
/** A card's line under the name: its chats and when it was last active. */
export function cardLine(p, now = Date.now() / 1000) {
  const n = p.chats || 0, a = fmtAgo(p.activity || p.updated, now);
  const when = !a ? '' : a === 'now' ? ' · just now' : /^\d/.test(a) ? ` · ${a} ago` : ` · ${a}`;
  return `${n} chat${n === 1 ? '' : 's'}${when}`;
}
/** What New project's dialog sends, or an error to show: a name is needed. */
export function newProjectBody(f) {
  const name = String(f?.name || '').trim().replace(/\s+/g, ' ');
  if (!name) return { error: 'A project needs a name.' };
  return { body: { name, description: String(f.description || '').trim(), instructions: String(f.instructions || '').trim() } };
}

/** The sidebar dropdown's projects (plan projects 5.4): pinned first, then the most recently active, up to `n`. */
export const dropdownProjects = (list, n = 8) => sortProjects(list, 'activity').slice(0, n);

/** The sidebar's Projects row under New (plan projects 5.4): its icon and label open the projects page; the chevron opens
 * a dropdown with the pinned and most recent projects, then All projects. Whether it's open is page state. */
export function ProjectsEntry({ projects, active = false, go = x => { location.hash = x; }, onGo = () => {} }) {
  const React = R(), [open, setOpen] = React.useState(false);
  const nav = to => { setOpen(false); onGo(); go(to); };
  const shown = dropdownProjects(projects || []);
  return h('div', { style: { position: 'relative', display: 'flex', alignItems: 'center', gap: 2, padding: '0 10px 6px 8px' } },
    h('a', { href: '#/chat/projects', onClick: () => { setOpen(false); onGo(); }, className: 'aichat-newbar', 'aria-current': active ? 'page' : undefined,
      style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 9, height: 30, padding: '0 6px', borderRadius: 7, color: T.tx, fontSize: 13, textDecoration: 'none', background: active ? T.hov : 'transparent' } },
      h('span', { style: { width: 20, height: 20, display: 'grid', placeItems: 'center', color: T.mut, flex: 'none' } }, h(Icon, { d: 'folder', size: 14 })), 'Projects'),
    h('button', { type: 'button', onClick: () => setOpen(!open), 'aria-label': 'Projects list', 'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false', className: 'aichat-quiet',
      style: { width: 30, height: 30, display: 'grid', placeItems: 'center', border: '1px solid transparent', borderRadius: 7, background: 'transparent', color: T.mut, cursor: 'pointer', flex: 'none' } },
      h(Icon, { d: open ? 'chevD' : 'chevR', size: 13 })),
    h(Popover, { open, onClose: () => setOpen(false), place: 'down-left', width: 240, label: 'Projects', style: { padding: 4, gap: 0 } },
      shown.length ? shown.map(p => h('button', { key: p.id, type: 'button', role: 'menuitem', onClick: () => nav('#/chat/projects/' + enc(p.id)), title: p.description || p.name,
        style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
        h(Icon, { d: p.pinned ? 'pin' : 'folder', size: 13 }), h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, p.name)))
        : h('span', { style: { fontSize: 12, color: T.mut, padding: '6px 9px' } }, 'No projects yet.'),
      h('button', { type: 'button', role: 'menuitem', onClick: () => nav('#/chat/projects'), style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0,
        borderTop: '1px solid ' + T.bd, borderRadius: 0, background: 'transparent', color: T.mut, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } }, 'All projects')));
}

export function ProjectsPage({ c, toast = () => {}, go = x => { location.hash = x; }, onMenu = null }) {
  const React = R(), { useState, useEffect } = React;
  const [list, setList] = useState(null), [q, setQ] = useState(''), [sort, setSortS] = useState(() => store.get(SORT_KEY, 'activity'));
  const [sortOpen, setSortOpen] = useState(false), [dialog, setDialog] = useState(false);
  const [ref, width] = useWidth(900), narrow = width < 640;
  const load = () => c.projects().then(setList, e => { setList([]); toast(e?.detail || 'The projects didn’t load', 'error'); });
  useEffect(() => { load(); const w = c.watchProjects?.(() => load()); return () => w?.close(); }, []);
  const setSort = s => { setSortS(s); store.set(SORT_KEY, s); setSortOpen(false); };
  const pin = async p => { try { await c.patchProject(p.id, { pinned: !p.pinned }); setList(l => l.map(x => (x.id === p.id ? { ...x, pinned: !p.pinned } : x))); } catch (e) { toast(e?.detail || 'Not pinned', 'error'); } };
  const shown = sortProjects(filterProjects(list, q), sort);
  return h('div', { ref, style: { flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', background: T.bg } },
    h('div', { style: { maxWidth: 920, margin: '0 auto', padding: narrow ? '14px 16px 28px' : '28px 28px 40px', display: 'flex', flexDirection: 'column', gap: 16 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
        onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: onMenu }) : null,
        h('h1', { style: { margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-.01em', flex: 1 } }, 'Projects'),
        h(Btn, { kind: 'pri', sm: true, icon: 'plus', label: 'New project', onClick: () => setDialog(true) })),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('label', { style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 7, ...inputSt, height: 34, borderRadius: 8 } },
          h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: 'search', size: 14 })),
          h('input', { value: q, onChange: e => setQ(e.target.value), placeholder: 'Search projects', 'aria-label': 'Search projects',
            style: { flex: 1, minWidth: 0, border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 13 } })),
        h('span', { style: { position: 'relative' } },
          h('button', { type: 'button', onClick: () => setSortOpen(!sortOpen), 'aria-haspopup': 'menu', 'aria-expanded': sortOpen ? 'true' : 'false',
            style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 34, padding: '0 10px', borderRadius: 8, border: '1px solid ' + T.bds, background: T.card, color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer' } },
            h('span', { style: { color: T.mut } }, 'Sort by'), (SORTS.find(s => s[0] === sort) || SORTS[0])[1], h(Icon, { d: 'chevD', size: 12 })),
          h(Popover, { open: sortOpen, onClose: () => setSortOpen(false), width: 190, label: 'Sort projects', style: { padding: 4, gap: 0 } },
            SORTS.map(([k, l]) => h('button', { key: k, type: 'button', role: 'menuitemradio', 'aria-checked': k === sort ? 'true' : 'false', onClick: () => setSort(k),
              style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: k === sort ? T.hov : 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
              h('span', { style: { width: 14, display: 'flex' } }, k === sort ? h(Icon, { d: 'check', size: 13 }) : null), l))))),
      list == null ? h('div', { style: { color: T.mut, padding: 20 } }, 'Loading…') :
      !list.length ? h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '48px 0', color: T.mut, textAlign: 'center' } },
        h('span', null, 'Projects gather chats around standing instructions, files, web pages and folders.'),
        h(Btn, { kind: 'pri', sm: true, icon: 'plus', label: 'New project', onClick: () => setDialog(true) })) :
      !shown.length ? h('div', { style: { color: T.mut, padding: 20 } }, `No projects match “${q}”.`) :
      h('div', { role: 'list', style: { display: 'grid', gridTemplateColumns: narrow ? '1fr' : '1fr 1fr', gap: 10 } },
        shown.map(p => h(ProjectCard, { key: p.id, p, onPin: () => pin(p) })))),
    dialog ? h(NewProjectDialog, { onClose: () => setDialog(false), onCreate: async body => {
      const p = await c.createProject(body);
      setDialog(false); toast(`Made the project ${p.name}`, 'success'); go('#/chat/projects/' + enc(p.id));
    } }) : null);
}

function ProjectCard({ p, onPin }) {
  return h('div', { role: 'listitem', className: 'aichat-pcard', style: { position: 'relative' } },
    h('a', { href: '#/chat/projects/' + enc(p.id), style: { display: 'flex', gap: 12, alignItems: 'flex-start', padding: '14px 14px', borderRadius: 10, border: '1px solid ' + T.bd,
      background: T.card, color: T.tx, textDecoration: 'none', minHeight: 92 } },
      h('span', { style: { width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: T.tpu, color: T.pu, flex: 'none' } }, h(Icon, { d: 'folder', size: 17 })),
      h('span', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 } },
        h('span', { style: { fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 24 } }, p.name),
        p.description ? h('span', { style: { fontSize: 12.5, color: T.mut, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, p.description) : null,
        h('span', { style: { fontSize: 11.5, color: T.dim, marginTop: 'auto' } }, cardLine(p)))),
    h('button', { type: 'button', className: 'aichat-pin' + (p.pinned ? ' on' : ''), onClick: onPin, 'aria-pressed': p.pinned ? 'true' : 'false',
      'aria-label': `${p.pinned ? 'Unpin' : 'Pin'} ${p.name}`, title: p.pinned ? 'Unpin' : 'Pin to the top',
      style: { position: 'absolute', top: 10, right: 10, width: 26, height: 26, display: 'grid', placeItems: 'center', border: 0, borderRadius: 6, background: 'transparent',
        color: p.pinned ? T.acc : T.mut, cursor: 'pointer' } }, h(Icon, { d: 'pin', size: 14, fill: p.pinned ? 'currentColor' : 'none' })));
}

export function NewProjectDialog({ onClose, onCreate }) {
  const React = R(), [f, setF] = React.useState({ name: '', description: '', instructions: '' }), [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false);
  const set = k => e => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async e => {
    e?.preventDefault?.();
    const { body, error } = newProjectBody(f);
    if (error) { setErr(error); return; }
    setBusy(true); setErr(null);
    try { await onCreate(body); } catch (x) { setErr(x?.detail || x?.message || 'Not made'); setBusy(false); }
  };
  const area = { ...inputSt, height: 'auto', padding: '8px 9px', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.45 };
  return h('div', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'New project', onKeyDown: e => { if (e.key === 'Escape') onClose(); },
    style: { position: 'fixed', inset: 0, zIndex: 80, display: 'grid', placeItems: 'center', background: T.ov, padding: 16 } },
    h('form', { onSubmit: submit, style: { width: 'min(520px, 100%)', background: T.card, border: '1px solid ' + T.bds, borderRadius: 12, boxShadow: SHADOW, padding: 18, display: 'flex', flexDirection: 'column', gap: 12 } },
      h('h2', { style: { margin: 0, fontSize: 16, fontWeight: 600 } }, 'New project'),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 5 } }, h('span', { style: label11 }, 'Name'),
        h('input', { autoFocus: true, value: f.name, onChange: set('name'), maxLength: 120, 'aria-label': 'Project name', placeholder: 'e.g. Thesis', style: { ...inputSt, height: 34 } })),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 5 } }, h('span', { style: label11 }, 'Description (optional)'),
        h('textarea', { value: f.description, onChange: set('description'), rows: 2, maxLength: 2000, 'aria-label': 'Description', style: area })),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 5 } }, h('span', { style: label11 }, 'Instructions (optional)'),
        h('textarea', { value: f.instructions, onChange: set('instructions'), rows: 5, maxLength: 16000, 'aria-label': 'Instructions', placeholder: 'What every chat in this project should follow', style: area })),
      err ? h('div', { role: 'alert', style: { color: T.rd, fontSize: 12.5 } }, err) : null,
      h('div', { style: { display: 'flex', justifyContent: 'flex-end', gap: 8 } },
        h(Btn, { kind: 'ghost', sm: true, label: 'Cancel', onClick: onClose }),
        h('button', { type: 'submit', disabled: busy, style: { height: 30, padding: '0 14px', borderRadius: 7, border: 0, background: T.acc, color: ON_ACC, font: 'inherit', fontSize: 12.5, fontWeight: 600, cursor: 'pointer' } },
          busy ? 'Making…' : 'Create project'))));
}

export const PROJECTS_CSS = `
.aichat-pcard .aichat-pin{opacity:0}.aichat-pcard:hover .aichat-pin,.aichat-pcard .aichat-pin:focus-visible,.aichat-pcard .aichat-pin.on{opacity:1}
.aichat-pcard a:hover{border-color:var(--bdh,#3A4A63)!important}
@media (hover:none){.aichat-pcard .aichat-pin{opacity:1}}
`;
