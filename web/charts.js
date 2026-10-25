// GAIFA's chart components (brief §11.6), plain SVG through the page's React:
//   AreaChart, LineChart, BarChart (time or category axis, stacked, up to 2 y-axes),
//   HBarChart, Donut, Sparkline, Heatmap, Treemap, Timeline, KpiTile.
// Every chart sizes itself to its container, shows a crosshair/readout on hover and with the
// arrow keys, toggles series from its legend, has loading/empty/error states (`state`), carries
// role="img" with a summary, and renders as a table when `table` is set ("View as table").
// Written by us (web/PATCHES.md); the shared pieces are in chart-kit.js.

import {
  h, SERIES, TONE, MONO, MUT, BD, fmtValue, fmtNum, fmtTime, fmtStamp, fmtDur, niceTicks, byteTicks, timeTicks,
  linePath, areaPath, stackValues, allNull, maxOf, lastValue, useWidth, useHidden, Frame, Legend, Tooltip, DataTable,
  keyIndex, srOnly,
} from './chart-kit.js';

export { SERIES, TONE, fmtValue, fmtNum, fmtTime, fmtStamp, fmtDur } from './chart-kit.js';

const R = () => globalThis.React;
const axisText = { fontSize: 10, fill: MUT, fontFamily: MONO };

function ticksFor(max, unit) { return unit === 'bytes' ? byteTicks(max) : niceTicks(0, max || 1, 4); }
function short(v, unit) {
  if (unit === 'bytes') return +(v / 1e9).toFixed(v % 1e9 ? 1 : 0) + ' GB';
  if (unit === 'ratio') return Math.round(v * 100) + '%';
  if (unit === 'seconds') return fmtDur(v);
  return fmtNum(v);
}
function summary(label, series, unit, at) {
  const parts = series.map(s => `${s.label} ${fmtValue(at != null ? s.values[at] : lastValue(s.values), s.unit || unit)}`);
  return `${label || 'Chart'}${parts.length ? ': latest ' + parts.join(', ') : ''}`;
}

