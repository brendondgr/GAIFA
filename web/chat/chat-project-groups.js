// The chat list by project (plan projects 5.4): the View menu's Group by: Project. One section per project with chats in
// this view (its name, how many chats, New chat in the project and a ⋯ menu with Open project), then its first 5 chats
// and Show more (all of them, 200 at a time), as chat-groups.js does for environments; then **No project**. Sections come
// from the agent's `GET /v1/threads/groups?by=project` and their chats from `GET /v1/threads?project=`. Pure helpers
// first (tested in utils/tests/web/chat-groups.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Popover } from './chat-ui.js';
import { FIRST, PAGE, MoreBar, archivedParam, emptyText, mergeById, moreOrLess, sectionChats, toggled } from './chat-groups.js';

const R = () => globalThis.React;
export const NO_PROJECT = 'none';

/** One section per project with chats here, then No project: `{key, project, ids, count, updated, running}`. `groups`
 * is the agent's `/v1/threads/groups?by=project`; a project id it uses that the list doesn't know (deleted meanwhile)
 * is left out. Projects in `by` order (activity: newest chat first; name; created), pinned ones first. */
export function projectRows(groups, projects, by = 'activity') {
  const list = Array.isArray(projects) ? projects : [], g = new Map((Array.isArray(groups) ? groups : []).map(x => [x.project, x]));
  const name = r => String(r.project.name || r.project.id).toLowerCase();
  const rows = list.filter(p => g.get(p.id)?.count).map(p => ({ key: p.id, project: p, ids: [p.id], count: g.get(p.id).count,
    updated: g.get(p.id).updated || 0, running: g.get(p.id).running || 0 }));
  const cmp = { name: (a, b) => name(a).localeCompare(name(b)), created: (a, b) => (b.project.created || 0) - (a.project.created || 0) }[by]
    || ((a, b) => b.updated - a.updated || name(a).localeCompare(name(b)));
  rows.sort((a, b) => (!!b.project.pinned - !!a.project.pinned) || cmp(a, b));
  const none = g.get(NO_PROJECT);
  if (none?.count) rows.push({ key: NO_PROJECT, project: null, ids: [NO_PROJECT], count: none.count, updated: none.updated || 0, running: none.running || 0 });
  return rows;
}

const iconBtn = { width: 22, height: 22, display: 'grid', placeItems: 'center', border: 0, borderRadius: 5, background: 'transparent', color: T.mut, cursor: 'pointer', flex: 'none' };

function ProjectSection({ row, open, onToggle, chats, loading, more, onMore, onLess, renderItem, onNew, go }) {
  const React = R(), [menu, setMenu] = React.useState(false);
  const p = row.project, name = p ? p.name : 'No project';
  return h('section', { 'aria-label': name, className: 'aichat-sec', style: { display: 'flex', flexDirection: 'column', gap: 1, marginTop: 4 } },
    h('div', { className: 'aichat-sechead', style: { display: 'flex', alignItems: 'center', gap: 4, height: 28, padding: '0 2px 0 4px', borderRadius: 6 } },
      h('button', { type: 'button', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', title: p?.description || (p ? name : 'Chats in no project'),
        style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6, height: 26, border: 0, background: 'transparent', color: p ? T.tx : T.mut, cursor: 'pointer', font: 'inherit', fontSize: 12, fontWeight: 600, padding: '0 4px', textAlign: 'left' } },
        h('span', { style: { color: T.mut, display: 'flex', flex: 'none' } }, h(Icon, { d: open ? 'chevD' : 'chevR', size: 12 })),
        h(Icon, { d: p ? 'folder' : 'chat', size: 12 }),
        h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, name),
        row.running ? h('span', { 'aria-label': `${row.running} running`, style: { width: 6, height: 6, borderRadius: 99, background: T.acc, flex: 'none' } }) : null,
        h('span', { style: { fontSize: 11, color: T.dim, fontWeight: 400, flex: 'none' } }, row.count)),
      h('button', { type: 'button', className: 'aichat-more', 'aria-label': `New chat in ${name}`, title: `New chat in ${name}`, onClick: onNew, style: iconBtn }, h(Icon, { d: 'plus', size: 13 })),
      p ? h('span', { style: { position: 'relative', flex: 'none' } },
        h('button', { type: 'button', className: 'aichat-more', 'aria-label': `More for ${name}`, 'aria-haspopup': 'menu', 'aria-expanded': menu ? 'true' : 'false', onClick: () => setMenu(!menu), style: iconBtn }, h(Icon, { d: 'more', size: 13 })),
        h(Popover, { open: menu, onClose: () => setMenu(false), width: 170, label: 'Project actions', style: { padding: 4, gap: 0 } },
          h('button', { type: 'button', role: 'menuitem', onClick: () => { setMenu(false); go('#/chat/projects/' + encodeURIComponent(p.id)); },
            style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } },
            h(Icon, { d: 'folder', size: 13 }), 'Open project'))) : null),
    open ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 1, paddingLeft: 10 } },
      row.count && !chats.length && loading ? h('div', { role: 'status', style: { padding: '4px 10px', color: T.dim, fontSize: 11.5 } }, 'Loading…') : null,
      chats.map(t => renderItem(t)),
      more === 'less' ? h(MoreBar, { label: 'Show less', onClick: onLess })
        : more ? h(MoreBar, { n: row.count - chats.length, onClick: onMore }) : null) : null);
}

