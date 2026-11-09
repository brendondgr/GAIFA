// Plan chat-history 3.1: the Show all page's pure parts: the page arithmetic, merging loads without repeating a chat
// that moved between them, a chat's environment, grouping what's loaded (date, environment, flat), the ↑/↓ steps, and
// a row with its environment and date.

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
const a = await load('chat/chat-all.js');
const list = await load('chat/chat-list.js');
await load('chat/chat.js');                   // the page imports it cleanly

function expand(n) {
  if (n == null || n === false || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(expand);
  if (typeof n.type === 'function') return expand(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
}
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
const at = (y, m, d, hh = 12) => new Date(y, m - 1, d, hh).getTime() / 1000;
const ENVS = [{ id: 'none', name: 'None', none: true }, { id: 'default', name: 'Default', default: true }, { id: 'ariadne', name: 'Ariadne' }];

test('pages of 50 until the count is reached', () => {
  assert.equal(a.ALL_PAGE, 50);
  assert.deepEqual(a.nextPage(0, 120), { offset: 0, limit: 50 });
  assert.deepEqual(a.nextPage(50, 120), { offset: 50, limit: 50 });
  assert.deepEqual(a.nextPage(100, 120), { offset: 100, limit: 50 });
  assert.equal(a.nextPage(120, 120), null);
  assert.equal(a.nextPage(130, 120), null);                       // more than the count (a chat made meanwhile): done
  assert.deepEqual(a.nextPage(50, null), { offset: 50, limit: 50 });   // no count: until a short page
  assert.equal(a.nextPage(50, null, true), null);
  assert.equal(a.nextPage(0, 0), null);
});

test('merging pages: a chat that moved up between two loads stays once; a short page ends it', () => {
  const p1 = Array.from({ length: 50 }, (_, i) => ({ id: 't' + i }));
  // t49 got a message between the loads, so the next page starts one later and repeats t48
  const p2 = [{ id: 't48' }, { id: 't50' }, { id: 't51' }];
  const out = a.addPage(p1, p2);
  assert.equal(out.items.length, 52);
  assert.equal(new Set(out.items.map(t => t.id)).size, 52);
  assert.equal(out.items.at(-1).id, 't51');
  assert.equal(out.done, true);
  assert.equal(a.addPage([], p1).done, false);
});

test('a chat\'s environment, a deleted one counting as Default', () => {
  assert.deepEqual(a.envOf({ settings: { environment: 'ariadne' } }, ENVS), { id: 'ariadne', name: 'Ariadne' });
  assert.deepEqual(a.envOf({ settings: {} }, ENVS), { id: 'default', name: 'Default' });
  assert.deepEqual(a.envOf({ settings: { environment: 'gone' } }, ENVS), { id: 'default', name: 'Default' });
  assert.deepEqual(a.envOf({}, null), { id: 'default', name: 'Default' });
});

test('grouping what is loaded: by date, by environment, flat', () => {
  const now = at(2026, 11, 8, 15);
  const items = [{ id: 'a', title: 'a', updated: at(2026, 11, 8), settings: { environment: 'ariadne' } }, { id: 'b', title: 'b', updated: at(2026, 11, 7) },
    { id: 'c', title: 'c', updated: at(2026, 10, 1), settings: { environment: 'ariadne' } }, { id: 'd', title: 'd', updated: at(2026, 11, 8, 9), settings: { environment: 'none' } }];
  assert.deepEqual(a.groupLoaded(items, { group: 'date', now }).map(g => [g.key, g.threads.map(t => t.id)]), [['today', ['a', 'd']], ['yesterday', ['b']], ['older', ['c']]]);
  assert.deepEqual(a.groupLoaded(items, { group: 'environment', envs: ENVS }).map(g => [g.label, g.threads.map(t => t.id)]),
    [['Ariadne', ['a', 'c']], ['Default', ['b']], ['None', ['d']]]);
  assert.deepEqual(a.groupLoaded(items, {}).map(g => [g.label, g.threads.length]), [[null, 4]]);
});

test('↑/↓ move through the rows and stay inside the list', () => {
  assert.equal(a.stepRow(-1, 'ArrowDown', 3), 0);                 // from the search box: the first row
  assert.equal(a.stepRow(0, 'ArrowDown', 3), 1);
  assert.equal(a.stepRow(2, 'ArrowDown', 3), 2);
  assert.equal(a.stepRow(2, 'ArrowUp', 3), 1);
  assert.equal(a.stepRow(0, 'ArrowUp', 3), 0);
  assert.equal(a.stepRow(-1, 'ArrowUp', 3), 0);
  assert.equal(a.stepRow(0, 'ArrowDown', 0), -1);
});

test('a row on the page: the sidebar\'s, with its environment and date after the name', () => {
  const t = { id: 't1', title: 'Report', updated: at(2025, 11, 5) };
  const el = expand(list.Item({ t, active: false, onRename() {}, onArchive() {}, onDelete() {}, aside: [{ type: 'span', props: { children: ['Ariadne'] } }, { type: 'span', props: { children: ['Nov 5, 2025'] } }] }));
  assert.equal(text(el), 'ReportAriadneNov 5, 2025');
  assert.equal(text(expand(list.Item({ t, active: false, onRename() {}, onArchive() {}, onDelete() {} }))), 'Report');   // the sidebar: the name only
});

test('the page: its title, the search from the URL, Show and Group by as chips', () => {
  const view = { show: 'both', group: 'date', envOrder: 'activity', chatOrder: 'updated', collapsed: [] };
  const el = a.AllChats({ c: {}, view, onView() {}, envs: ENVS, q0: 'fox', actions: {}, reloadKey: 0 });
  const all = (n, pred, out = []) => { if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; } if (!n || typeof n !== 'object') return out; if (pred(n)) out.push(n); all(n.props?.children, pred, out); return out; };
  assert.equal(el.props['aria-label'], 'All chats');
  assert.equal(all(el, n => n.type === 'h2').map(text)[0], 'All chats');
  assert.equal(all(el, n => n.type === 'input')[0].props.value, 'fox');
  const chips = all(el, n => n.props && 'options' in n.props && 'label' in n.props);
  assert.deepEqual(chips.map(c => [c.props.label, c.props.value]), [['Show', 'both'], ['Group by', 'date']]);
  assert.deepEqual(chips[1].props.options.map(([k]) => k), ['environment', 'date', 'none']);
});

// chat-history 3.2: the palette's pages list it, next to Chat.
test('the command palette offers All chats', async () => {
  const { readFile } = await import('node:fs/promises');
  const hub = await readFile(path.join(root, 'web/Hub.dc.html'), 'utf8');
  assert.match(hub, /\['Chat', '#\/chat', ICON\.chat\], \['All chats', '#\/chat\/all', ICON\.chat\]/);
});
