// Plan chat-history 2.1: a row in the chat list shows only the chat's name (no time, no environment), its state dot,
// ⋯ in a slot that's empty until hover or focus (always on touch screens), and an archived chat dimmed with an
// archive mark and Unarchive in its menu; the menu's letters.

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
const noop = () => {};
const row = (t, o = {}) => expand(list.Item({ t, active: false, onRename: noop, onArchive: noop, onDelete: noop, ...o }));
const menu = t => all(list.Item({ t, active: false, onRename: noop, onArchive: noop, onDelete: noop }), n => n.props?.label === 'Chat actions')[0]
  .props.children.filter(Boolean).map(b => text(b.props.children.filter(c => c?.type !== 'kbd')));

test('what a row shows: live, running, waiting, failed, archived', () => {
  assert.deepEqual(list.rowLook({ title: 'Report', state: 'idle' }), { title: 'Report', state: null, dot: null, archived: false, archiveLabel: 'Archive' });
  assert.equal(list.rowLook({ title: '' }).title, 'New chat');
  assert.equal(list.rowLook({ running: true }).state, 'running');
  assert.equal(list.rowLook({ state: 'running' }).state, 'running');
  assert.equal(list.rowLook({ state: 'waiting' }).state, 'waiting');
  assert.equal(list.rowLook({ state: 'error' }).state, 'error');
  assert.ok(list.rowLook({ state: 'error' }).dot);
  const a = list.rowLook({ title: 'Old', archived: true });
  assert.deepEqual([a.archived, a.archiveLabel], [true, 'Unarchive']);
});

test('a row: the name only, no time and no environment', () => {
  const t = { id: 't1', title: 'Report', updated: Date.now() / 1000 - 3600, settings: { environment: 'grants' } };
  const el = row(t, { where: 'Grants' });                      // an old caller's `where` is ignored
  assert.equal(text(el), 'Report');
  assert.equal(all(el, n => n.props?.className === 'aichat-ago').length, 0);
  assert.equal(all(el, n => n.props?.['aria-label'] === 'Archived').length, 0);
  assert.equal(all(el, n => n.type === 'a')[0].props.style.opacity, 1);
});

test('⋯ sits in a slot that is empty until hover or focus, and always shows on touch screens', () => {
  const el = row({ id: 't1', title: 'Report' });
  const slot = all(el, n => n.props?.className === 'aichat-slot');
  assert.equal(slot.length, 1);
  assert.equal(all(slot[0], n => n.props?.className === 'aichat-more').length, 1);
  assert.match(list.LIST_CSS, /\.aichat-item \.aichat-more\{display:none\}/);
  assert.match(list.LIST_CSS, /\.aichat-item:hover \.aichat-more,\.aichat-item:focus-within \.aichat-more[^{]*\{display:grid\}/);
  assert.match(list.LIST_CSS, /@media \(hover:none\)\{\.aichat-item \.aichat-more\{display:grid\}/);
  assert.doesNotMatch(list.LIST_CSS, /aichat-ago/);
});

test('a running chat keeps its dot; an archived one is dimmed with an archive mark and says Unarchive', () => {
  const run = row({ id: 't1', title: 'Busy', running: true });
  assert.equal(all(run, n => n.props?.['aria-label'] === 'running').length, 1);
  const arch = row({ id: 't2', title: 'Old', archived: true });
  assert.equal(all(arch, n => n.props?.['aria-label'] === 'Archived').length, 1);
  assert.ok(all(arch, n => n.type === 'a')[0].props.style.opacity < 1);
  assert.match(all(arch, n => typeof n.props?.className === 'string' && n.props.className.startsWith('aichat-item'))[0].props.className, /archived/);
  assert.equal(text(arch), 'Old');
  assert.deepEqual(menu({ id: 't2', title: 'Old', archived: true }), ['Rename', 'Unarchive', 'Delete…']);
  assert.deepEqual(menu({ id: 't1', title: 'Report' }), ['Rename', 'Archive', 'Delete…']);
});

test('the menu\'s letters: r, m, a, d alone; not with a modifier or while typing', () => {
  const key = (k, o = {}) => list.menuKey({ key: k, target: { tagName: 'BODY' }, ...o });
  assert.deepEqual(['r', 'M', 'a', 'D', 'x'].map(k => key(k)), ['r', 'm', 'a', 'd', null]);
  assert.equal(key('a', { metaKey: true }), null);
  assert.equal(key('r', { target: { tagName: 'TEXTAREA' } }), null);
  assert.equal(key('r', { target: { tagName: 'DIV', isContentEditable: true } }), null);
  assert.equal(list.menuKey(null), null);
});
