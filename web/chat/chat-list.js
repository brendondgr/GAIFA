// The Chat page's thread list (plan 14.1, compact after Claude Code's in plan 42.1): the search across the top,
// then "+ New" with the View button on its right, then the chats: rename (the ⋯ menu, or double-click a
// title), archive, delete (with a confirm), Move to another environment. A row shows only the chat's name and its
// state dot; ⋯ shows on hover or focus (always on a touch screen), and an archived chat (Show: Both) is dimmed
// with an archive mark (plan chat-history 2.1). Which chats show is the View menu's (2.2). Sessions at the bottom. A drawer on narrow screens (chat.js
// decides). Grouped by environment (plan 41.2), the list's body is chat-groups.js's sections; by date, chat-dates.js's. Chats by meaning
// are in the header's Search (palette-meaning.js).

import { h, T, MONO, Icon, Btn, Popover, chipSt, inputSt, label11 } from './chat-ui.js';
import { ViewMenu, MoreBar, emptyText } from './chat-groups.js';
import { moveGroups } from './chat-env.js';

const R = () => globalThis.React;

/** What a chat's row shows (plan chat-history 2.1): its name, a dot while it runs, waits on a card or failed, and
 * whether it's archived (dimmed, with an archive mark; its menu then says Unarchive). No time, no environment. */
export function rowLook(t) {
  const state = t.running || t.state === 'running' ? 'running' : ['waiting', 'error'].includes(t.state) ? t.state : null;
  return { title: t.title || 'New chat', state, dot: { running: T.acc, waiting: T.pu, error: T.rd }[state] || null, archived: !!t.archived,
    archiveLabel: t.archived ? 'Unarchive' : 'Archive' };
}

/** One chat. `moveTo`: the other environments it can move to (plan 41.2); `aside`: what goes after the name (the Show
 * all page's environment and date, chat-history 3.1; nothing in the sidebar). */
