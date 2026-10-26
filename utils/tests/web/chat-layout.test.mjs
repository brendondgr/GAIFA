// web/chat/chat-layout.js (chat-split plan 2.1): splitting at each edge, same-direction siblings, nesting four deep,
// closing down to one pane, moving, resizing within bounds, dropping deleted chats, and saved layouts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const L = await import(pathToFileURL(path.join(root, 'web/chat/chat-layout.js')).href);
const tids = x => L.panes(x.root).map(p => p.tid);
const sum = a => a.reduce((x, y) => x + y, 0);
const close = (a, b) => Math.abs(a - b) < 1e-9;

test('a split at each edge puts the new pane on that side, and it becomes active', () => {
  for (const [edge, dir, order] of [['left', 'row', ['b', 'a']], ['right', 'row', ['a', 'b']], ['top', 'col', ['b', 'a']], ['bottom', 'col', ['a', 'b']]]) {
    const x = L.splitPane(L.single('a'), 'p1', edge, 'b');
    assert.equal(x.root.dir, dir, edge);
    assert.deepEqual(tids(x), order, edge);
    assert.deepEqual(x.root.sizes, [0.5, 0.5]);
    assert.equal(L.activePane(x).tid, 'b');
  }
});

test('a split in the same direction adds a sibling that takes half the target\'s space', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  x = L.splitPane(x, x.active, 'right', 'c');
  assert.equal(x.root.dir, 'row');
  assert.deepEqual(tids(x), ['a', 'b', 'c']);
  assert.deepEqual(x.root.sizes, [0.5, 0.25, 0.25]);
  x = L.splitPane(x, 'p1', 'left', 'z');
  assert.deepEqual(tids(x), ['z', 'a', 'b', 'c']);
  assert.ok(close(sum(x.root.sizes), 1));
});

test('splits nest without a limit, alternating directions, and every id is unique', () => {
  let x = L.single('a');
  const edges = ['right', 'bottom', 'right', 'bottom', 'right', 'bottom', 'right', 'bottom'];
  edges.forEach((e, i) => { x = L.splitPane(x, x.active, e, 't' + i); });
  assert.equal(L.panes(x.root).length, 9);
  let depth = 0;
  for (let n = x.root; !L.isPane(n); n = n.kids[1]) depth++;
  assert.ok(depth >= 4, 'four deep or more');
  const ids = [];
  (function walk(n) { ids.push(n.id); if (n.kids) n.kids.forEach(walk); })(x.root);
  assert.equal(new Set(ids).size, ids.length);
});

test('closing a pane gives its space back, collapses splits of one, and the last pane stays as a new chat', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  const b = x.active;
  x = L.splitPane(x, b, 'bottom', 'c');
  assert.deepEqual(tids(x), ['a', 'b', 'c']);
  const c = x.active;
  x = L.closePane(x, c);
  assert.deepEqual(tids(x), ['a', 'b']);
  assert.equal(x.root.dir, 'row', 'the column of one collapsed into the row');
  assert.equal(x.active, b, 'the pane before it becomes active');
  x = L.closePane(x, b);
  assert.ok(L.isPane(x.root));
  assert.equal(x.root.tid, 'a');
  x = L.closePane(x, x.root.id);
  assert.ok(L.isPane(x.root));
  assert.equal(x.root.tid, null);
});

test('closing a middle pane flattens a split left in the same direction as its parent', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');      // row [a, b]
  x = L.splitPane(x, x.active, 'bottom', 'c');                 // row [a, col [b, c]]
  const b = L.panes(x.root)[1].id;
  x = L.splitPane(x, b, 'right', 'd');                         // row [a, col [row [b, d], c]]
  x = L.closePane(x, L.panes(x.root).find(p => p.tid === 'c').id);
  assert.equal(x.root.dir, 'row');
  assert.deepEqual(tids(x), ['a', 'b', 'd']);
  assert.ok(x.root.kids.every(L.isPane), 'row [a, b, d], not row [a, row [b, d]]');
  assert.ok(close(sum(x.root.sizes), 1));
});

test('moving a pane keeps its chat, places it at the edge and makes it active', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  x = L.splitPane(x, x.active, 'right', 'c');                  // [a, b, c]
  const c = x.active;
  x = L.movePane(x, c, 'p1', 'top');
  assert.deepEqual(tids(x), ['c', 'a', 'b']);
  assert.equal(L.activePane(x).tid, 'c');
  assert.equal(x.active, c, 'it keeps its id, so the view keeps the chat mounted');
  assert.equal(L.movePane(x, x.active, x.active, 'left'), x, 'onto itself: nothing');
});

test('resize moves one divider and stops at the smallest size', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  const s = x.root.id;
  x = L.resize(x, s, 0, 0.2);
  assert.ok(close(x.root.sizes[0], 0.7));
  x = L.resize(x, s, 0, 0.5, 0.2);
  assert.ok(close(x.root.sizes[1], 0.2), 'stops at min');
  x = L.resize(x, s, 0, -5, 0.2);
  assert.ok(close(x.root.sizes[0], 0.2));
  x = L.equalize(x, s);
  assert.deepEqual(x.root.sizes, [0.5, 0.5]);
  assert.deepEqual(L.resize(x, s, 1, 0.1).root.sizes, [0.5, 0.5], 'no divider after the last kid');
});