// ---------- time / category chart ----------
// series: [{ key, label, values, color?, type?: 'area'|'line'|'bar', axis?: 'left'|'right', dash?, unit? }]
function XYChart(p) {
  const { t, categories, series = [], type = 'line', stacked = false, unit, unitRight, height = 150, label, table, state, error, onRetry, yMax, onBrush, onPick, brush } = p;
  const React = R(), [ref, width] = useWidth(), [hidden, toggle] = useHidden();
  const [idx, setIdx] = React.useState(null), drag = React.useRef(null), [sel, setSel] = React.useState(null);
  const xs0 = t || categories || [], n = xs0.length;
  const all = series.map((s, i) => ({ ...s, key: s.key || s.label, color: s.color || SERIES[i % SERIES.length], type: s.type || type, axis: s.axis || 'left' }));
  if (state && state !== 'ok') return h('div', { ref }, h(Frame, { state, height, error, onRetry }));
  if (!n || allNull(all.map(s => s.values))) return h('div', { ref }, h(Frame, { state: 'empty', height }));
  if (table) {
    const cols = [t ? 'Time' : '', ...all.map(s => s.label)], step = t && n > 1 ? t[1] - t[0] : 0;
    const rows = xs0.map((x, i) => [t ? fmtStamp(x, step) : String(x), ...all.map(s => fmtValue(s.values[i], s.unit || (s.axis === 'right' ? unitRight : unit)))]).reverse();
    return h(DataTable, { caption: label, columns: cols, rows });
  }
  const vis = all.filter(s => !hidden.has(s.key));
  const stackable = stacked ? vis.filter(s => s.type !== 'line' && s.axis === 'left') : [];
  const stacks = stackValues(stackable.map(s => s.values));
  const left = vis.filter(s => s.axis === 'left' && !stackable.includes(s)), right = vis.filter(s => s.axis === 'right');
  const maxL = yMax || Math.max(maxOf(stacks.map(x => x.top)), maxOf(left.map(s => s.values))), maxR = maxOf(right.map(s => s.values));
  const tL = ticksFor(maxL, unit), tR = right.length ? ticksFor(maxR, unitRight) : null;
  const topL = tL[tL.length - 1] || 1, topR = tR ? tR[tR.length - 1] || 1 : 1;
  const padL = 44, padR = tR ? 44 : 8, padT = 6, padB = 18, W = Math.max(40, width - padL - padR), H = Math.max(30, height - padT - padB);
  const bars = vis.some(s => s.type === 'bar'), bw = W / n;
  const xi = i => padL + (bars ? (i + 0.5) * bw : n === 1 ? W / 2 : i * W / (n - 1));
  const yl = v => padT + H - (v / topL) * H, yr = v => padT + H - (v / topR) * H;
  const xs = xs0.map((_, i) => xi(i));
  const els = [];
  // grid + y labels
  tL.forEach((v, i) => { const y = yl(v); els.push(h('line', { key: 'g' + i, x1: padL, x2: padL + W, y1: y, y2: y, stroke: BD, strokeWidth: 1 }), h('text', { key: 'gl' + i, x: padL - 6, y: y + 3, textAnchor: 'end', style: axisText }, short(v, unit))); });
  if (tR) tR.forEach((v, i) => els.push(h('text', { key: 'gr' + i, x: padL + W + 6, y: yr(v) + 3, style: axisText }, short(v, unitRight))));
  // x labels
  if (t) {
    const span = t[n - 1] - t[0], step = n > 1 ? t[1] - t[0] : 0;
    timeTicks(t[0], t[n - 1] + (bars ? step : 0), Math.max(2, Math.floor(W / 80))).forEach((ts, i) => {
      const x = padL + (span + (bars ? step : 0) > 0 ? (ts - t[0]) / (span + (bars ? step : 0)) * W : W / 2);
      els.push(h('text', { key: 'x' + i, x, y: height - 4, textAnchor: 'middle', style: axisText }, fmtTime(ts, span)));
    });
  } else {
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(W / 56))));
    xs0.forEach((c, i) => { if (i % every === 0) els.push(h('text', { key: 'x' + i, x: xi(i), y: height - 4, textAnchor: 'middle', style: axisText }, String(c))); });
  }
  // stacked areas/bars
  stackable.forEach((s, k) => {
    const st = stacks[k];
    if (s.type === 'bar') st.top.forEach((v, i) => { if (v == null || v === st.lo[i]) return; els.push(h('rect', { key: `b${k}-${i}`, x: xi(i) - bw * 0.38, width: Math.max(1, bw * 0.76), y: yl(v), height: Math.max(0, yl(st.lo[i]) - yl(v)), fill: s.color })); });
    else els.push(h('path', { key: 'a' + k, d: areaPath(xs, st.lo.map(yl), st.top.map(v => (v == null ? null : yl(v)))), fill: s.color, fillOpacity: 0.55, stroke: s.color, strokeWidth: 1 }));
  });
  // plain series
  const plainBars = [...left, ...right].filter(s => s.type === 'bar'), gw = bw * 0.76 / Math.max(1, plainBars.length);
  [...left, ...right].forEach((s, k) => {
    const y = s.axis === 'right' ? yr : yl, ys = s.values.map(v => (v == null ? null : y(v)));
    if (s.type === 'bar') { const j = plainBars.indexOf(s); s.values.forEach((v, i) => { if (v == null || !v) return; els.push(h('rect', { key: `p${k}-${i}`, x: xi(i) - bw * 0.38 + j * gw, width: Math.max(1, gw - 1), y: y(v), height: Math.max(0, padT + H - y(v)), fill: s.color })); }); }
    else if (s.type === 'area') els.push(h('path', { key: 'pa' + k, d: areaPath(xs, xs.map(() => padT + H), ys), fill: s.color, fillOpacity: 0.25, stroke: 'none' }), h('path', { key: 'pl' + k, d: linePath(xs, ys), fill: 'none', stroke: s.color, strokeWidth: 1.5 }));
    else els.push(h('path', { key: 'pl' + k, d: linePath(xs, ys), fill: 'none', stroke: s.color, strokeWidth: 1.5, strokeDasharray: s.dash ? '4 3' : undefined }));
  });
  // brush selection
  const brushSel = sel || brush;
  if (brushSel) { const [a, b] = [Math.min(...brushSel), Math.max(...brushSel)]; els.push(h('rect', { key: 'sel', x: xi(a) - bw / 2, width: xi(b) - xi(a) + bw, y: padT, height: H, fill: 'var(--cy,#58C4DD)', fillOpacity: 0.15, stroke: 'var(--cy,#58C4DD)', strokeOpacity: 0.5 })); }
  if (idx != null) els.push(h('line', { key: 'cross', x1: xi(idx), x2: xi(idx), y1: padT, y2: padT + H, stroke: 'var(--bdh,#3A4A63)', strokeWidth: 1 }));
  const at = e => { const r = e.currentTarget.getBoundingClientRect(), x = e.clientX - r.left; const i = bars ? Math.floor((x - padL) / bw) : Math.round((x - padL) / (W / Math.max(1, n - 1))); return Math.max(0, Math.min(n - 1, i)); };
  const onMove = e => { const i = at(e); setIdx(i); if (drag.current != null) setSel([drag.current, i]); };
  const onDown = onBrush ? e => { const i = at(e); drag.current = i; setSel([i, i]); e.currentTarget.setPointerCapture?.(e.pointerId); } : undefined;
  const onUp = onBrush ? e => { if (drag.current == null) return; const a = drag.current, b = at(e); drag.current = null; setSel(null); onBrush(Math.min(a, b), Math.max(a, b)); } : undefined;
  const step = t && n > 1 ? t[1] - t[0] : 0;
  const tip = idx == null ? null : { title: t ? fmtStamp(t[idx], step) : String(categories[idx]), rows: vis.map(s => ({ color: s.color, label: s.label, value: fmtValue(s.values[idx], s.unit || (s.axis === 'right' ? unitRight : unit)) })) };
  const legend = all.map(s => ({ key: s.key, label: s.label, color: s.color, line: s.type === 'line' }));
  return h('div', { ref, style: { position: 'relative', minWidth: 0 } },
    h('div', { role: 'img', tabIndex: 0, 'aria-label': summary(label, vis, unit), onKeyDown: e => keyIndex(e, idx, n, setIdx), onBlur: () => setIdx(null), style: { outlineOffset: 2, borderRadius: 4 } },
      h('svg', { width, height, style: { display: 'block', touchAction: onBrush ? 'none' : 'auto', cursor: onBrush ? 'crosshair' : 'default' }, onPointerMove: onMove, onPointerLeave: () => drag.current == null && setIdx(null), onPointerDown: onDown, onPointerUp: onUp,
        onClick: onPick && !onBrush ? e => onPick(at(e)) : undefined }, els)),
    tip && h(Tooltip, { x: xi(idx), width, title: tip.title, rows: tip.rows }),
    h('div', { 'aria-live': 'polite', style: srOnly }, tip ? tip.title + ': ' + tip.rows.map(r => r.label + ' ' + r.value).join(', ') : ''),
    h(Legend, { items: legend, hidden, onToggle: toggle }));
}
export const AreaChart = p => h(XYChart, { type: 'area', ...p });
export const LineChart = p => h(XYChart, { type: 'line', ...p });
export const BarChart = p => (p.horizontal ? h(HBarChart, p) : h(XYChart, { type: 'bar', ...p }));

