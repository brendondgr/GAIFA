// The Overview's bento grid (plan overview-bento 1.1): 12 columns, fixed row heights and six tile sizes,
// so every tile fills its box and the grid has no holes. `BentoGrid` lays tiles out; `Tile` is the frame
// (header, a body that scrolls inside the tile, the ⋯ menu with Size, View as table, Open page and Hide),
// and hands its body's size to charts through `useTileSize()`. While editing, tiles drag onto each other
// to move. The layout itself is `[ui.dashboard]` (order, hidden, shown, sizes, ranges). Written by us
// (web/PATCHES.md).

import { h, MUT, BD, TONE } from './chart-kit.js';
import { MockBadge, RangePicker } from './views.js';

const R = () => globalThis.React;

// ---------- sizes and layout (pure; tested in utils/tests/web/bento.test.mjs) ----------
// size → [columns, rows] at full width.
export const SIZES = { xs: [3, 1], s: [4, 2], m: [4, 3], w: [6, 3], l: [8, 3], f: [12, 2] };
export const SIZE_LABEL = { xs: 'Small', s: 'Medium', m: 'Tall', w: 'Half', l: 'Wide', f: 'Full width' };
export const ROW_H = { compact: 60, comfortable: 68 };
export const GAP = { compact: 10, comfortable: 14 };

// [columns, rows] a size takes at a container width. Under 1100 px the 4-column sizes take half a row and
// the 8-column one the whole; under 760 px everything is full width but the small numbers, two to a row.
export function spanAt(size, width) {
  const [c, r] = SIZES[size] || SIZES.s;
  if (width < 760) return [c <= 3 ? 6 : 12, r];
  if (width < 1100) return [c <= 3 ? 3 : c <= 6 ? 6 : 12, r];
  return [c, r];
}

// The tile's size: the saved one when the tile allows it, else its default.
export function sizeOf(def, layout = {}) {
  const saved = layout.sizes?.[def.key];
  return saved && (def.sizes || [def.size]).includes(saved) ? saved : def.size;
}

// Every key in display order: the saved order first (unknown and repeated keys dropped), then the rest in
// the default order.
export function orderKeys(defaults, saved = []) {
  const known = new Set(defaults);
  const head = saved.filter((k, i) => known.has(k) && saved.indexOf(k) === i);
  return [...head, ...defaults.filter(k => !head.includes(k))];
}

// Whether a tile shows: an `off` tile only when turned on (`shown`), any other unless turned off (`hidden`).
export const isOn = (def, layout = {}) => (def.off ? (layout.shown || []).includes(def.key) : !(layout.hidden || []).includes(def.key));

export function visibleKeys(defs, layout = {}) {
  const by = new Map(defs.map(d => [d.key, d]));
  return orderKeys(defs.map(d => d.key), layout.order).filter(k => isOn(by.get(k), layout));
}

// The layout with a tile turned on or off.
export function setOn(layout, def, on) {
  const drop = (list, k) => (list || []).filter(x => x !== k), add = (list, k) => [...drop(list, k), k];
  if (def.off) return { ...layout, shown: on ? add(layout.shown, def.key) : drop(layout.shown, def.key) };
  return { ...layout, hidden: on ? drop(layout.hidden, def.key) : add(layout.hidden, def.key) };
}

// `order` with `key` moved to just before `before` (null: to the end).
export function dropBefore(order, key, before) {
  if (key === before || !order.includes(key)) return order;
  const o = order.filter(k => k !== key), i = before == null ? -1 : o.indexOf(before);
  if (i < 0) o.push(key); else o.splice(i, 0, key);
  return o;
}

// `order` with `key` swapped one place among the visible keys (dir −1 or +1), for the keyboard.
export function stepKey(order, visible, key, dir) {
  const i = visible.indexOf(key), j = i + dir;
  if (i < 0 || j < 0 || j >= visible.length) return order;
  return dir < 0 ? dropBefore(order, key, visible[j]) : dropBefore(order, visible[j], key);
}

// ---------- the tile's size, for charts ----------
let SizeCtx = null;
const sizeCtx = () => SizeCtx || (SizeCtx = R().createContext({ w: 0, h: 0 }));
/** The tile body's {w, h} in px (0 before the first measure). */
export const useTileSize = () => R().useContext(sizeCtx());