export function Item({ t, active, onOpen, onRename, onArchive, onDelete, moveTo = [], onMove, aside = null, projects = [], onProject }) {
  const React = R(), [menu, setMenu] = React.useState(false), [edit, setEdit] = React.useState(null), [moving, setMoving] = React.useState(false);
  const groups = moveGroups(t, onProject ? projects : [], onMove ? moveTo : []);        // plan projects 5.3: projects, then environments
  const act = { r: () => { setMenu(false); setEdit(t.title || ''); }, m: groups.some(g => g.rows.length) ? () => setMoving(true) : null,
    a: () => { setMenu(false); onArchive(); }, d: () => { setMenu(false); onDelete(); } };
  React.useEffect(() => {        // while the menu is open: R renames, M moves, A archives, D deletes (the user's ask)
    if (!menu || moving) return undefined;
    const k = e => { const f = menuKey(e) && act[menuKey(e)]; if (f) { e.preventDefault(); e.stopPropagation(); f(); } };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, [menu, moving]);
  const look = rowLook(t), dot = look.dot;
  if (edit != null) {
    const save = () => { const v = edit.trim(); setEdit(null); if (v && v !== t.title) onRename(v); };
    return h('div', { style: { padding: '3px 6px' } }, h('input', { autoFocus: true, value: edit, 'aria-label': 'Chat title', onChange: e => setEdit(e.target.value), onBlur: save,
      onKeyDown: e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { e.stopPropagation(); setEdit(null); } }, style: { ...inputSt, width: '100%', height: 28 } }));
  }
  return h('div', { className: 'aichat-item' + (menu ? ' open' : '') + (look.archived ? ' archived' : ''), style: { position: 'relative', display: 'flex', alignItems: 'center', borderRadius: 6, background: active ? T.hov : 'transparent' } },
    h('a', { href: '#/chat/' + encodeURIComponent(t.id), onClick: onOpen, draggable: true,   // chat-split plan 2.3: drag it beside an open chat
      onDragStart: e => { e.dataTransfer.setData('application/x-gaifa-chat', t.id); e.dataTransfer.effectAllowed = 'copyMove'; }, onDoubleClick: e => { e.preventDefault(); setEdit(t.title || ''); }, 'aria-current': active ? 'page' : undefined,
      title: look.archived ? 'Archived' : undefined,
      style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 4px 0 10px', color: active ? T.tx : T.mut, fontWeight: active ? 500 : 400, textDecoration: 'none', opacity: look.archived ? 0.6 : 1 } },
      dot ? h('span', { 'aria-label': look.state, style: { width: 6, height: 6, borderRadius: 99, background: dot, flex: 'none', animation: look.state === 'running' ? 'aichatpulse 1.2s ease-in-out infinite' : 'none' } }) : null,
      look.archived ? h('span', { 'aria-label': 'Archived', style: { display: 'flex', flex: 'none', color: T.dim } }, h(Icon, { d: 'archive', size: 12 })) : null,
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, look.title), aside),
    // a slot at the right edge, empty until hover or focus, or while the menu is open; always on touch screens (LIST_CSS)
    h('span', { className: 'aichat-slot', style: { position: 'relative', flex: 'none', width: 24, height: 24, marginRight: 4, display: 'flex', alignItems: 'center', justifyContent: 'flex-end' } },
      h('button', { type: 'button', className: 'aichat-more', 'aria-label': `More for ${t.title || 'chat'}`, 'aria-haspopup': 'menu', 'aria-expanded': menu ? 'true' : 'false', onClick: () => setMenu(!menu),
        style: { width: 24, height: 24, placeItems: 'center', border: 0, borderRadius: 5, background: 'transparent', color: T.mut, cursor: 'pointer' } }, h(Icon, { d: 'more', size: 14 })),
      h(Popover, { open: menu, onClose: () => { setMenu(false); setMoving(false); }, width: moving ? 250 : 190, label: 'Chat actions', style: { padding: 4, gap: 0 } },
        moving
          ? groups.flatMap(g => [h('span', { key: 'h' + g.key, style: { ...label11, padding: '6px 9px 2px' } }, g.label),
            h('span', { key: 'n' + g.key, style: { fontSize: 11, color: T.dim, padding: '0 9px 4px', lineHeight: 1.35 } }, g.hint),
            ...g.rows.map(r => menuItem(`${r.kind}:${r.id}`, r.kind === 'project' ? 'folder' : 'home', r.label, () => {
              setMenu(false); setMoving(false); if (r.kind === 'project') onProject(r.id); else onMove(r.id); }))])
          : [menuItem('rename', 'edit', 'Rename', act.r, T.tx, 'R'),
            act.m ? menuItem('move', 'folder', 'Move to…', act.m, T.tx, 'M') : null,
            menuItem('archive', 'archive', look.archiveLabel, act.a, T.tx, 'A'),
            menuItem('delete', 'trash', 'Delete…', act.d, T.rd, 'D')])));
}

/** A menu letter from a key press: r, m, a or d alone (no modifier; not while typing in a box). */
export const menuKey = e => {
  if (!e || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || '') || e.target?.isContentEditable) return null;
  const k = String(e.key || '').toLowerCase();
  return ['r', 'm', 'a', 'd'].includes(k) ? k : null;
};

