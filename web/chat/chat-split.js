// The Chat page's split view (chat-split plan 2.2–2.3): every pane of the layout tree (chat-layout.js) drawn at its
// box, keyed by its id so a split or a move never remounts a chat; the dividers between them, dragged to resize
// (double click: equal sizes); drop zones over a pane for a chat dragged from the list or a pane dragged by its grip.
// Under 760 px only the active pane is drawn, with a tab per pane.
//
// SplitView({layout, setLayout, renderPane(pane, {active, tools, grip}), titleOf(tid), narrow, maxPanes, onRefuse(msg)})

import { h, T, Icon, Btn } from './chat-ui.js';
import { geometry, panes, splitPane, movePane, setTid, setActive, closePane, resize, equalize, dropZone, paneSize, splitPaneSize } from './chat-layout.js';

const R = () => globalThis.React;
export const CHAT_TYPE = 'application/x-gaifa-chat', PANE_TYPE = 'application/x-gaifa-pane';
export const MIN_W = 320, MIN_H = 240;
const GRIP = 'M9 5h.01M9 12h.01M9 19h.01M15 5h.01M15 12h.01M15 19h.01';
const SPLIT = 'M4 5h16v14H4zM12 5v14';
const ZONE_BOX = { left: { left: 0, top: 0, width: '50%', height: '100%' }, right: { right: 0, top: 0, width: '50%', height: '100%' },
  top: { left: 0, top: 0, width: '100%', height: '50%' }, bottom: { left: 0, bottom: 0, width: '100%', height: '50%' }, center: { inset: 0 } };
const pct = x => `${(x * 100).toFixed(4)}%`;
const ours = e => { const t = [...(e.dataTransfer?.types || [])]; return t.includes(CHAT_TYPE) || t.includes(PANE_TYPE); };

/** What a split of `paneId` at `edge` would break, or null when it fits (the cap, the smallest pane). */
export function splitProblem(L, paneId, edge, box, maxPanes) {
  if (panes(L.root).length >= maxPanes) return `At most ${maxPanes} chats side by side for now`;
  const s = box && splitPaneSize(L, paneId, edge, box.w, box.h);
  if (s && (s.w < MIN_W || s.h < MIN_H)) return 'Not enough room to split that chat';
  return null;
}

