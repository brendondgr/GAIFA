// The Chat page's split layout (chat-split plan 2.1): a tree of panes and splits, as pure functions over a layout
// value, saved on the hub (`hub.chat.layout` in the UI store, settings-that-stick 4.3; this browser's copy paints first).
// Tested in utils/tests/web/chat-layout.test.mjs.
//
//   layout: {root, active, next}         active: the pane id the URL follows; next: the counter for new ids
//   pane:   {id: 'p3', tid}              tid null: a new chat, not created yet
//   split:  {id: 's2', dir: 'row' | 'col', sizes: [fractions summing to 1], kids: [nodes]}
//
// A split in the same direction as its parent is never nested in it: its kids join the parent's (`normalize`).

import { store } from '../ui-store.js';

export const LAYOUT_KEY = 'gaifa.chat.layout';   // the key this browser used before; the store's is HUB_LAYOUT
export const HUB_LAYOUT = 'hub.chat.layout';
/** The UI store as the storage loadLayout/saveLayout take: saved to the hub once dragging stops for 2 s. */
export const hubStorage = {
  getItem: () => { const v = store.get(HUB_LAYOUT, null); return v == null ? null : JSON.stringify(v); },
  setItem: (k, v) => store.set(HUB_LAYOUT, JSON.parse(v), { wait: 2000 }),
};
const EDGES = { left: ['row', true], right: ['row', false], top: ['col', true], bottom: ['col', false] };

export function single(tid = null) { return { root: { id: 'p1', tid }, active: 'p1', next: 2 }; }

export const isPane = n => !!n && !n.kids;
/** The panes in reading order (left to right, top to bottom). */
export function panes(node) { return isPane(node) ? [node] : node.kids.flatMap(panes); }
export function findPane(L, id) { return panes(L.root).find(p => p.id === id) || null; }
export function activePane(L) { return findPane(L, L.active) || panes(L.root)[0]; }
/** The split holding `id` and its index there, or null for the root. */
function parentOf(node, id) {
  if (isPane(node)) return null;
  for (let i = 0; i < node.kids.length; i++) {
    if (node.kids[i].id === id) return { parent: node, index: i };
    const r = parentOf(node.kids[i], id);
    if (r) return r;
  }
  return null;
}
/** A copy of the tree with node `id` replaced by fn(node) (fn may return null to drop it). */
function mapNode(node, id, fn) {
  if (node.id === id) return fn(node);
  if (isPane(node)) return node;
  const kids = [], sizes = [];
  node.kids.forEach((k, i) => { const n = mapNode(k, id, fn); if (n) { kids.push(n); sizes.push(node.sizes[i]); } });
  return { ...node, kids, sizes };
}

/** Sizes summing to 1, no split of one, no split nested in one of its own direction. */
export function normalize(node) {
  if (isPane(node)) return node;
  let kids = [], sizes = [];
  node.kids.forEach((k, i) => {
    const n = normalize(k), s = Number.isFinite(node.sizes?.[i]) && node.sizes[i] > 0 ? node.sizes[i] : 1 / node.kids.length;
    if (!isPane(n) && n.dir === node.dir) { const t = n.sizes.reduce((a, b) => a + b, 0) || 1; n.kids.forEach((kk, j) => { kids.push(kk); sizes.push(s * n.sizes[j] / t); }); }
    else { kids.push(n); sizes.push(s); }
  });
  if (kids.length === 1) return kids[0];
  const total = sizes.reduce((a, b) => a + b, 0) || 1;
  return { ...node, kids, sizes: sizes.map(x => x / total) };
}

/** Split pane `paneId` at `edge` (left | right | top | bottom) with a new pane showing `tid`; the new pane is active.
 *  `keep`: the new pane's id (a moved pane keeps its own, so its chat isn't drawn again from scratch). */
export function splitPane(L, paneId, edge, tid = null, keep = null) {
  const [dir, before] = EDGES[edge] || EDGES.right;
  if (!findPane(L, paneId)) return L;
  const id = keep || 'p' + L.next, fresh = { id, tid }, sid = 's' + (L.next + 1);
  const at = parentOf(L.root, paneId);
  let root;
  if (at && at.parent.dir === dir) {           // a sibling in the same row or column: the target gives it half its space
    root = mapNode(L.root, at.parent.id, s => {
      const kids = [...s.kids], sizes = [...s.sizes], half = sizes[at.index] / 2, i = before ? at.index : at.index + 1;
      sizes[at.index] = half; kids.splice(i, 0, fresh); sizes.splice(i, 0, half);
      return { ...s, kids, sizes };
    });
  } else {
    root = mapNode(L.root, paneId, p => ({ id: sid, dir, sizes: [0.5, 0.5], kids: before ? [fresh, p] : [p, fresh] }));
  }
  return { root: normalize(root), active: id, next: L.next + 2 };
}

/** Close a pane: its space goes to its neighbours; the last pane stays, as a new chat. */
export function closePane(L, paneId) {
  if (isPane(L.root)) return L.root.id === paneId ? { ...L, root: { ...L.root, tid: null } } : L;
  const at = parentOf(L.root, paneId);
  if (!at) return L;
  const order = panes(L.root).map(p => p.id), i = order.indexOf(paneId);
  const root = normalize(mapNode(L.root, paneId, () => null));
  const left = panes(root).map(p => p.id);
  const active = L.active !== paneId && left.includes(L.active) ? L.active : (order.slice(0, i).reverse().find(x => left.includes(x)) || left[0]);
  return { ...L, root, active };
}

/** Move pane `paneId` next to `targetId` at `edge`; it keeps its id and chat, and becomes active. */
export function movePane(L, paneId, targetId, edge) {
  const p = findPane(L, paneId);
  if (!p || paneId === targetId || !findPane(L, targetId) || panes(L.root).length < 2) return L;
  return splitPane(closePane(L, paneId), targetId, edge, p.tid, p.id);
}