const menuItem = (key, ic, label, fn, color = T.tx, letter = null) => h('button', { key, type: 'button', role: 'menuitem', onClick: fn, 'aria-keyshortcuts': letter || undefined,
  style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
  h(Icon, { d: ic, size: 13 }), h('span', { style: { flex: 1 } }, label),
  letter ? h('kbd', { style: { fontFamily: MONO, fontSize: 10.5, color: T.dim, border: '1px solid ' + T.bd, borderRadius: 4, padding: '0 4px', lineHeight: '16px' } }, letter) : null);

export const LIST_CSS = `
.aichat-item .aichat-more{display:none}
.aichat-item:hover .aichat-more,.aichat-item:focus-within .aichat-more,.aichat-item.open .aichat-more{display:grid}
.aichat-item:hover,.aichat-item.open{background:var(--hov,#161C28)}
.aichat-sechead .aichat-more{opacity:0}.aichat-sechead:hover .aichat-more,.aichat-sechead:focus-within .aichat-more,.aichat-sechead .aichat-more[aria-expanded="true"]{opacity:1}
.aichat-morebar:hover{color:var(--tx,#E6EAF2)!important}
.aichat-newbar:hover{background:var(--hov,#161C28)!important}
.aichat-quiet{border-color:transparent!important}.aichat-quiet:hover,.aichat-quiet:focus-visible,.aichat-quiet[aria-expanded="true"]{border-color:var(--bds,#2A3547)!important;color:var(--tx,#E6EAF2)!important}
@media (hover:none){.aichat-item .aichat-more{display:grid}.aichat-sechead .aichat-more{opacity:1}}
`;

/** `showAll`: `{n}` when more chats exist than the list shows (n: how many in all, or null), else null; `onShowAll`
 * opens the Show all page (plan chat-history 2.4). */
export function ThreadList({ threads, loading, activeId, q, onQ, showAll = null, onShowAll, onNew, onOpen, onRename, onArchive, onDelete, onClose, onSessions,
  grouped = null, groupLabel = 'Chats by environment', view = null, onView = null, canGroup = false, canProjects = false, projectsRow = null, itemProps = () => ({}) }) {   // projectsRow: plan projects 5.4
  return h('aside', { 'aria-label': 'Chats', style: { width: '100%', height: '100%', display: 'flex', flexDirection: 'column', background: T.sb, minHeight: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '10px 10px 4px' } },
      h('label', { style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 7, ...inputSt, height: 30, padding: '0 9px', borderRadius: 7 } },
        h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: 'search', size: 13 })),
        h('input', { value: q, onChange: e => onQ(e.target.value), placeholder: view?.show === 'archived' ? 'Search archived' : 'Search', 'aria-label': 'Search chats',
          style: { flex: 1, minWidth: 0, border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5 } }),
        q ? h('button', { type: 'button', 'aria-label': 'Clear search', onClick: () => onQ(''), style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 0, display: 'flex' } }, h(Icon, { d: 'x', size: 12 })) : null),
      onClose ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close', onClick: onClose }) : null),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '2px 10px 8px 8px' } },
      h('button', { type: 'button', onClick: onNew, className: 'aichat-newbar', 'aria-label': 'New chat',
        style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 9, height: 30, padding: '0 6px', borderRadius: 7, border: 0, background: 'transparent', color: T.tx, font: 'inherit', fontSize: 13, cursor: 'pointer', textAlign: 'left' } },
        h('span', { style: { width: 20, height: 20, borderRadius: 99, display: 'grid', placeItems: 'center', background: T.row, color: T.tx, flex: 'none' } }, h(Icon, { d: 'plus', size: 12 })),
        'New'),
      view && onView ? h(ViewMenu, { view, onChange: onView, envs: canGroup, projects: canProjects }) : null),
    projectsRow,
    grouped && !q.trim() ? h('nav', { 'aria-label': groupLabel, style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 6px 8px' } }, grouped,
      showAll ? h(MoreBar, { n: showAll.n, label: 'Show all', onClick: onShowAll }) : null) :
    h('nav', { style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 6px 8px', display: 'flex', flexDirection: 'column', gap: 1 } },
      !threads.length ? h('div', { style: { padding: '18px 10px', color: T.mut, fontSize: 12, textAlign: 'center' } },
        loading ? 'Loading…' : emptyText(view?.show, q)) : null,
      threads.map(t => h(Item, { key: t.id, t, active: t.id === activeId, onOpen: () => onOpen?.(t),
        onRename: v => onRename(t, v), onArchive: () => onArchive(t), onDelete: () => onDelete(t), ...itemProps(t) })),
      showAll ? h(MoreBar, { n: showAll.n, label: 'Show all', onClick: onShowAll }) : null),
    h('div', { style: { padding: '8px 10px', borderTop: '1px solid ' + T.bd, display: 'flex', alignItems: 'center', gap: 6 } },
      onSessions ? h('button', { type: 'button', onClick: onSessions, title: 'Save or switch setups (what runs and what is loaded)', style: { ...chipSt(false, { sm: true }), marginLeft: 'auto' } }, h(Icon, { d: 'bookmark', size: 12 }), 'Sessions') : null));
}
