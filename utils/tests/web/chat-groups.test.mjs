// Plan 41.2: the chat list by environment: the saved view, sections from the agent's groups (a deleted
// environment folds into Default), their orders, the live overlay, a section's rows and Show more, Move to on a
// chat, the flat list while searching, and the client's and the mock's filters.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const g = await load('chat/chat-groups.js');
const list = await load('chat/chat-list.js');

function expand(n) {
  if (n == null || n === false || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(expand);
  if (typeof n.type === 'function') return expand(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
}
const all = (n, pred, out = []) => {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
};
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));

const ENVS = [{ id: 'default', name: 'Default', default: true, created: 1, updated: 1, folders: [] },
  { id: 'grants', name: 'Grants', created: 3, updated: 3, folders: [{ id: 'a', path: '/home/u/a', level: 'edit' }] },
  { id: 'art', name: 'art', created: 2, updated: 50, folders: [] }];
const GROUPS = [{ environment: 'grants', count: 9, updated: 40, running: 1 }, { environment: 'default', count: 2, updated: 30, running: 0 },
  { environment: 'gone', count: 1, updated: 45, running: 0 }];

test('the saved view, with defaults for anything unknown', () => {
  assert.deepEqual(g.readView({}), g.VIEW_DEFAULTS);
  assert.deepEqual(g.readView({ group: 'none', envOrder: 'name', chatOrder: 'title', collapsed: ['art'] }),
    { group: 'none', envOrder: 'name', chatOrder: 'title', collapsed: ['art'] });
  assert.deepEqual(g.readView({ group: 'tag', chatOrder: 'size', collapsed: 'x' }), g.VIEW_DEFAULTS);
  assert.deepEqual(g.readView(null), g.VIEW_DEFAULTS);
  assert.deepEqual(g.toggled(['a'], 'b'), ['a', 'b']);
  assert.deepEqual(g.toggled(['a', 'b'], 'a'), ['b']);
});

test('sections: one per environment, a deleted one folds into Default', () => {
  const rows = g.groupRows(GROUPS, ENVS);
  const by = Object.fromEntries(rows.map(r => [r.env.id, r]));
  assert.deepEqual(by.default.ids, ['default', 'gone']);
  assert.equal(by.default.count, 3);
  assert.equal(by.default.updated, 45);
  assert.equal(by.grants.running, 1);
  assert.equal(by.art.count, 0);                                   // an empty environment still has its section
  assert.deepEqual(g.groupRows(null, ENVS).map(r => r.count), [0, 0, 0]);
  assert.deepEqual(g.shownRows(rows).map(r => r.env.id), ['default', 'grants']);    // an environment with no chats here isn't shown
});

test('sections in order: activity (empty ones last), name, created', () => {
  const rows = g.groupRows(GROUPS, ENVS);
  assert.deepEqual(g.orderGroups(rows, 'activity').map(r => r.env.id), ['default', 'grants', 'art']);
  assert.deepEqual(g.orderGroups(rows, 'name').map(r => r.env.id), ['art', 'default', 'grants']);
  assert.deepEqual(g.orderGroups(rows, 'created').map(r => r.env.id), ['grants', 'art', 'default']);
});

test('a row shows the newest state the page knows', () => {
  const rows = [{ id: 't1', title: 'old', state: 'idle', settings: { environment: 'grants' } }, { id: 't2', title: 'x' }];
  const out = g.overlay(rows, [{ id: 't1', title: 'new', state: 'running', settings: { environment: 'art' } }]);
  assert.deepEqual(out[0], { id: 't1', title: 'new', state: 'running', settings: { environment: 'grants' } });
  assert.equal(out[1].title, 'x');
  assert.deepEqual(g.sectionChats({ count: 0 }, rows, []), []);            // emptied by a move: the old rows go
  assert.equal(g.sectionChats({ count: 2 }, rows, []).length, 2);
});