// ---------- horizontal bars (stacked or grouped) ----------
// categories: [label], series: [{ key, label, values, color }]
export function HBarChart({ categories = [], series = [], stacked, unit, label, table, state, error, onRetry, onPick, height }) {
  const React = R(), [ref, width] = useWidth(), [hidden, toggle] = useHidden(), [idx, setIdx] = React.useState(null);
  const all = series.map((s, i) => ({ ...s, key: s.key || s.label, color: s.color || SERIES[i % SERIES.length] }));
  if (state && state !== 'ok') return h('div', { ref }, h(Frame, { state, height: height || 120, error, onRetry }));
  if (!categories.length || allNull(all.map(s => s.values))) return h('div', { ref }, h(Frame, { state: 'empty', height: height || 120 }));
  if (table) return h(DataTable, { caption: label, columns: ['', ...all.map(s => s.label)], rows: categories.map((c, i) => [c, ...all.map(s => fmtValue(s.values[i], unit))]) });
  const vis = all.filter(s => !hidden.has(s.key)), labW = Math.min(130, Math.max(70, width * 0.3)), valW = 64, W = Math.max(30, width - labW - valW - 8);
  const totals = categories.map((_, i) => vis.reduce((a, s) => a + (s.values[i] || 0), 0));
  const max = stacked ? Math.max(...totals, 0) : maxOf(vis.map(s => s.values)), rowH = stacked || vis.length < 2 ? 20 : 8 + vis.length * 7;
  const rows = categories.map((c, i) => {
    let x = 0;
    const segs = vis.map((s, k) => { const v = s.values[i] || 0, w = max ? v / max * W : 0, el = h('rect', { key: k, x: labW + (stacked ? x : 0), y: stacked || vis.length < 2 ? 4 : 4 + k * 7, width: Math.max(v ? 1 : 0, w), height: stacked || vis.length < 2 ? 12 : 6, rx: 2, fill: s.color }); if (stacked) x += w; return el; });
    return h('g', { key: i, transform: `translate(0 ${i * rowH})`, onPointerEnter: () => setIdx(i), onClick: onPick ? () => onPick(i) : undefined, style: { cursor: onPick ? 'pointer' : 'default' } },
      h('rect', { x: 0, y: 0, width, height: rowH, fill: idx === i ? 'var(--hov,#161C28)' : 'transparent' }),
      h('text', { x: 4, y: rowH / 2 + 4, style: { fontSize: 11, fill: 'var(--tx,#E6EAF2)' } }, c.length > 18 ? c.slice(0, 17) + '…' : c), segs,
      h('text', { x: width - 4, y: rowH / 2 + 4, textAnchor: 'end', style: axisText }, fmtValue(stacked ? totals[i] : vis[0]?.values[i], unit)));
  });
  const tip = idx == null ? null : { title: categories[idx], rows: vis.map(s => ({ color: s.color, label: s.label, value: fmtValue(s.values[idx], unit) })) };
  return h('div', { ref, style: { position: 'relative' } },
    h('div', { role: 'img', tabIndex: 0, 'aria-label': `${label || 'Bar chart'}: ` + categories.slice(0, 6).map((c, i) => `${c} ${fmtValue(stacked ? totals[i] : vis[0]?.values[i], unit)}`).join(', '), onKeyDown: e => keyIndex({ ...e, key: { ArrowDown: 'ArrowRight', ArrowUp: 'ArrowLeft' }[e.key] || e.key, preventDefault: () => e.preventDefault() }, idx, categories.length, setIdx), onBlur: () => setIdx(null) },
      h('svg', { width, height: categories.length * rowH, style: { display: 'block' }, onPointerLeave: () => setIdx(null) }, rows)),
    tip && vis.length > 1 && h(Tooltip, { x: labW + W / 2, y: (idx + 1) * rowH, width, title: tip.title, rows: tip.rows }),
    h(Legend, { items: all.map(s => ({ key: s.key, label: s.label, color: s.color })), hidden, onToggle: toggle }));
}