export function SplitView({ layout, setLayout, renderPane, titleOf = () => null, narrow = false, maxPanes = Infinity, onRefuse = () => {} }) {
  const React = R(), { useRef, useState, useEffect } = React;
  const boxRef = useRef(null), lref = useRef(layout); lref.current = layout;
  const [zone, setZone] = useState(null);          // {pane, zone} while something of ours is dragged over a pane
  const [dragging, setDragging] = useState(null);  // the divider being dragged
  const g = geometry(layout.root), many = g.panes.length > 1;
  const size = () => { const r = boxRef.current?.getBoundingClientRect(); return r ? { w: r.width, h: r.height } : null; };
  useEffect(() => {                                  // a drag that ends outside every pane leaves no zone behind
    const end = () => setZone(null);
    document.addEventListener('dragend', end); document.addEventListener('drop', end);
    return () => { document.removeEventListener('dragend', end); document.removeEventListener('drop', end); };
  }, []);

  const split = (paneId, edge, tid) => {
    const L = lref.current, problem = splitProblem(L, paneId, edge, size(), maxPanes);
    if (problem) { onRefuse(problem); return; }
    setLayout(splitPane(L, paneId, edge, tid));
  };
  const drop = (e, paneId) => {
    if (!ours(e)) return;
    e.preventDefault(); e.stopPropagation();
    const z = zone?.pane === paneId ? zone.zone : 'center', L = lref.current;
    setZone(null);
    const from = e.dataTransfer.getData(PANE_TYPE), tid = e.dataTransfer.getData(CHAT_TYPE);
    if (from) {
      if (from === paneId) return;
      if (z === 'center') {                          // onto a pane's middle: the two swap chats
        const a = panes(L.root).find(p => p.id === from), b = panes(L.root).find(p => p.id === paneId);
        if (a && b) setLayout(setActive(setTid(setTid(L, a.id, b.tid), b.id, a.tid), b.id));
        return;
      }
      const moved = movePane(L, from, paneId, z), s = size(), p = panes(moved.root).find(x => x.id === moved.active);
      const ps = s && p && paneSize(moved.root, p.id, s.w, s.h);
      if (ps && (ps.w < MIN_W || ps.h < MIN_H)) { onRefuse('Not enough room there'); return; }
      setLayout(moved);
      return;
    }
    if (!tid) return;
    if (z === 'center') setLayout(setActive(setTid(L, paneId, tid), paneId));
    else split(paneId, z, tid);
  };
  const over = (e, paneId) => {
    if (!ours(e)) return;
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = [...e.dataTransfer.types].includes(PANE_TYPE) ? 'move' : 'copy';
    const r = e.currentTarget.getBoundingClientRect(), z = dropZone(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
    if (zone?.pane !== paneId || zone?.zone !== z) setZone({ pane: paneId, zone: z });
  };
  const leave = (e, paneId) => { if (!e.currentTarget.contains(e.relatedTarget) && zone?.pane === paneId) setZone(null); };

  const startResize = (e, d) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget, s = size();
    if (!s) return;
    el.setPointerCapture?.(e.pointerId);
    const row = d.dir === 'row', px = row ? s.w * d.box.w : s.h * d.box.h, start = row ? e.clientX : e.clientY, L0 = lref.current;
    const min = (row ? MIN_W : MIN_H) / px;
    setDragging(d.split + ':' + d.i);
    const move = ev => setLayout(resize(L0, d.split, d.i, ((row ? ev.clientX : ev.clientY) - start) / px, min));
    const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); setDragging(null); };
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
  };

  const toolsFor = p => {
    const s = size(), ps = s && paneSize(layout.root, p.id, s.w, s.h);   // beside when it's wider than tall, else below; whichever fits
    const fits = e => !ps || (e === 'right' ? ps.w / 2 >= MIN_W : ps.h / 2 >= MIN_H), pref = ps && ps.w < ps.h ? 'bottom' : 'right';
    const edge = fits(pref) ? pref : fits(pref === 'right' ? 'bottom' : 'right') ? (pref === 'right' ? 'bottom' : 'right') : pref;
    return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 2, flex: 'none' } },
      h(Btn, { kind: 'ghost', sm: true, icon: SPLIT, title: edge === 'right' ? 'Open a new chat beside this one' : 'Open a new chat below this one', 'aria-label': 'Split', onClick: () => split(p.id, edge, null) }),
      many ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close this pane (the chat stays in the list)', 'aria-label': 'Close pane', onClick: () => setLayout(closePane(lref.current, p.id)) }) : null);
  };
  const gripFor = p => (many && !narrow ? h('span', { draggable: true, title: 'Drag to move this chat to another side', 'aria-label': 'Move pane', role: 'button',
    onDragStart: e => { e.dataTransfer.setData(PANE_TYPE, p.id); e.dataTransfer.effectAllowed = 'move'; },
    style: { display: 'grid', placeItems: 'center', width: 18, height: 26, marginLeft: -6, color: T.dim, cursor: 'grab', flex: 'none' } }, h(Icon, { d: GRIP, size: 14, sw: 3 })) : null);

  const shown = narrow ? g.panes.filter(p => p.id === layout.active) : g.panes;
  return h('div', { style: { flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' } },
    narrow && many ? h('div', { role: 'tablist', 'aria-label': 'Open chats', style: { display: 'flex', gap: 4, padding: '6px 8px', borderBottom: '1px solid ' + T.bd, overflowX: 'auto', flex: 'none' } },
      g.panes.map(p => h('button', { key: p.id, type: 'button', role: 'tab', 'aria-selected': p.id === layout.active, onClick: () => setLayout(setActive(lref.current, p.id)),
        style: { flex: 'none', maxWidth: 180, height: 26, padding: '0 10px', borderRadius: 6, border: '1px solid ' + (p.id === layout.active ? T.bdh : T.bd), background: p.id === layout.active ? T.row : 'transparent',
          color: p.id === layout.active ? T.tx : T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
        (p.tid && titleOf(p.tid)) || (p.tid ? 'Chat' : 'New chat')))) : null,
    h('div', { ref: boxRef, style: { flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden', userSelect: dragging ? 'none' : undefined, cursor: dragging ? (dragging && g.dividers.find(d => d.split + ':' + d.i === dragging)?.dir === 'col' ? 'row-resize' : 'col-resize') : undefined } },
      shown.map(p => {
        const active = p.id === layout.active, z = zone?.pane === p.id ? zone.zone : null, box = narrow ? { x: 0, y: 0, w: 1, h: 1 } : p;
        return h('div', { key: p.id, 'data-pane-id': p.id, onDragOverCapture: e => over(e, p.id), onDropCapture: e => drop(e, p.id), onDragLeave: e => leave(e, p.id),
          style: { position: 'absolute', left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h), display: 'flex', minWidth: 0, minHeight: 0, overflow: 'hidden',
            pointerEvents: dragging ? 'none' : undefined } },
          renderPane(p, { active, tools: toolsFor(p), grip: gripFor(p) }),
          many && active && !narrow ? h('div', { 'aria-hidden': true, style: { position: 'absolute', inset: 0, pointerEvents: 'none', boxShadow: `inset 0 2px 0 ${T.acc}`, zIndex: 30 } }) : null,
          z ? h('div', { 'aria-hidden': true, style: { position: 'absolute', ...ZONE_BOX[z], pointerEvents: 'none', zIndex: 31, background: T.tacc, border: '2px solid ' + T.acc, borderRadius: 6, boxSizing: 'border-box' } }) : null);
      }),
      narrow ? null : g.dividers.map(d => {
        const row = d.dir === 'row', key = d.split + ':' + d.i, on = dragging === key;
        return h('div', { key, role: 'separator', 'aria-orientation': row ? 'vertical' : 'horizontal', title: 'Drag to resize; double-click for equal sizes',
          onPointerDown: e => startResize(e, d), onDoubleClick: () => setLayout(equalize(lref.current, d.split)), className: 'aichat-divider',
          style: { position: 'absolute', zIndex: 32, touchAction: 'none', cursor: row ? 'col-resize' : 'row-resize',
            ...(row ? { left: `calc(${pct(d.at)} - 4px)`, top: pct(d.box.y), width: 8, height: pct(d.box.h) } : { top: `calc(${pct(d.at)} - 4px)`, left: pct(d.box.x), height: 8, width: pct(d.box.w) }) } },
          h('div', { className: on ? 'on' : undefined, style: { position: 'absolute', background: on ? T.acc : T.bd, ...(row ? { left: 3.5, top: 0, bottom: 0, width: 1 } : { top: 3.5, left: 0, right: 0, height: 1 }) } }));
      })));
}

export const SPLIT_CSS = `.aichat-divider:hover>div:not(.on){background:var(--bdh,#3A4A63)!important}`;