test('a section: its name and count, its chats, Show more with how many are left', () => {
  const row = g.groupRows(GROUPS, ENVS).find(r => r.env.id === 'grants');
  const chats = [{ id: 't1', title: 'One' }, { id: 't2', title: 'Two' }];
  const el = expand(g.Section({ row, open: true, chats, loading: false, more: true, onMore() {}, renderItem: t => ({ type: 'li', props: { children: [t.title] } }),
    onToggle() {}, onNew() {}, onRename() {}, onManage() {} }));
  assert.match(text(el), /Grants/);
  assert.match(text(el), /One.*Two/);
  assert.match(text(el), /Show more · 7/);
  assert.ok(all(el, n => n.props?.['aria-label'] === 'New chat in Grants').length === 1);
  const closed = expand(g.Section({ row, open: false, chats, loading: false, more: true, onMore() {}, renderItem: t => ({ type: 'li', props: { children: [t.title] } }),
    onToggle() {}, onNew() {}, onRename() {}, onManage() {} }));
  assert.doesNotMatch(text(closed), /One|Show more/);
  const empty = expand(g.Section({ row: { ...row, count: 0 }, open: true, chats: [], loading: false, more: false, renderItem: () => null,
    onToggle() {}, onNew() {}, onRename() {}, onManage() {} }));
  assert.match(text(empty), /No chats yet/);
});

test('the View menu offers grouping only with environments', () => {
  const v = g.readView({});
  const choices = el => all(expand(el), n => n.props?.role === 'radiogroup').map(n => n.props['aria-label']);
  // the popover renders its children only when open; the stub's useState keeps it closed, so read the props
  const menu = g.ViewMenu({ view: v, onChange() {}, grouped: true });
  const pop = all(menu, n => n.props && 'label' in n.props && n.props.label === 'View')[0];
  assert.deepEqual(all(pop.props.children, n => n.props?.role === 'radiogroup').length, 0);   // Choice elements aren't expanded yet
  assert.deepEqual(choices({ type: 'div', props: { children: pop.props.children } }), ['Group by', 'Environments by', 'Chats by']);
  const flat = g.ViewMenu({ view: v, onChange() {}, grouped: false });
  const pop2 = all(flat, n => n.props && n.props.label === 'View')[0];
  assert.deepEqual(choices({ type: 'div', props: { children: pop2.props.children } }), ['Chats by']);
});

test('a chat\'s menu: Rename, Move to (other environments), Archive, Delete (its row: chat-list.test.mjs)', () => {
  const t = { id: 't1', title: 'Report', settings: { environment: 'grants' } };
  // the menu's popover renders only while open (the stub's useState keeps it shut): read its children
  const menu = el => all(el, n => n.props?.label === 'Chat actions')[0].props.children.filter(Boolean).map(b => text(b.props.children.filter(c => c?.type !== 'kbd')));
  const raw = list.Item({ t, active: false, onRename() {}, onArchive() {}, onDelete() {}, moveTo: [ENVS[0], ENVS[2]], onMove() {} });
  assert.deepEqual(menu(raw), ['Rename', 'Move to…', 'Archive', 'Delete…']);
  const el = expand(raw);
  assert.equal(text(el), 'Report');                                // no environment on the row (chat-history 2.1)
  assert.deepEqual(menu(list.Item({ t, active: false, onRename() {}, onArchive() {}, onDelete() {} })), ['Rename', 'Archive', 'Delete…']);
  const link = all(el, n => n.type === 'a')[0];
  assert.equal(typeof link.props.onDoubleClick, 'function');      // double-click renames
});

test('the list shows the sections, or a flat list while searching', () => {
  const props = { threads: [{ id: 't9', title: 'Flat one' }], loading: false, activeId: null, q: '', onQ() {}, archived: false, onArchived() {},
    onNew() {}, onRename() {}, onArchive() {}, onDelete() {}, grouped: { type: 'div', props: { children: ['SECTIONS'] } } };
  assert.match(text(expand(list.ThreadList(props))), /SECTIONS/);
  const searching = text(expand(list.ThreadList({ ...props, q: 'flat' })));
  assert.match(searching, /Flat one/);
  assert.doesNotMatch(searching, /SECTIONS/);
  assert.match(text(expand(list.ThreadList({ ...props, grouped: null }))), /Flat one/);
});

test('the client asks the agent per environment, and the mock answers the same way', async () => {
  const api = await load('chat/chat-api.js');
  const seen = [];
  const c = api.createLiveClient({ base: 'http://h', fetch: async (url) => { seen.push(url); return new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } }); } });
  await c.threads({ environment: 'default,gone', sort: 'title', limit: 6, offset: 6 });
  await c.threads({ sort: 'updated' });
  await c.threadGroups({ archived: true });
  assert.match(seen[0], /\/v1\/threads\?.*environment=default%2Cgone/);
  assert.match(seen[0], /sort=title/);
  assert.match(seen[0], /offset=6/);
  assert.doesNotMatch(seen[1], /sort=/);
  assert.match(seen[2], /\/v1\/threads\/groups\?archived=true/);

  const { createMockClient } = await load('chat/chat-mock.js');
  const m = createMockClient(null, { speed: 1000 });
  const a = await m.create({ title: 'b chat', settings: { environment: 'grants' } });
  await m.create({ title: 'A chat', settings: { environment: 'grants' } });
  const groups = await m.threadGroups();
  assert.equal(groups.find(x => x.environment === 'grants').count, 2);
  assert.deepEqual((await m.threads({ environment: 'grants', sort: 'title' })).map(t => t.title), ['A chat', 'b chat']);
  assert.ok((await m.threads({ environment: 'default' })).every(t => (t.settings?.environment || 'default') === 'default'));
  assert.equal((await m.threads({ environment: 'grants', limit: 1, offset: 1, sort: 'title' }))[0].id, a.id);
});