export function setTid(L, paneId, tid) {
  if (!findPane(L, paneId)) return L;
  return { ...L, root: mapNode(L.root, paneId, p => ({ ...p, tid: tid || null })) };
}
export function setActive(L, paneId) { return findPane(L, paneId) && L.active !== paneId ? { ...L, active: paneId } : L; }

/** A chat that's gone (deleted, or its environment deleted): its panes close; the last one becomes a new chat. */
export function dropTids(L, tids) {
  const gone = new Set(tids);
  let out = L;
  for (const p of panes(L.root)) if (p.tid && gone.has(p.tid)) out = closePane(out, p.id);
  return out;
}

/** Move the divider after kid `i` of split `splitId` by `delta` (a fraction of the split), keeping both sides ≥ `min`. */
export function resize(L, splitId, i, delta, min = 0.1) {
  return { ...L, root: mapNode(L.root, splitId, s => {
    if (isPane(s) || i < 0 || i + 1 >= s.kids.length) return s;
    const pair = s.sizes[i] + s.sizes[i + 1], lo = Math.min(min, pair / 2);
    const a = Math.max(lo, Math.min(pair - lo, s.sizes[i] + delta)), sizes = [...s.sizes];
    sizes[i] = a; sizes[i + 1] = pair - a;
    return { ...s, sizes };
  }) };
}
export function equalize(L, splitId) {
  return { ...L, root: mapNode(L.root, splitId, s => (isPane(s) ? s : { ...s, sizes: s.kids.map(() => 1 / s.kids.length) })) };
}

/** Every split with its pixel size, for the view to know how small a pane would get (dir 'row': widths). */
export function splitPaneSize(L, paneId, edge, w, h) {
  const [dir] = EDGES[edge] || EDGES.right;
  const size = paneSize(L.root, paneId, w, h);
  if (!size) return null;
  return dir === 'row' ? { w: size.w / 2, h: size.h } : { w: size.w, h: size.h / 2 };
}
/** A pane's size in pixels inside a box of w × h (dividers ignored). */
export function paneSize(node, paneId, w, h) {
  if (isPane(node)) return node.id === paneId ? { w, h } : null;
  for (let i = 0; i < node.kids.length; i++) {
    const r = paneSize(node.kids[i], paneId, node.dir === 'row' ? w * node.sizes[i] : w, node.dir === 'col' ? h * node.sizes[i] : h);
    if (r) return r;
  }
  return null;
}

/** Where each pane and divider sits, as fractions of the page's split area: panes [{id, tid, x, y, w, h}] and
 *  dividers [{split, i, dir, box, at}] (`at`: the divider's x for a row, y for a column; `box`: its split's box).
 *  The view draws every pane at its box, keyed by id, so a split or a move never remounts a chat. */
export function geometry(root) {
  const out = { panes: [], dividers: [] };
  (function walk(n, b) {
    if (isPane(n)) { out.panes.push({ id: n.id, tid: n.tid, ...b }); return; }
    let at = 0;
    n.kids.forEach((k, i) => {
      const s = n.sizes[i];
      walk(k, n.dir === 'row' ? { x: b.x + b.w * at, y: b.y, w: b.w * s, h: b.h } : { x: b.x, y: b.y + b.h * at, w: b.w, h: b.h * s });
      at += s;
      if (i < n.kids.length - 1) out.dividers.push({ split: n.id, i, dir: n.dir, box: b, at: n.dir === 'row' ? b.x + b.w * at : b.y + b.h * at });
    });
  })(root, { x: 0, y: 0, w: 1, h: 1 });
  return out;
}

/** The drop zone under the pointer at (x, y) in a pane of w × h: the nearest edge within `edge` of it, else 'center'. */
export function dropZone(x, y, w, h, edge = 0.28) {
  const d = [['left', x / w], ['right', 1 - x / w], ['top', y / h], ['bottom', 1 - y / h]].sort((a, b) => a[1] - b[1])[0];
  return d[1] < edge ? d[0] : 'center';
}

function valid(node, seen) {
  if (!node || typeof node !== 'object' || typeof node.id !== 'string' || seen.has(node.id)) return false;
  seen.add(node.id);
  if (!node.kids) return node.tid === null || node.tid === undefined || typeof node.tid === 'string';
  return (node.dir === 'row' || node.dir === 'col') && Array.isArray(node.kids) && node.kids.length > 0 && Array.isArray(node.sizes)
    && node.kids.length === node.sizes.length && node.kids.every(k => valid(k, seen));
}
const idNum = id => +String(id).slice(1) || 0;
/** A saved layout (a JSON string) → a layout, or null when it doesn't parse. */
export function parseLayout(text) {
  let v;
  try { v = JSON.parse(text); } catch { return null; }
  if (!v || !valid(v.root, new Set())) return null;
  const root = normalize(v.root), ids = [];
  (function walk(n) { ids.push(idNum(n.id)); if (!isPane(n)) n.kids.forEach(walk); })(root);
  for (const p of panes(root)) if (p.tid === undefined) p.tid = null;
  const next = Math.max(Number.isInteger(v.next) ? v.next : 0, Math.max(...ids) + 1);
  return { root, active: findPane({ root }, v.active) ? v.active : panes(root)[0].id, next };
}
export function loadLayout(storage = hubStorage) {
  try { return parseLayout(storage?.getItem(LAYOUT_KEY)) || null; } catch { return null; }
}
export function saveLayout(L, storage = hubStorage) {
  try { storage?.setItem(LAYOUT_KEY, JSON.stringify(L)); } catch { /* private window, storage full: the layout lasts this page */ }
}
