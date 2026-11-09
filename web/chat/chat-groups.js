// The chat list by environment (plan 41.2, after Claude Code's sidebar): one section per environment (Phase 34's
// workspaces) with its name, how many chats, New chat in it and a ⋯ menu (Rename, Manage folders), then its
// first chats in the chosen order and Show more. The View menu picks which chats (Chats, Archived, Both), the
// grouping (Environment, Date, None) and both orders (plan chat-history 2.2); they and the
// collapsed sections are saved in config.toml (`[ui.chat.list]`, settings-that-stick 3.3; `gaifa.chat.list` before). Chats load per section from the agent
// (`GET /v1/threads?environment=`, `GET /v1/threads/groups`), so a big environment never loads whole.
// Pure helpers first (tested in utils/tests/web/chat-groups.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, Popover, chipSt, inputSt, label11, getPref } from './chat-ui.js';
import { uiPrefs } from '../ui-prefs.js';

const R = () => globalThis.React;
const enc = encodeURIComponent;
export const LIST_VIEW = 'gaifa.chat.list';
export const FIRST = 5;          // chats shown in a section before Show more (chat-history 2.4)
export const PAGE = 200;         // an open section loads its chats this many at a time
export const VIEW_DEFAULTS = { show: 'chats', group: 'environment', envOrder: 'activity', chatOrder: 'updated', collapsed: [] };
// Group by: a grouping needing more than the chats' own fields says so in `needs` (Environment: the workspace mod's
// environments; Project: the agent's projects, plan projects 5.4, whose sections are chat-project-groups.js's).
export const GROUP_BY = [['environment', 'Environment'], ['project', 'Project'], ['date', 'Date'], ['none', 'None']];
export const GROUP_NEEDS = { environment: 'envs', project: 'projects' };
export const SHOW = [['chats', 'Chats'], ['archived', 'Archived'], ['both', 'Both']];
export const ENV_ORDERS = [['activity', 'Recent activity'], ['name', 'Name'], ['created', 'Created']];
export const CHAT_ORDERS = [['updated', 'Recent activity'], ['title', 'Name'], ['created', 'Created']];

/** `[ui.chat.list]` (snake case) ↔ the page's view. An old saved `archived` toggle reads as Show: Archived. */
export const viewOfUi = u => (u && typeof u === 'object' ? { show: u.show ?? (u.archived === true ? 'archived' : undefined), group: u.group,
  envOrder: u.env_order, chatOrder: u.chat_order, collapsed: u.collapsed } : {});
export const uiOfView = v => ({ show: v.show || 'chats', group: v.group, env_order: v.envOrder, chat_order: v.chatOrder, collapsed: [...(v.collapsed || [])] });
/** Show → the agent's `archived` filter: live chats (false), archived ones (true), or both ('all'). */
export const archivedParam = show => (show === 'both' ? 'all' : show === 'archived');
/** The groupings the menu offers: Environment only with the workspace mod's environments (`have.envs`), Project only
 * with the agent's projects (`have.projects`). */
export const groupChoices = (have = {}) => GROUP_BY.filter(([k]) => !GROUP_NEEDS[k] || have[GROUP_NEEDS[k]]);
/** The grouping in effect: the saved one, or None when what it needs is missing (no environments). */
export const groupOf = (view, have = {}) => (groupChoices(have).some(([k]) => k === view.group) ? view.group : 'none');
const saved0 = () => { const u = uiPrefs.get('chat.list', null); return u ? viewOfUi(u) : getPref(LIST_VIEW, {}); };

/** The saved view, with defaults for anything missing or unknown. */
export function readView(saved = saved0()) {
  const v = { ...VIEW_DEFAULTS, ...Object.fromEntries(Object.entries(saved && typeof saved === 'object' ? saved : {}).filter(([, x]) => x !== undefined)) };
  if (saved?.show === undefined && saved?.archived === true) v.show = 'archived';      // the old toggle (chat-history 2.2)
  const ok = (list, x, d) => (list.some(([k]) => k === x) ? x : d);
  return { show: ok(SHOW, v.show, 'chats'), group: ok(GROUP_BY, v.group, 'environment'), envOrder: ok(ENV_ORDERS, v.envOrder, 'activity'),
    chatOrder: ok(CHAT_ORDERS, v.chatOrder, 'updated'), collapsed: Array.isArray(v.collapsed) ? v.collapsed.map(String) : [] };
}
export const saveView = v => uiPrefs.set('chat.list', uiOfView(v));
export const toggled = (list, id) => (list.includes(id) ? list.filter(x => x !== id) : [...list, id]);