// Plan 42.1: the compact sidebar after Claude Code's.
test('the top: the search across, then + New with View on its right; no Chats label, no By meaning', () => {
  const props = { threads: [], loading: false, activeId: null, q: '', onQ() {}, archived: false, onArchived() {}, onNew() {}, onRename() {}, onArchive() {}, onDelete() {},
    view: g.readView({}), onView() {}, canGroup: true };
  const el = expand(list.ThreadList(props));
  const rows = el.props.children.filter(Boolean);
  const first = rows[0], second = rows[1];
  const search = all(first, n => n.type === 'input' && n.props['aria-label'] === 'Search chats');
  assert.equal(search.length, 1);
  assert.equal(search[0].props.placeholder, 'Search');
  assert.equal(text(second).trim(), 'New');
  assert.equal(all(second, n => n.props?.['aria-label'] === 'View').length, 1);
  const kids = second.props.children.filter(Boolean);
  assert.equal(all(kids[kids.length - 1], n => n.props?.['aria-label'] === 'View').length, 1);  // View on the right of New
  assert.doesNotMatch(text(el), /By meaning|Chats/);
  assert.equal(all(expand(list.ThreadList({ ...props, archived: true })), n => n.type === 'input')[0].props.placeholder, 'Search archived');
});

test('Show more is a full-width divider with its count', () => {
  const bar = expand(g.MoreBar({ n: 7, onClick() {} }));
  assert.equal(bar.type, 'button');
  assert.equal(bar.props.style.width, '100%');
  assert.equal(text(bar), 'Show more · 7');
  assert.equal(bar.props.children.filter(c => c?.props?.style?.height === 1).length, 2);      // a line on each side
  assert.equal(text(expand(g.MoreBar({ onClick() {} }))), 'Show more');
});

test('None\'s section has no ⋯ menu (nothing to rename or fill)', () => {
  const row = { env: { id: 'none', name: 'None', none: true, folders: [] }, ids: ['none'], count: 1, updated: 1, running: 0 };
  const el = expand(g.Section({ row, open: true, chats: [], loading: false, more: false, renderItem: () => null, onToggle() {}, onNew() {}, onRename() {}, onManage() {} }));
  assert.equal(all(el, n => n.props?.['aria-label'] === 'More for None').length, 0);
  assert.equal(all(el, n => n.props?.['aria-label'] === 'New chat in None').length, 1);
});

test('the chat menu\'s letters: R renames, M moves, A archives, D deletes; not while typing', () => {
  const key = (k, o = {}) => list.menuKey({ key: k, target: { tagName: 'BODY' }, ...o });
  assert.deepEqual(['r', 'M', 'a', 'D', 'x'].map(k => key(k)), ['r', 'm', 'a', 'd', null]);
  assert.equal(key('a', { ctrlKey: true }), null);
  assert.equal(key('d', { target: { tagName: 'INPUT' } }), null);
  const t = { id: 't1', title: 'Report' };
  const items = all(list.Item({ t, active: false, onRename() {}, onArchive() {}, onDelete() {}, moveTo: [ENVS[2]], onMove() {} }), n => n.props?.label === 'Chat actions')[0]
    .props.children.filter(Boolean);
  assert.deepEqual(items.map(b => b.props['aria-keyshortcuts']), ['R', 'M', 'A', 'D']);
});

test('View shows archived chats too (Show: Chats · Archived)', () => {
  const got = [];
  const menu = g.ViewMenu({ view: g.readView({}), onChange() {}, grouped: true, archived: false, onArchived: v => got.push(v) });
  const pop = all(menu, n => n.props?.label === 'View')[0];
  const show = pop.props.children.filter(Boolean)[0];
  assert.equal(show.props.label, 'Show');
  assert.equal(show.props.value, 'chats');
  show.props.onPick('archived');
  assert.deepEqual(got, [true]);
});
