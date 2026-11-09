// The Show all page (plan chat-history 3.1): `#/chat/all` in the Chat page's main area, the sidebar beside it. A title
// with the count, a search (`?q=` from the URL; the same title-and-message search as the sidebar), the sidebar's Show and
// Group by as chips (the same saved view, so changing one changes both), then every chat: grouped by date (the same
// headings, over what's loaded), by environment, or flat. A row is the sidebar's (`Item`: rename, Move to, archive,
// delete, drag into a pane) with its environment and its date added. Pages of 50 load as the end scrolls into view.
// Keys: ↑/↓ move through the rows, Enter opens one, / focuses the search. Pure helpers first (tested in
// utils/tests/web/chat-all.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, inputSt } from './chat-ui.js';
import { Item } from './chat-list.js';
import { Choice, SHOW, groupChoices, groupOf, archivedParam, mergeById, emptyText } from './chat-groups.js';
import { groupByDate, shortDate, dateHeadSt } from './chat-dates.js';

const R = () => globalThis.React;
export const ALL_PAGE = 50;          // chats per load

/** The next load: `{offset, limit}` after what's loaded, or null once the count is reached (an unknown count: until
 * a load comes back short, `done`). */
export function nextPage(loaded, total, done = false, size = ALL_PAGE) {
  if (done || (total != null && loaded >= total)) return null;
  return { offset: loaded, limit: size };
}

/** Appends a load to what's there: a chat already listed (it moved up between two loads) stays once. `done` when the
 * load came back short of a full page. */
export const addPage = (items, page, size = ALL_PAGE) => ({ items: mergeById(items, page), done: page.length < size });

/** A chat's environment: its id (`default` for none or for one the workspace mod no longer has) and name. */
export function envOf(t, envs) {
  const list = Array.isArray(envs) ? envs : [], id = (t.settings || {}).environment || 'default';
  const env = list.find(e => e.id === id) || list.find(e => e.default || e.id === 'default');
  return env ? { id: env.id, name: env.name || env.id } : { id, name: id === 'default' ? 'Default' : id };
}

/** What's loaded, under its headings: by date (the sidebar's), by environment (in the order its first chat comes), or
 * one group with no heading. */
export function groupLoaded(items, { group = 'none', order = 'updated', envs, now } = {}) {
  if (group === 'date') return groupByDate(items, { order, now });
  if (group !== 'environment') return [{ key: 'all', label: null, threads: items }];
  const by = new Map();
  for (const t of items) {
    const e = envOf(t, envs);
    if (!by.has(e.id)) by.set(e.id, { key: e.id, label: e.name, threads: [] });
    by.get(e.id).threads.push(t);
  }
  return [...by.values()];
}

/** The row to focus after ↑ or ↓ from `i` (−1: none yet), kept inside the list. */
export const stepRow = (i, key, n) => (!n ? -1 : key === 'ArrowDown' ? Math.min(n - 1, i + 1) : key === 'ArrowUp' ? Math.max(0, i < 0 ? 0 : i - 1) : i);