/** One section per environment: `{env, ids, count, updated, running}`. `groups` is the agent's
 * `/v1/threads/groups`; an environment id it uses that the workspace mod doesn't know (deleted) folds into
 * Default, as the header chip treats it, and `ids` lists every id the section's chats carry. */
export function groupRows(groups, envs) {
  const list = Array.isArray(envs) ? envs : [];
  const def = list.find(e => e.default || e.id === 'default');
  const by = new Map(list.map(e => [e.id, { env: e, ids: [e.id], count: 0, updated: 0, running: 0 }]));
  if (def && !by.get(def.id).ids.includes('default')) by.get(def.id).ids.push('default');
  for (const g of Array.isArray(groups) ? groups : []) {
    let row = by.get(g.environment);
    if (!row && def) { row = by.get(def.id); if (!row.ids.includes(g.environment)) row.ids.push(g.environment); }
    if (!row) continue;
    row.count += g.count || 0;
    row.updated = Math.max(row.updated, g.updated || 0);
    row.running += g.running || 0;
  }
  return [...by.values()];
}

/** Sections in the chosen order: by recent activity (an empty one by its own `updated`, after those with
 * chats), by name, or newest made first. */
export function orderGroups(rows, by = 'activity') {
  const name = r => String(r.env.name || r.env.id).toLowerCase();
  const cmp = {
    name: (a, b) => name(a).localeCompare(name(b)),
    created: (a, b) => (b.env.created || 0) - (a.env.created || 0) || name(a).localeCompare(name(b)),
    activity: (a, b) => (!!b.count - !!a.count) || ((b.updated || b.env.updated || 0) - (a.updated || a.env.updated || 0)) || name(a).localeCompare(name(b)),
  }[by] || (() => 0);
  return [...rows].sort(cmp);
}

/** A section's chats with the newest state the page knows (a turn started, a title changed). */
export const overlay = (rows, known) => {
  const by = new Map((known || []).map(t => [t.id, t]));
  return rows.map(t => (by.has(t.id) ? { ...t, ...pick(by.get(t.id)) } : t));
};
/** The sections the list shows: only environments with chats (in this view: an environment whose chats are all
 * archived shows only under Archived); the user's ask, 2026-10-21. */
export const shownRows = rows => rows.filter(r => r.count > 0);

/** A section's rows: its first 5, or all it loaded once opened with Show more; none once it's empty (its last chat
 * moved, archived or deleted: nothing stale stays). */
export const sectionChats = (row, loaded, known, open = false) => (row.count ? overlay((loaded || []).slice(0, open ? undefined : FIRST), known) : []);
/** What ends a section: 'more' (Show more · N: the rest, or the next page of an open section), 'less' (Show less, once
 * an open section has everything), or null (5 or fewer). `shown`: how many rows it draws. */
export const moreOrLess = (row, shown, open = false) => (shown < row.count ? 'more' : open && row.count > FIRST ? 'less' : null);
/** The flat list's end: `{n}` (Show all · n) when the agent counts more chats than the list shows; with no count (an
 * older agent), a full page means there may be more. */
export const showAllOf = (shown, total, page = 20) => (total == null ? (shown >= page ? { n: null } : null) : total > shown ? { n: total } : null);
/** `more` added after `list`, a chat already there (moved up between two loads) kept once, where it was first. */
export const mergeById = (list, more) => { const ids = new Set(list.map(t => t.id)); return [...list, ...more.filter(t => !ids.has(t.id))]; };
const pick = t => Object.fromEntries(['title', 'state', 'running', 'updated', 'archived'].filter(k => k in t).map(k => [k, t[k]]));

/** What an empty list says, per Show. */
export const emptyText = (show, q = '') => (q ? `No chats match “${q}”.` : show === 'archived' ? 'No archived chats.' : 'No chats yet. Start one ↑');

/** Environments from the workspace mod, or null without it (the list is then flat). */
export async function loadEnvs(api) {
  if (!api?.callService) return null;
  try { return (await api.callService('workspace', 'GET', '/v1/environments')).json?.environments || null; } catch { return null; }
}

// ---------- Show more: a full-width divider, a line each side of the words (plan 42.1) ----------
export function MoreBar({ n, onClick, label = 'Show more' }) {
  const line = h('span', { 'aria-hidden': 'true', style: { flex: 1, height: 1, background: T.bd } });
  const words = n ? `${label} · ${n}` : label;
  return h('button', { type: 'button', onClick, className: 'aichat-morebar', 'aria-label': label === 'Show more' && n ? `Show ${n} more` : words,
    style: { display: 'flex', alignItems: 'center', gap: 8, width: '100%', height: 24, margin: '2px 0 4px', padding: '0 6px', border: 0, background: 'transparent', color: T.mut, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } },
    line, h('span', { style: { flex: 'none', whiteSpace: 'nowrap' } }, words), line);
}