// ---------- donut ----------
// items: [{ key, label, value, color }]
export function Donut({ items = [], unit, center, sub, label, table, state, error, onRetry, size = 132 }) {
  const React = R(), [hidden, toggle] = useHidden(), [idx, setIdx] = React.useState(null);
  const all = items.map((s, i) => ({ ...s, key: s.key || s.label, color: s.color || SERIES[i % SERIES.length] }));
  if (state && state !== 'ok') return h(Frame, { state, height: size, error, onRetry });
  const vis = all.filter(s => !hidden.has(s.key) && s.value > 0), tot = vis.reduce((a, s) => a + s.value, 0);
  if (!all.some(s => s.value > 0)) return h(Frame, { state: 'empty', height: size });
  if (table) return h(DataTable, { caption: label, columns: ['', 'Value', 'Share'], rows: all.map(s => [s.label, fmtValue(s.value, unit), tot ? Math.round(s.value / tot * 100) + '%' : '—']) });
  const r = size / 2, ri = r * 0.62, arcs = [];
  let a0 = -Math.PI / 2;
  vis.forEach((s, i) => {
    const a1 = a0 + (s.value / tot) * Math.PI * 2 - (vis.length > 1 ? 0.012 : 0), big = a1 - a0 > Math.PI ? 1 : 0, ex = idx === i ? 3 : 0;
    const P = (rad, a) => [r + Math.cos(a) * (rad + ex), r + Math.sin(a) * (rad + ex)];
    const d = vis.length === 1 ? `M${r} ${r - r}A${r} ${r} 0 1 1 ${r - 0.01} 0ZM${r} ${r - ri}A${ri} ${ri} 0 1 0 ${r + 0.01} ${r - ri}Z`
      : `M${P(r, a0)}A${r + ex} ${r + ex} 0 ${big} 1 ${P(r, a1)}L${P(ri, a1)}A${ri + ex} ${ri + ex} 0 ${big} 0 ${P(ri, a0)}Z`;
    arcs.push(h('path', { key: s.key, d, fill: s.color, fillRule: 'evenodd', onPointerEnter: () => setIdx(i), onPointerLeave: () => setIdx(null) }));
    a0 = a1 + (vis.length > 1 ? 0.012 : 0);
  });
  const cur = idx != null ? vis[idx] : null;
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', minWidth: 0 } },
    h('div', { role: 'img', tabIndex: 0, 'aria-label': `${label || 'Donut'}: ` + vis.map(s => `${s.label} ${fmtValue(s.value, unit)}`).join(', '), onKeyDown: e => keyIndex(e, idx, vis.length, setIdx), onBlur: () => setIdx(null), style: { position: 'relative', width: size, height: size, flex: 'none' } },
      h('svg', { width: size + 6, height: size + 6, viewBox: `-3 -3 ${size + 6} ${size + 6}`, style: { display: 'block', margin: -3 } }, arcs),
      h('div', { style: { position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', textAlign: 'center' } },
        h('span', { style: { fontFamily: MONO, fontSize: 14, fontWeight: 600 } }, cur ? fmtValue(cur.value, unit) : center),
        h('span', { style: { fontSize: 10.5, color: MUT, maxWidth: ri * 1.7, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, cur ? cur.label : sub))),
    h('div', { style: { flex: '1 1 120px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 } }, all.map(s => {
      const off = hidden.has(s.key);
      return h('button', { key: s.key, type: 'button', 'aria-pressed': !off, onClick: () => toggle(s.key), style: { display: 'flex', alignItems: 'center', gap: 6, border: 0, background: 'none', padding: 0, cursor: 'pointer', fontSize: 11.5, color: off ? 'var(--dim,#737D90)' : MUT, textDecoration: off ? 'line-through' : 'none', minWidth: 0 } },
        h('span', { style: { width: 9, height: 9, borderRadius: 2, background: off ? 'transparent' : s.color, border: off ? '1px solid var(--bds,#2A3547)' : 0, flex: 'none' } }),
        h('span', { style: { flex: 1, minWidth: 0, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.label),
        h('span', { style: { fontFamily: MONO, fontSize: 11, color: 'var(--tx,#E6EAF2)' } }, fmtValue(s.value, unit)));
    })));
}

// ---------- sparkline ----------
export function Sparkline({ values = [], color = SERIES[0], width, height = 22, label, unit, area = true }) {
  const [ref, w0] = useWidth(width || 80), w = width || w0;
  const vals = values.filter(v => v != null);
  const box = { display: 'block', width: width || '100%', height, minWidth: 0 };
  if (!vals.length) return h('span', { ref, role: 'img', 'aria-label': `${label || 'Trend'}: no data`, style: { ...box, borderBottom: '1px dashed var(--bds,#2A3547)', height: height / 2 } });
  const lo = Math.min(0, ...vals), hi = Math.max(...vals), n = values.length, span = hi - lo || 1;
  const xs = values.map((_, i) => (n === 1 ? w / 2 : 1 + i * (w - 2) / (n - 1))), ys = values.map(v => (v == null ? null : 2 + (height - 4) * (1 - (v - lo) / span)));
  const last = lastValue(values);
  return h('span', { ref, role: 'img', 'aria-label': `${label || 'Trend'}: ${fmtValue(Math.min(...vals), unit)} to ${fmtValue(hi, unit)}, now ${fmtValue(last, unit)}`, title: `${label ? label + ': ' : ''}now ${fmtValue(last, unit)} · max ${fmtValue(hi, unit)}`, style: box },
    h('svg', { width: w, height, style: { display: 'block', overflow: 'visible' }, 'aria-hidden': true },
      area && h('path', { d: areaPath(xs, xs.map(() => height), ys), fill: color, fillOpacity: 0.16 }),
      h('path', { d: linePath(xs, ys), fill: 'none', stroke: color, strokeWidth: 1.4, strokeLinejoin: 'round' })));
}

// ---------- heatmap ----------
// rows: [{ label, cells: [{ v, err, tip }] }], cols: [label] (shown sparsely)
export function Heatmap({ rows = [], cols = [], label, table, state, error, onRetry, height }) {
  const React = R(), [ref, width] = useWidth(), [cur, setCur] = React.useState(null);
  if (state && state !== 'ok') return h('div', { ref }, h(Frame, { state, height: height || 160, error, onRetry }));
  const max = Math.max(0, ...rows.flatMap(r => r.cells.map(c => c.v || 0)));
  if (!rows.length || !max) return h('div', { ref }, h(Frame, { state: 'empty', height: height || 160 }));
  if (table) return h(DataTable, { caption: label, columns: ['', ...cols], rows: rows.map(r => [r.label, ...r.cells.map(c => (c.v ? String(c.v) + (c.err ? ` (${c.err} err)` : '') : ''))]) });
  const labW = 46, nC = cols.length, cw = Math.max(4, (width - labW) / nC), ch = Math.max(8, Math.min(16, (height || 9999) / (rows.length + 1), cw)), els = [];
  rows.forEach((r, j) => {
    els.push(h('text', { key: 'l' + j, x: labW - 6, y: j * ch + ch * 0.75, textAnchor: 'end', style: axisText }, r.label));
    r.cells.forEach((c, i) => {
      const k = c.v ? 0.18 + 0.82 * (c.v / max) : 0, on = cur && cur[0] === j && cur[1] === i;
      els.push(h('rect', { key: j + '-' + i, x: labW + i * cw + 0.5, y: j * ch + 0.5, width: cw - 1, height: ch - 1, rx: 2, fill: c.err ? 'var(--rd,#F85149)' : c.v ? 'var(--cy,#58C4DD)' : 'var(--row,#1A2130)', fillOpacity: c.err ? Math.max(0.35, k) : c.v ? k : 1, stroke: on ? 'var(--tx,#E6EAF2)' : 'none', onPointerEnter: () => setCur([j, i]) }));
    });
  });
  const every = Math.ceil(nC / Math.max(2, Math.floor((width - labW) / 34)));
  cols.forEach((c, i) => { if (i % every === 0) els.push(h('text', { key: 'c' + i, x: labW + i * cw + cw / 2, y: rows.length * ch + 11, textAnchor: 'middle', style: axisText }, c)); });
  const cell = cur ? rows[cur[0]].cells[cur[1]] : null;
  const onKey = e => {
    const [j, i] = cur || [rows.length - 1, nC - 1], mv = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[e.key];
    if (mv) { e.preventDefault(); setCur([Math.max(0, Math.min(rows.length - 1, j + mv[0])), Math.max(0, Math.min(nC - 1, i + mv[1]))]); } else if (e.key === 'Escape') setCur(null);
  };
  return h('div', { ref, style: { position: 'relative' } },
    h('div', { role: 'img', tabIndex: 0, 'aria-label': `${label || 'Heatmap'}: busiest ${max} per cell`, onKeyDown: onKey, onBlur: () => setCur(null) },
      h('svg', { width, height: rows.length * ch + 14, style: { display: 'block' }, onPointerLeave: () => setCur(null) }, els)),
    cell && h(Tooltip, { x: labW + cur[1] * cw, y: (cur[0] + 1) * ch + 2, width, title: cell.tip, rows: [{ label: 'Events', value: String(cell.v || 0) }, ...(cell.err ? [{ color: 'var(--rd,#F85149)', label: 'Errors', value: String(cell.err) }] : [])] }),
    h('div', { 'aria-live': 'polite', style: srOnly }, cell ? `${cell.tip}: ${cell.v || 0} events, ${cell.err || 0} errors` : ''));
}

// ---------- treemap (squarified) ----------
export function squarify(items, x, y, w, h0) {
  const out = [], list = items.filter(i => i.value > 0).sort((a, b) => b.value - a.value);
  const total = list.reduce((a, i) => a + i.value, 0);
  if (!total) return out;
  const scale = (w * h0) / total;
  let rest = list.map(i => ({ ...i, area: i.value * scale })), X = x, Y = y, W = w, H = h0;
  const worst = (row, side) => { const s = row.reduce((a, r) => a + r.area, 0), mx = Math.max(...row.map(r => r.area)), mn = Math.min(...row.map(r => r.area)); return Math.max(side * side * mx / (s * s), (s * s) / (side * side * mn)); };
  while (rest.length) {
    const side = Math.min(W, H), row = [rest[0]];
    let i = 1;
    while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) row.push(rest[i++]);
    rest = rest.slice(i);
    const s = row.reduce((a, r) => a + r.area, 0), thick = s / side;
    let off = 0;
    row.forEach(r => { const len = r.area / thick; out.push(W >= H ? { ...r, x: X, y: Y + off, w: thick, h: len } : { ...r, x: X + off, y: Y, w: len, h: thick }); off += len; });
    if (W >= H) { X += thick; W -= thick; } else { Y += thick; H -= thick; }
  }
  return out;
}
export function Treemap({ items = [], unit = 'bytes', height = 130, label, table, state, error, onRetry, onPick }) {
  const React = R(), [ref, width] = useWidth(), [idx, setIdx] = React.useState(null);
  const all = items.map((s, i) => ({ ...s, key: s.key || s.label, color: s.color || SERIES[i % SERIES.length] }));
  if (state && state !== 'ok') return h('div', { ref }, h(Frame, { state, height, error, onRetry }));
  if (!all.some(s => s.value > 0)) return h('div', { ref }, h(Frame, { state: 'empty', height }));
  const tot = all.reduce((a, s) => a + (s.value || 0), 0);
  if (table) return h(DataTable, { caption: label, columns: ['', 'Size', 'Share'], rows: all.map(s => [s.label, fmtValue(s.value, unit), Math.round(s.value / tot * 100) + '%']) });
  const rects = squarify(all, 0, 0, width, height);
  const cur = idx != null ? rects[idx] : null;
  return h('div', { ref, style: { position: 'relative' } },
    h('div', { role: 'img', tabIndex: 0, 'aria-label': `${label || 'Treemap'}: ` + rects.map(r => `${r.label} ${fmtValue(r.value, unit)}`).join(', '), onKeyDown: e => keyIndex(e, idx, rects.length, setIdx), onBlur: () => setIdx(null) },
      h('svg', { width, height, style: { display: 'block' }, onPointerLeave: () => setIdx(null) }, rects.map((r, i) => h('g', { key: r.key, onPointerEnter: () => setIdx(i), onClick: onPick ? () => onPick(r) : undefined, style: { cursor: onPick ? 'pointer' : 'default' } },
        h('rect', { x: r.x + 1, y: r.y + 1, width: Math.max(0, r.w - 2), height: Math.max(0, r.h - 2), rx: 4, fill: r.color, fillOpacity: idx === i ? 0.95 : 0.75 }),
        r.w > 54 && r.h > 30 && h('text', { x: r.x + 7, y: r.y + 16, style: { fontSize: 11, fontWeight: 600, fill: '#0B0E14' } }, r.label),
        r.w > 54 && r.h > 44 && h('text', { x: r.x + 7, y: r.y + 30, style: { fontSize: 10.5, fill: '#0B0E14', fontFamily: MONO } }, fmtValue(r.value, unit)))))),
    cur && h(Tooltip, { x: cur.x + cur.w / 2, y: Math.min(height - 40, cur.y + cur.h / 2), width, title: cur.label, rows: [{ color: cur.color, label: 'Size', value: fmtValue(cur.value, unit) }, { label: 'Share', value: Math.round(cur.value / tot * 100) + '%' }] }));
}

// ---------- timeline (swimlanes) ----------
export const STATE_COLOR = { stopped: 'transparent', starting: 'var(--acc,#FFB224)', ready: 'var(--gr,#3FB950)', degraded: 'var(--acc,#FFB224)', stopping: 'var(--mut,#8A94A6)', failed: 'var(--rd,#F85149)' };
const JOB_COLOR = { done: 'var(--acc,#FFB224)', running: 'var(--s8,#E3B341)', queued: 'var(--mut,#8A94A6)', failed: 'var(--rd,#F85149)', cancelled: 'var(--mut,#8A94A6)' };
// lanes: [{ key, label, href?, states, loaded, jobs, outputs, events }] (brief §11.7 Timeline)
export function Timeline({ from, to, lanes = [], label, table, state, error, onRetry, onOpen, laneH = 30, minWidth = 560, labelW = 110 }) {
  const React = R(), [ref, w0] = useWidth(), [tip, setTip] = React.useState(null);
  const width = Math.max(minWidth, w0);
  if (state && state !== 'ok') return h('div', { ref }, h(Frame, { state, height: Math.max(80, lanes.length * laneH || 120), error, onRetry }));
  if (!lanes.length) return h('div', { ref }, h(Frame, { state: 'empty', height: 100, emptyText: 'No services' }));
  const empty = lanes.every(l => !l.states.length && !l.loaded.length && !l.jobs.length && !l.outputs.length && !l.events.length);
  if (table) {
    const rows = [];
    lanes.forEach(l => {
      l.states.forEach(s => rows.push([l.label, 'state', s.state, fmtStamp(s.from), fmtDur(s.to - s.from)]));
      l.loaded.forEach(s => rows.push([l.label, 'loaded', '', fmtStamp(s.from), fmtDur(s.to - s.from)]));
      l.jobs.forEach(j => rows.push([l.label, 'job', `${j.label} (${j.state})`, fmtStamp(j.from), j.to ? fmtDur(j.to - j.from) : 'running']));
      l.outputs.forEach(o => rows.push([l.label, 'output', o.kind, fmtStamp(o.ts), '']));
      l.events.forEach(e => rows.push([l.label, e.level, e.text, fmtStamp(e.ts), '']));
    });
    return h(DataTable, { caption: label, columns: ['Service', 'What', 'Detail', 'From', 'For'], rows, maxHeight: 340 });
  }
  const W = width - labelW - 8, span = Math.max(1, to - from), X = ts => labelW + Math.max(0, Math.min(1, (ts - from) / span)) * W;
  const els = [], axisY = lanes.length * laneH;
  timeTicks(from, to, Math.max(2, Math.floor(W / 90))).forEach((ts, i) => els.push(
    h('line', { key: 'tg' + i, x1: X(ts), x2: X(ts), y1: 0, y2: axisY, stroke: BD }),
    h('text', { key: 'tl' + i, x: X(ts), y: axisY + 12, textAnchor: 'middle', style: axisText }, fmtTime(ts, span))));
  const show = (e, title, rows) => setTip({ cx: e.clientX - ref.current.getBoundingClientRect().left + ref.current.scrollLeft, title, rows });
  lanes.forEach((l, j) => {
    const y = j * laneH, mid = y + laneH / 2;
    els.push(h('rect', { key: 'bg' + j, x: labelW, y: y + 2, width: W, height: laneH - 4, rx: 3, fill: 'var(--row,#1A2130)', fillOpacity: 0.5 }));
    els.push(h('a', { key: 'lb' + j, href: l.href || undefined }, h('text', { x: 4, y: mid + 4, style: { fontSize: 11.5, fill: 'var(--tx,#E6EAF2)' } }, l.label.length > 15 ? l.label.slice(0, 14) + '…' : l.label)));
    l.states.forEach((s, i) => { if (s.state === 'stopped') return; els.push(h('rect', { key: `s${j}-${i}`, x: X(s.from), y: y + 3, width: Math.max(1, X(s.to) - X(s.from)), height: laneH - 6, fill: STATE_COLOR[s.state] || MUT, fillOpacity: s.state === 'ready' ? 0.16 : 0.45, onPointerEnter: e => show(e, l.label, [{ color: STATE_COLOR[s.state], label: s.state, value: fmtDur(s.to - s.from) }, { label: fmtStamp(s.from) + ' →', value: '' }]) })); });
    l.loaded.forEach((s, i) => els.push(h('rect', { key: `l${j}-${i}`, x: X(s.from), y: y + 4, width: Math.max(1, X(s.to) - X(s.from)), height: 4, rx: 1, fill: 'var(--cy,#58C4DD)', onPointerEnter: e => show(e, l.label, [{ color: 'var(--cy,#58C4DD)', label: 'Model loaded', value: fmtDur(s.to - s.from) }, { label: fmtStamp(s.from) + ' →', value: '' }]) })));
    l.jobs.forEach((jb, i) => { const x1 = X(jb.from), x2 = X(jb.to ?? to); els.push(h('rect', { key: `j${j}-${i}`, x: x1, y: mid - 3, width: Math.max(2, x2 - x1), height: 8, rx: 2, fill: JOB_COLOR[jb.state] || MUT, style: { cursor: 'pointer' }, onClick: () => onOpen?.('job', jb, l), onPointerEnter: e => show(e, jb.label, [{ color: JOB_COLOR[jb.state], label: jb.state, value: jb.to ? fmtDur(jb.to - jb.from) : 'running' }, { label: l.label, value: fmtStamp(jb.from) }]) })); });
    l.outputs.forEach((o, i) => els.push(h('circle', { key: `o${j}-${i}`, cx: X(o.ts), cy: y + laneH - 7, r: 2.6, fill: 'var(--pu,#BC8CFF)', style: { cursor: 'pointer' }, onClick: () => onOpen?.('output', o, l), onPointerEnter: e => show(e, l.label, [{ color: 'var(--pu,#BC8CFF)', label: o.kind + ' output', value: '' }, { label: fmtStamp(o.ts), value: '' }]) })));
    l.events.forEach((ev, i) => { const x = X(ev.ts), c = ev.level === 'error' ? 'var(--rd,#F85149)' : 'var(--acc,#FFB224)'; els.push(h('path', { key: `e${j}-${i}`, d: `M${x} ${y + 3}l4 7h-8z`, fill: c, style: { cursor: 'pointer' }, onClick: () => onOpen?.('event', ev, l), onPointerEnter: e => show(e, l.label, [{ color: c, label: ev.text, value: '' }, { label: fmtStamp(ev.ts), value: '' }]) })); });
  });
  const summaryText = `${label || 'Timeline'}: ` + lanes.map(l => `${l.label} ${l.states.filter(s => s.state === 'ready').length} ready periods, ${l.jobs.length} jobs, ${l.outputs.length} outputs`).join('; ');
  return h('div', { ref, style: { position: 'relative', overflowX: 'auto', overflowY: 'hidden' }, onPointerLeave: () => setTip(null) },
    h('div', { role: 'img', 'aria-label': summaryText, style: { width } },
      h('svg', { width, height: axisY + 16, style: { display: 'block' } }, els)),
    empty && h('div', { style: { position: 'absolute', left: labelW, right: 0, top: 0, bottom: 16, display: 'grid', placeItems: 'center', fontSize: 12, color: MUT, pointerEvents: 'none' } }, 'No history in this range'),
    tip && h(Tooltip, { x: tip.cx, y: 4, width, title: tip.title, rows: tip.rows }));
}

// ---------- KPI tile ----------
export function KpiTile({ label, value, sub, tone, delta, deltaTone, spark, href, unit, onClick }) {
  const body = [
    h('div', { key: 'l', style: { fontSize: 11, color: MUT, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, label),
    h('div', { key: 'v', style: { display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 } },
      h('span', { style: { fontFamily: MONO, fontSize: 17, fontWeight: 600, color: tone ? TONE[tone] : 'var(--tx,#E6EAF2)', whiteSpace: 'nowrap' } }, value),
      sub && h('span', { style: { fontSize: 11, color: MUT, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, sub),
      delta && h('span', { style: { marginLeft: 'auto', fontFamily: MONO, fontSize: 10.5, color: deltaTone ? TONE[deltaTone] : MUT, whiteSpace: 'nowrap' } }, delta)),
    spark ? h(Sparkline, { key: 's', values: spark.values, color: spark.color || SERIES[0], height: 20, label, unit }) : h('div', { key: 's', style: { height: 20 } }),
  ];
  const st = { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, padding: '8px 10px', borderRadius: 8, background: 'var(--card,#11151D)', border: '1px solid ' + BD, color: 'inherit', textDecoration: 'none' };
  return href ? h('a', { href, onClick, style: st, 'aria-label': `${label}: ${value}${sub ? ' ' + sub : ''}` }, body) : h('div', { style: st }, body);
}