// ---------- the page ----------
const metaSt = { fontSize: 11, color: T.dim, flex: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' };

/** `c`: the chat client; `view`/`onView`: the sidebar's saved view; `itemProps(t)` and `actions` ({rename, archive,
 * remove}): the page's handlers; `reloadKey`: bumped when chats are made, moved, archived or deleted; `bus`: the
 * page's `patched` events (a rename shows at once). */
export function AllChats({ c, view, onView, envs, q0 = '', reloadKey, bus, actions, itemProps = () => ({}), onError, onMenu, onBack }) {
  const React = R(), { useState, useEffect, useRef } = React;
  const [text, setText] = useState(q0), [q, setQ] = useState(q0.trim());
  const [items, setItems] = useState([]), [total, setTotal] = useState(null), [done, setDone] = useState(false), [loading, setLoading] = useState(true);
  const gen = useRef(0), busy = useRef(false), st = useRef({}); st.current = { items, total, done };
  const search = useRef(null), sentinel = useRef(null), listRef = useRef(null);
  const archived = archivedParam(view.show), grouping = groupOf(view, { envs: !!envs });
  const params = { q: q || undefined, archived, sort: view.chatOrder };

  const load = async (fresh = false) => {
    const s = st.current, next = fresh ? { offset: 0, limit: Math.max(ALL_PAGE, fresh === 'keep' ? s.items.length : 0) } : nextPage(s.items.length, s.total, s.done);
    if (!next || (busy.current && !fresh)) return;
    const my = fresh ? ++gen.current : gen.current;
    busy.current = true; setLoading(true);
    try {
      const [page, count] = await Promise.all([c.threads({ ...params, ...next }),
        fresh && c.threadCount ? c.threadCount({ q: params.q, archived }).then(r => r.count, () => null) : null]);
      if (my !== gen.current) return;                       // a newer search or view started meanwhile
      const out = addPage(fresh ? [] : st.current.items, page, next.limit);
      setItems(out.items); setDone(out.done);
      if (fresh) setTotal(count);
    } catch (e) { if (my === gen.current) onError?.(e); }
    finally { if (my === gen.current) { busy.current = false; setLoading(false); } }
  };
  useEffect(() => { const t = setTimeout(() => setQ(text.trim()), text.trim() === q ? 0 : 220); return () => clearTimeout(t); }, [text]);
  useEffect(() => { setItems([]); setTotal(null); setDone(false); load(true); }, [q, view.show, view.chatOrder]);
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } load('keep'); }, [reloadKey]);   // changed elsewhere: the same rows again
  useEffect(() => { search.current?.focus(); }, []);
  useEffect(() => {                                         // a rename (or a turn's state) shows on its row at once
    if (!bus) return undefined;
    const on = e => setItems(l => l.map(t => (t.id === e.detail?.id ? { ...t, ...e.detail } : t)));
    bus.addEventListener('patched', on);
    return () => bus.removeEventListener('patched', on);
  }, [bus]);
  useEffect(() => {                                         // the end in view: the next 50
    const el = sentinel.current;
    if (!el || typeof IntersectionObserver === 'undefined') return undefined;
    const io = new IntersectionObserver(es => { if (es.some(x => x.isIntersecting)) load(); }, { root: listRef.current, rootMargin: '300px' });
    io.observe(el);
    return () => io.disconnect();
  }, [items.length, done, total, q, view.show, view.chatOrder]);

  const onKey = e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || '');
    if (e.key === '/' && !typing) { e.preventDefault(); search.current?.focus(); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const rows = [...(listRef.current?.querySelectorAll('[data-row] a[href^="#/chat/"]') || [])];
    const i = stepRow(rows.indexOf(document.activeElement), e.key, rows.length);
    if (i >= 0) { e.preventDefault(); rows[i].focus(); }
  };
  const row = t => {
    const env = envOf(t, envs);
    return h('div', { key: t.id, 'data-row': t.id },
      h(Item, { t, active: false, onRename: v => actions.rename(t, v), onArchive: () => actions.archive(t), onDelete: () => actions.remove(t), ...itemProps(t),
        aside: [envs ? h('span', { key: 'e', title: 'Environment', style: { ...metaSt, flex: '0 1 auto', minWidth: 0, maxWidth: 'min(120px, 35%)' } }, env.name) : null,
          h('span', { key: 'd', style: { ...metaSt, minWidth: 44, textAlign: 'right' } }, shortDate(t[view.chatOrder === 'created' ? 'created' : 'updated']))] }));
  };
  const groups = groupLoaded(items, { group: grouping, order: view.chatOrder, envs });
  return h('section', { 'aria-label': 'All chats', onKeyDown: onKey, style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, background: T.bg } },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 18px 10px', borderBottom: '1px solid ' + T.bd } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: onMenu }) : null,
        h('h2', { style: { margin: 0, fontSize: 15, fontWeight: 600, color: T.tx } }, 'All chats'),
        total != null ? h('span', { 'aria-label': `${total} chats`, style: { fontSize: 12.5, color: T.dim } }, total) : null,
        h('span', { style: { flex: 1 } }),
        onBack ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Back to the chats', 'aria-label': 'Back to the chats', onClick: onBack }) : null),
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 7, ...inputSt, height: 32, padding: '0 10px', borderRadius: 7, maxWidth: 520 } },
        h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: 'search', size: 13 })),
        h('input', { ref: search, value: text, onChange: e => setText(e.target.value), placeholder: 'Search titles and messages', 'aria-label': 'Search all chats',
          onKeyDown: e => { if (e.key === 'Escape' && text) { e.stopPropagation(); setText(''); } },
          style: { flex: 1, minWidth: 0, border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5 } })),
      h('div', { style: { display: 'flex', gap: 18, flexWrap: 'wrap' } },
        h(Choice, { label: 'Show', value: view.show, options: SHOW, onPick: show => onView({ ...view, show }) }),
        h(Choice, { label: 'Group by', value: grouping, options: groupChoices({ envs: !!envs }), onPick: group => onView({ ...view, group }) }))),
    h('div', { ref: listRef, style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '6px 12px 18px' } },
      h('div', { style: { maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 1 } },
        !items.length ? h('div', { role: 'status', style: { padding: '24px 10px', color: T.mut, fontSize: 12.5 } }, loading ? 'Loading…' : emptyText(view.show, q)) : null,
        groups.map(g => h('div', { key: g.key, role: 'group', 'aria-label': g.label || 'Chats', style: { display: 'flex', flexDirection: 'column', gap: 1 } },
          g.label ? h('h3', { style: { margin: 0, ...dateHeadSt } }, g.label) : null,
          g.threads.map(row))),
        h('div', { ref: sentinel, 'aria-hidden': 'true', style: { height: 1 } }),
        items.length && loading ? h('div', { role: 'status', style: { padding: '8px 10px', color: T.dim, fontSize: 11.5 } }, 'Loading more…') : null)));
}