// ---------- the View menu ----------
export function Choice({ label, value, options, onPick }) {
  return h('div', { role: 'radiogroup', 'aria-label': label, style: { display: 'flex', flexDirection: 'column', gap: 4 } },
    h('span', { style: label11 }, label),
    h('div', { style: { display: 'flex', gap: 4, flexWrap: 'wrap' } },
      options.map(([k, l]) => h('button', { key: k, type: 'button', role: 'radio', 'aria-checked': k === value ? 'true' : 'false', onClick: () => onPick(k), style: chipSt(k === value, { sm: true }) }, l))));
}

/** `envs`: whether the workspace mod's environments are known (Group by: Environment needs them); `projects`: whether
 * the agent has projects (Group by: Project, plan projects 5.4). */
export function ViewMenu({ view, onChange, envs = true, projects = false }) {
  const React = R(), [open, setOpen] = React.useState(false);
  const set = patch => onChange({ ...view, ...patch });
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Btn, { sm: true, icon: 'sliders', title: 'View: group and order the chats', 'aria-label': 'View', 'aria-expanded': open ? 'true' : 'false', onClick: () => setOpen(!open),
      className: 'aichat-quiet', style: { width: 30, height: 30, borderRadius: 7, background: 'transparent', color: T.mut } }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'down-left', width: 280, label: 'View', style: { gap: 10 } },   // opens over the chat, not behind the app's rail
      h(Choice, { label: 'Show', value: view.show, options: SHOW, onPick: show => set({ show }) }),   // the one place to choose (chat-history 2.2)
      h(Choice, { label: 'Group by', value: groupOf(view, { envs, projects }), options: groupChoices({ envs, projects }), onPick: group => set({ group }) }),
      ['environment', 'project'].includes(groupOf(view, { envs, projects })) ? h(Choice, { label: groupOf(view, { envs, projects }) === 'project' ? 'Projects by' : 'Environments by',
        value: view.envOrder, options: ENV_ORDERS, onPick: envOrder => set({ envOrder }) }) : null,
      h(Choice, { label: 'Chats by', value: view.chatOrder, options: CHAT_ORDERS, onPick: chatOrder => set({ chatOrder }) })));
}

// ---------- a section ----------
const iconBtn = { width: 22, height: 22, display: 'grid', placeItems: 'center', border: 0, borderRadius: 5, background: 'transparent', color: T.mut, cursor: 'pointer', flex: 'none' };

export function Section({ row, open, onToggle, chats, loading, more, onMore, onLess, renderItem, onNew, onRename, onManage }) {
  const React = R(), [menu, setMenu] = React.useState(false), [edit, setEdit] = React.useState(null);
  const env = row.env, name = env.name || env.id;
  const save = () => { const v = (edit || '').trim(); setEdit(null); if (v && v !== name) onRename(v); };
  return h('section', { 'aria-label': name, className: 'aichat-sec', style: { display: 'flex', flexDirection: 'column', gap: 1, marginTop: 4 } },
    h('div', { className: 'aichat-sechead', style: { display: 'flex', alignItems: 'center', gap: 4, height: 28, padding: '0 2px 0 4px', borderRadius: 6 } },
      edit != null
        ? h('input', { autoFocus: true, value: edit, 'aria-label': 'Environment name', onChange: e => setEdit(e.target.value), onBlur: save,
            onKeyDown: e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { e.stopPropagation(); setEdit(null); } }, style: { ...inputSt, flex: 1, height: 24 } })
        : h('button', { type: 'button', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', title: (env.folders || []).map(f => f.path).join('\n') || 'No folders yet',
            style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6, height: 26, border: 0, background: 'transparent', color: T.tx, cursor: 'pointer', font: 'inherit', fontSize: 12, fontWeight: 600, padding: '0 4px', textAlign: 'left' } },
            h('span', { style: { color: T.mut, display: 'flex', flex: 'none' } }, h(Icon, { d: open ? 'chevD' : 'chevR', size: 12 })),
            h(Icon, { d: 'home', size: 12 }),
            h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, name),
            row.running ? h('span', { 'aria-label': `${row.running} running`, style: { width: 6, height: 6, borderRadius: 99, background: T.acc, flex: 'none' } }) : null,
            h('span', { style: { fontSize: 11, color: T.dim, fontWeight: 400, flex: 'none' } }, row.count)),
      h('button', { type: 'button', className: 'aichat-more', 'aria-label': `New chat in ${name}`, title: `New chat in ${name}`, onClick: onNew, style: iconBtn }, h(Icon, { d: 'plus', size: 13 })),
      env.none ? null : h('span', { style: { position: 'relative', flex: 'none' } },   // None: nothing to rename or fill
        h('button', { type: 'button', className: 'aichat-more', 'aria-label': `More for ${name}`, 'aria-haspopup': 'menu', 'aria-expanded': menu ? 'true' : 'false', onClick: () => setMenu(!menu), style: iconBtn }, h(Icon, { d: 'more', size: 13 })),
        h(Popover, { open: menu, onClose: () => setMenu(false), width: 180, label: 'Environment actions', style: { padding: 4, gap: 0 } },
          [['edit', 'Rename', () => setEdit(name)], ['folder', 'Manage folders…', onManage]].map(([ic, label, fn]) =>
            h('button', { key: label, type: 'button', role: 'menuitem', onClick: () => { setMenu(false); fn(); },
              style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
            h(Icon, { d: ic, size: 13 }), label))))),
    open ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 1, paddingLeft: 10 } },
      !row.count ? h('div', { style: { padding: '4px 10px 6px', color: T.dim, fontSize: 11.5 } }, 'No chats yet') : null,
      row.count && !chats.length && loading ? h('div', { role: 'status', style: { padding: '4px 10px', color: T.dim, fontSize: 11.5 } }, 'Loading…') : null,
      chats.map(t => renderItem(t)),
      more === 'less' ? h(MoreBar, { label: 'Show less', onClick: onLess })
        : more ? h(MoreBar, { n: row.count - chats.length, onClick: onMore }) : null) : null);
}