test('paneSize and splitPaneSize give pixel sizes, for refusing a split that would be too small', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  x = L.resize(x, x.root.id, 0, 0.25);                       // [0.75, 0.25]
  assert.deepEqual(L.paneSize(x.root, 'p1', 1200, 800), { w: 900, h: 800 });
  assert.deepEqual(L.splitPaneSize(x, x.active, 'right', 1200, 800), { w: 150, h: 800 });
  assert.deepEqual(L.splitPaneSize(x, x.active, 'bottom', 1200, 800), { w: 300, h: 400 });
});

test('a deleted chat closes its panes', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  x = L.splitPane(x, x.active, 'bottom', 'a');
  x = L.dropTids(x, ['a']);
  assert.deepEqual(tids(x), ['b']);
  x = L.dropTids(x, ['b']);
  assert.deepEqual(tids(x), [null]);
});

test('setTid and setActive', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', null);
  x = L.setTid(x, x.active, 'b');
  assert.deepEqual(tids(x), ['a', 'b']);
  x = L.setActive(x, 'p1');
  assert.equal(x.active, 'p1');
  assert.equal(L.setActive(x, 'nope'), x);
});

test('a saved layout round-trips; a corrupt or hostile one gives null', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');
  x = L.splitPane(x, x.active, 'bottom', null);
  const store = new Map(), storage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  L.saveLayout(x, storage);
  const y = L.loadLayout(storage);
  assert.deepEqual(y, x);
  for (const bad of ['', 'nope', '{}', '{"root":{"id":"s1","dir":"row","sizes":[1],"kids":[]}}', '{"root":{"id":"p1","tid":5}}',
    '{"root":{"id":"s1","dir":"diag","sizes":[0.5,0.5],"kids":[{"id":"p1"},{"id":"p2"}]}}', '{"root":{"id":"s1","dir":"row","sizes":[0.5,0.5],"kids":[{"id":"p1"},{"id":"p1"}]}}']) {
    assert.equal(L.parseLayout(bad), null, bad);
  }
  const z = L.parseLayout('{"root":{"id":"s9","dir":"row","sizes":[3,1],"kids":[{"id":"p4","tid":"a"},{"id":"p7"}]},"active":"gone"}');
  assert.deepEqual(z.root.sizes, [0.75, 0.25], 'sizes normalized');
  assert.equal(z.active, 'p4', 'an unknown active pane: the first');
  assert.equal(z.next, 10, 'new ids never reuse a saved one');
  assert.equal(L.panes(z.root)[1].tid, null);
  const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(L.loadLayout(throwing), null);
  assert.doesNotThrow(() => L.saveLayout(x, throwing));
});

test('geometry places every pane and divider; the boxes tile the whole area', () => {
  let x = L.splitPane(L.single('a'), 'p1', 'right', 'b');      // row [a, b]
  x = L.splitPane(x, x.active, 'bottom', 'c');                 // row [a, col [b, c]]
  x = L.resize(x, x.root.id, 0, 0.1);                          // a: 0.6
  const g = L.geometry(x.root);
  const at = id => g.panes.find(p => p.id === id);
  const [a, b, c] = L.panes(x.root).map(p => at(p.id));
  assert.deepEqual([a.x, a.y, a.h], [0, 0, 1]); assert.ok(close(a.w, 0.6));
  assert.ok(close(b.x, 0.6) && close(b.w, 0.4) && close(b.h, 0.5) && b.y === 0);
  assert.ok(close(c.y, 0.5) && close(c.h, 0.5));
  assert.ok(close(sum(g.panes.map(p => p.w * p.h)), 1), 'no gaps or overlaps');
  assert.equal(g.dividers.length, 2);
  const row = g.dividers.find(d => d.dir === 'row'), col = g.dividers.find(d => d.dir === 'col');
  assert.ok(close(row.at, 0.6)); assert.ok(close(col.at, 0.5)); assert.ok(close(col.box.x, 0.6) && close(col.box.w, 0.4));
  assert.deepEqual(L.geometry(L.single('z').root), { panes: [{ id: 'p1', tid: 'z', x: 0, y: 0, w: 1, h: 1 }], dividers: [] });
});

test('dropZone: the nearest edge within a band, else the middle', () => {
  assert.equal(L.dropZone(10, 300, 800, 600), 'left');
  assert.equal(L.dropZone(790, 300, 800, 600), 'right');
  assert.equal(L.dropZone(400, 20, 800, 600), 'top');
  assert.equal(L.dropZone(400, 590, 800, 600), 'bottom');
  assert.equal(L.dropZone(400, 300, 800, 600), 'center');
  assert.equal(L.dropZone(30, 20, 800, 600), 'top', 'a corner: the nearer edge by fraction (20/600 < 30/800)');
});