function useBox() {
  const { useState, useRef, useLayoutEffect } = R();
  const ref = useRef(null), [box, set] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return undefined;
    const put = (w, hh) => { w = Math.floor(w); hh = Math.floor(hh); set(p => (p.w === w && p.h === hh ? p : { w, h: hh })); };
    const r = el.getBoundingClientRect(); put(r.width, r.height);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(es => put(es[0].contentRect.width, es[0].contentRect.height));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, box];
}

// ---------- the tile ----------
const PATH = {
  more: 'M5 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0M10.5 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0M16 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0',
  grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01', check: 'M5 12l5 5 9-10',
};
export const Icon = ({ d, size = 14, color = 'currentColor', fill = false }) => h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: fill ? color : 'none', stroke: fill ? 'none' : color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { flex: 'none', display: 'block' } }, h('path', { d }));
const menuItem = { display: 'flex', alignItems: 'center', gap: 8, height: 28, padding: '0 8px', border: 0, borderRadius: 5, background: 'transparent', textAlign: 'left', cursor: 'pointer', fontSize: 12, color: 'var(--tx,#E6EAF2)', textDecoration: 'none', whiteSpace: 'nowrap' };
const sep = k => h('div', { key: k, role: 'separator', style: { height: 1, margin: '4px 2px', background: BD } });

function TileMenu({ title, sizes, size, onSize, table, onTable, href, onHide }) {
  const React = R(), [open, setOpen] = React.useState(false);
  const items = [];
  if (onSize && sizes?.length > 1) {
    items.push(h('div', { key: 'sh', style: { padding: '4px 8px 2px', fontSize: 10.5, color: MUT } }, 'Size'));
    for (const z of sizes) items.push(h('button', { key: 'z' + z, role: 'menuitemradio', 'aria-checked': z === size, type: 'button', onClick: () => { setOpen(false); onSize(z); }, style: menuItem },
      h('span', { style: { width: 12, display: 'flex' } }, z === size && h(Icon, { d: PATH.check, size: 12 })), SIZE_LABEL[z],
      h('span', { style: { marginLeft: 'auto', paddingLeft: 12, fontSize: 10.5, color: MUT, fontFamily: "'JetBrains Mono',ui-monospace,monospace" } }, SIZES[z].join('×'))));
    items.push(sep('s1'));
  }
  if (onTable) items.push(h('button', { key: 't', role: 'menuitem', type: 'button', onClick: () => { setOpen(false); onTable(!table); }, style: menuItem }, table ? 'View as chart' : 'View as table'));
  if (href) items.push(h('a', { key: 'o', role: 'menuitem', href, onClick: () => setOpen(false), style: menuItem }, 'Open page'));
  if (onHide) items.push(h('button', { key: 'x', role: 'menuitem', type: 'button', onClick: () => { setOpen(false); onHide(); }, style: menuItem }, 'Hide tile'));
  if (!items.length) return null;
  return h('div', { style: { position: 'relative', flex: 'none' } },
    h('button', { type: 'button', 'aria-label': `${title} options`, 'aria-haspopup': 'menu', 'aria-expanded': open, onClick: () => setOpen(!open), className: 'bento-more',
      style: { width: 22, height: 22, display: 'grid', placeItems: 'center', border: 0, borderRadius: 5, background: open ? 'var(--hov,#161C28)' : 'transparent', color: MUT, cursor: 'pointer' } },
      h(Icon, { d: PATH.more, size: 14, fill: true })),
    open && h('div', { onClick: () => setOpen(false), 'aria-hidden': true, style: { position: 'fixed', inset: 0, zIndex: 30 } }),
    open && h('div', { role: 'menu', style: { position: 'absolute', right: 0, top: 24, zIndex: 31, minWidth: 160, padding: 4, borderRadius: 8, background: 'var(--card,#11151D)', border: '1px solid var(--bds,#2A3547)', boxShadow: '0 12px 30px rgba(0,0,0,.4)', display: 'flex', flexDirection: 'column' } }, items));
}