/** The sections and their chats. `known`: the page's flat list, whose live state (a turn running, a new title)
 * shows on the rows; `reloadKey`: bumped by the page when chats are made, moved, archived or deleted. */
export function GroupedChats({ c, api, envs, view, onView, known, reloadKey, renderItem, onNewIn, onEnvsChanged, onError, go }) {
  // `opened`: the sections whose Show more was used (page state, not saved): they hold all their chats, loaded 200 at a time
  const React = R(), [groups, setGroups] = React.useState(null), [chats, setChats] = React.useState({}), [opened, setOpened] = React.useState({});
  const rows = orderGroups(groupRows(groups, envs), view.envOrder), archived = archivedParam(view.show);
  const want = (row, limit, offset = 0) => c.threads({ environment: row.ids.join(','), sort: view.chatOrder, limit, offset, archived })
    .then(list => setChats(m => ({ ...m, [row.env.id]: offset ? mergeById(m[row.env.id] || [], list) : list })), onError);
  const key = rows.map(r => `${r.env.id}:${r.count}:${r.ids.length}`).join('|');
  React.useEffect(() => { c.threadGroups?.({ archived }).then(setGroups, e => { setGroups([]); onError?.(e); }); }, [archived, reloadKey]);
  React.useEffect(() => {
    if (!groups) return;
    rows.filter(r => r.count && !view.collapsed.includes(r.env.id)).forEach(r => want(r, opened[r.env.id] ? PAGE : FIRST));
  }, [key, view.chatOrder, view.collapsed.join(','), groups]);
  if (!groups) return h('div', { role: 'status', style: { padding: '18px 10px', color: T.mut, fontSize: 12, textAlign: 'center' } }, 'Loading…');
  const rename = async (row, name) => {
    try { await api.callService('workspace', 'PUT', `/v1/environments/${enc(row.env.id)}`, { json: { name } }); onEnvsChanged?.(); }
    catch (e) { onError?.(e); }
  };
  const anything = rows.some(r => r.count);
  return h('div', { style: { display: 'flex', flexDirection: 'column' } },
    !anything ? h('div', { style: { padding: '12px 10px 4px', color: T.mut, fontSize: 12, textAlign: 'center' } }, emptyText(view.show)) : null,
    shownRows(rows).map(r => {
      const id = r.env.id, open = !view.collapsed.includes(id), all = !!opened[id], list = sectionChats(r, chats[id], known, all);
      return h(Section, { key: id, row: r, open, chats: list, loading: !chats[id], more: moreOrLess(r, list.length, all),
        onToggle: () => onView({ ...view, collapsed: toggled(view.collapsed, id) }),
        onMore: () => { if (all) want(r, PAGE, (chats[id] || []).length); else { setOpened(s => ({ ...s, [id]: true })); want(r, PAGE); } },
        onLess: () => setOpened(s => ({ ...s, [id]: false })),
        renderItem, onNew: () => onNewIn(id), onRename: name => rename(r, name), onManage: () => go('#/s/workspace/environments') });
    }));
}
