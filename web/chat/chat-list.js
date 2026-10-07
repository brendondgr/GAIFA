// The Chat page's thread list (plan 14.1): search, new chat, rename, archive, delete (with a
// confirm), and the archived toggle. A drawer on narrow screens (chat.js decides).

import { h, T, MONO, Icon, Btn, Popover, chipSt, inputSt, fmtAgo, label11 } from './chat-ui.js';

const R = () => globalThis.React;

function Item({ t, active, onOpen, onRename, onArchive, onDelete }) {
  const React = R(), [menu, setMenu] = React.useState(false), [edit, setEdit] = React.useState(null);
  const dot = t.running || t.state === 'running' ? T.acc : t.state === 'waiting' ? T.pu : t.state === 'error' ? T.rd : null;
  if (edit != null) {
    const save = () => { const v = edit.trim(); setEdit(null); if (v && v !== t.title) onRename(v); };
    return h('div', { style: { padding: '3px 6px' } }, h('input', { autoFocus: true, value: edit, 'aria-label': 'Chat title', onChange: e => setEdit(e.target.value), onBlur: save,
      onKeyDown: e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { e.stopPropagation(); setEdit(null); } }, style: { ...inputSt, width: '100%', height: 28 } }));
  }
  return h('div', { className: 'aichat-item', style: { position: 'relative', display: 'flex', alignItems: 'center', borderRadius: 6, background: active ? T.hov : 'transparent' } },
    h('a', { href: '#/chat/' + encodeURIComponent(t.id), onClick: onOpen, 'aria-current': active ? 'page' : undefined,
      style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8, height: 32, padding: '0 4px 0 10px', color: active ? T.tx : T.mut, fontWeight: active ? 500 : 400, textDecoration: 'none' } },
      dot ? h('span', { 'aria-label': t.state, style: { width: 6, height: 6, borderRadius: 99, background: dot, flex: 'none', animation: dot === T.acc ? 'aichatpulse 1.2s ease-in-out infinite' : 'none' } }) : null,
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t.title || 'New chat'),
      h('span', { className: 'aichat-ago', style: { fontFamily: MONO, fontSize: 10.5, color: T.dim, flex: 'none' } }, fmtAgo(t.updated))),
    h('span', { style: { position: 'relative', flex: 'none' } },
      h('button', { type: 'button', className: 'aichat-more', 'aria-label': `More for ${t.title || 'chat'}`, 'aria-haspopup': 'menu', 'aria-expanded': menu ? 'true' : 'false', onClick: () => setMenu(!menu),
        style: { width: 24, height: 24, marginRight: 4, display: 'grid', placeItems: 'center', border: 0, borderRadius: 5, background: 'transparent', color: T.mut, cursor: 'pointer' } }, h(Icon, { d: 'more', size: 14 })),
      h(Popover, { open: menu, onClose: () => setMenu(false), width: 170, label: 'Chat actions', style: { padding: 4, gap: 0 } },
        [['edit', 'Rename', () => setEdit(t.title || '')], ['archive', t.archived ? 'Unarchive' : 'Archive', onArchive], ['trash', 'Delete…', onDelete]].map(([ic, label, fn]) =>
          h('button', { key: label, type: 'button', role: 'menuitem', onClick: () => { setMenu(false); fn(); },
            style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color: ic === 'trash' ? T.rd : T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
          h(Icon, { d: ic, size: 13 }), label)))));
}

export const LIST_CSS = `
.aichat-item .aichat-more{opacity:0}.aichat-item:hover .aichat-more,.aichat-item:focus-within .aichat-more,.aichat-item .aichat-more[aria-expanded="true"]{opacity:1}
.aichat-item:hover{background:var(--hov,#161C28)}
@media (hover:none){.aichat-item .aichat-more{opacity:1}}
`;

export function ThreadList({ threads, loading, activeId, q, onQ, archived, onArchived, onMore, onNew, onOpen, onRename, onArchive, onDelete, onClose, onSessions }) {
  return h('aside', { 'aria-label': 'Chats', style: { width: '100%', height: '100%', display: 'flex', flexDirection: 'column', background: T.sb, minHeight: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 10px 8px 12px' } },
      h('span', { style: { ...label11, flex: 1 } }, archived ? 'Archived chats' : 'Chats'),
      h(Btn, { kind: 'pri', sm: true, icon: 'plus', label: 'New chat', onClick: onNew }),
      onClose ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close', onClick: onClose }) : null),
    h('div', { style: { padding: '0 10px 8px' } },
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 6, ...inputSt, height: 30, padding: '0 8px' } },
        h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: 'search', size: 13 })),
        h('input', { value: q, onChange: e => onQ(e.target.value), placeholder: 'Search chats', 'aria-label': 'Search chats',
          style: { flex: 1, minWidth: 0, border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5 } }),
        q ? h('button', { type: 'button', 'aria-label': 'Clear search', onClick: () => onQ(''), style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 0, display: 'flex' } }, h(Icon, { d: 'x', size: 12 })) : null)),
    h('nav', { style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 6px 8px', display: 'flex', flexDirection: 'column', gap: 1 } },
      !threads.length ? h('div', { style: { padding: '18px 10px', color: T.mut, fontSize: 12, textAlign: 'center' } },
        loading ? 'Loading…' : q ? `No chats match “${q}”.` : archived ? 'No archived chats.' : 'No chats yet. Start one →') : null,
      threads.map(t => h(Item, { key: t.id, t, active: t.id === activeId, onOpen: () => onOpen?.(t),
        onRename: v => onRename(t, v), onArchive: () => onArchive(t), onDelete: () => onDelete(t) })),
      onMore ? h('button', { type: 'button', onClick: onMore, style: { ...chipSt(false, { sm: true }), alignSelf: 'center', margin: '8px 0 4px' } }, 'Show more') : null),
    h('div', { style: { padding: '8px 10px', borderTop: '1px solid ' + T.bd, display: 'flex', alignItems: 'center', gap: 6 } },
      h('button', { type: 'button', 'aria-pressed': archived ? 'true' : 'false', onClick: () => onArchived(!archived), style: chipSt(archived, { sm: true }) }, h(Icon, { d: 'archive', size: 12 }), archived ? 'Showing archived' : 'Archived'),
      onSessions ? h('button', { type: 'button', onClick: onSessions, title: 'Save or switch setups (what runs and what is loaded)', style: { ...chipSt(false, { sm: true }), marginLeft: 'auto' } }, h(Icon, { d: 'bookmark', size: 12 }), 'Sessions') : null));
}