/** A bento tile. `count`/`tone` badge the title; `flush` drops the body's padding (lists that run edge to edge). */
export function Tile(p) {
  const { title, icon, count, tone, ranges, range, onRange, href, link, mock, extra, children, size, flush, editing, grip, drag, style } = p;
  const React = R(), id = React.useId ? React.useId() : title, [ref, box] = useBox();
  const small = size === 'xs';
  return h('section', { 'aria-labelledby': id, ...drag, className: 'bento-tile',
    style: { position: 'relative', display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, background: 'var(--card,#11151D)', border: '1px solid ' + (editing ? 'var(--bds,#2A3547)' : BD), borderRadius: 10, padding: small ? '7px 10px' : '8px 10px 10px', gap: small ? 2 : 6, outline: drag?.['data-over'] ? '2px solid var(--acc,#FFB224)' : 'none', outlineOffset: 2, opacity: drag?.['data-dragging'] ? 0.45 : 1, cursor: editing ? 'grab' : 'auto', ...style } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, minHeight: small ? 16 : 22, minWidth: 0 } },
      grip,
      icon && !small && h('span', { style: { color: tone ? TONE[tone] : MUT, display: 'flex' } }, h(Icon, { d: icon, size: 13 })),
      h('h2', { id, style: { margin: 0, fontSize: small ? 11 : 11.5, fontWeight: small ? 400 : 600, color: small ? MUT : 'var(--tx,#E6EAF2)', flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
        link ? h('a', { href: link, style: { color: 'inherit', textDecoration: 'none' } }, title) : title),
      count != null && count !== '' && h('span', { style: { flex: 'none', minWidth: 18, height: 18, padding: '0 6px', borderRadius: 99, fontSize: 10.5, fontWeight: 600, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: tone ? `color-mix(in srgb, ${TONE[tone]} 18%, transparent)` : 'var(--hov,#161C28)', color: tone ? TONE[tone] : MUT } }, count),
      mock && h(MockBadge), extra,
      !small && h(RangePicker, { ranges, value: range, onChange: onRange, label: `${title} range` }),
      h(TileMenu, { title, sizes: p.sizes, size, onSize: p.onSize, table: p.table, onTable: p.onTable, href, onHide: p.onHide })),
    h('div', { ref, style: { flex: '1 1 0', minHeight: 0, minWidth: 0, overflowY: 'auto', overflowX: 'hidden', scrollbarWidth: 'thin', scrollbarColor: 'var(--bds,#2A3547) transparent', margin: flush ? '0 -10px -10px' : 0, pointerEvents: editing ? 'none' : 'auto' } },
      h(sizeCtx().Provider, { value: box }, children)));
}

// ---------- the grid ----------
// tiles: [{ key, title, size, sizes, render: () => body, …Tile props }]
export function BentoGrid({ tiles, width, compact = true, editing, order, onOrder }) {
  const React = R(), [dragKey, setDrag] = React.useState(null), [over, setOver] = React.useState(null);
  const rowH = ROW_H[compact ? 'compact' : 'comfortable'], gap = GAP[compact ? 'compact' : 'comfortable'];
  const visible = tiles.map(t => t.key);
  const cells = tiles.map(t => {
    const [c, r] = spanAt(t.size, width);
    const drag = editing ? {
      draggable: true, 'data-over': over === t.key && dragKey !== t.key ? 1 : undefined, 'data-dragging': dragKey === t.key ? 1 : undefined,
      onDragStart: e => { setDrag(t.key); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', t.key); } catch { /* old browsers */ } },
      onDragEnd: () => { setDrag(null); setOver(null); },
      onDragOver: e => { if (!dragKey) return; e.preventDefault(); if (over !== t.key) setOver(t.key); },
      onDrop: e => { e.preventDefault(); const k = dragKey; setDrag(null); setOver(null); if (k && k !== t.key) onOrder(dropBefore(order, k, t.key)); },
    } : undefined;
    const grip = editing ? h('button', { type: 'button', 'aria-label': `Move ${t.title}: arrow keys`, title: 'Drag to move, or use the arrow keys',
      onKeyDown: e => { const dir = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : 0; if (dir) { e.preventDefault(); onOrder(stepKey(order, visible, t.key, dir)); } },
      style: { width: 18, height: 20, padding: 0, border: 0, background: 'transparent', color: MUT, cursor: 'grab', display: 'grid', placeItems: 'center', flex: 'none' } }, h(Icon, { d: PATH.grip, size: 14 })) : null;
    return h(Tile, { ...t, key: t.key, editing, drag, grip, style: { gridColumn: `span ${c}`, gridRow: `span ${r}`, ...(editing ? { borderStyle: 'dashed' } : null) } }, t.render());
  });
  return h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(12,minmax(0,1fr))', gridAutoRows: rowH + 'px', gridAutoFlow: 'row dense', gap, minWidth: 0 } }, cells);
}