/** The sections and their chats (as GroupedChats, chat-groups.js). `projects`: the page's list (`c.projects()`);
 * `onNewIn(project | null)`: New chat in a project, or in none. */
export function ProjectChats({ c, projects, view, onView, known, reloadKey, renderItem, onNewIn, onError, go }) {
  const React = R(), [groups, setGroups] = React.useState(null), [chats, setChats] = React.useState({}), [opened, setOpened] = React.useState({});
  const rows = projectRows(groups, projects, view.envOrder), archived = archivedParam(view.show);
  const want = (row, limit, offset = 0) => c.threads({ project: row.ids.join(','), sort: view.chatOrder, limit, offset, archived })
    .then(list => setChats(m => ({ ...m, [row.key]: offset ? mergeById(m[row.key] || [], list) : list })), onError);
  const key = rows.map(r => `${r.key}:${r.count}`).join('|');
  React.useEffect(() => { c.threadGroups?.({ archived, by: 'project' }).then(setGroups, e => { setGroups([]); onError?.(e); }); }, [archived, reloadKey]);
  React.useEffect(() => {
    if (!groups) return;
    rows.filter(r => !view.collapsed.includes('p:' + r.key)).forEach(r => want(r, opened[r.key] ? PAGE : FIRST));
  }, [key, view.chatOrder, view.collapsed.join(','), groups]);
  if (!groups) return h('div', { role: 'status', style: { padding: '18px 10px', color: T.mut, fontSize: 12, textAlign: 'center' } }, 'Loading…');
  if (!rows.length) return h('div', { style: { padding: '12px 10px 4px', color: T.mut, fontSize: 12, textAlign: 'center' } }, emptyText(view.show));
  return h('div', { style: { display: 'flex', flexDirection: 'column' } },
    rows.map(r => {
      const id = r.key, ck = 'p:' + id, open = !view.collapsed.includes(ck), all = !!opened[id], list = sectionChats(r, chats[id], known, all);
      return h(ProjectSection, { key: id, row: r, open, chats: list, loading: !chats[id], more: moreOrLess(r, list.length, all), go,
        onToggle: () => onView({ ...view, collapsed: toggled(view.collapsed, ck) }),
        onMore: () => { if (all) want(r, PAGE, (chats[id] || []).length); else { setOpened(s => ({ ...s, [id]: true })); want(r, PAGE); } },
        onLess: () => setOpened(s => ({ ...s, [id]: false })),
        renderItem, onNew: () => onNewIn(r.project) });
    }));
}
