// Shared pieces of GAIFA's charts (brief §11.6): formatting, scales, the size hook, and the
// frame every chart uses (loading / empty / error, legend, tooltip, "View as table").
// Written by us (revision 2 was built by hand, see web/PATCHES.md). Plain SVG through the page's
// own React (window.React, served from web/vendor/); no chart library, nothing from a CDN.

const R = () => globalThis.React;
export const h = (...a) => R().createElement(...a);

export const SERIES = ['var(--s1,#58C4DD)', 'var(--s2,#FFB224)', 'var(--s3,#BC8CFF)', 'var(--s4,#3FB950)', 'var(--s5,#F78166)', 'var(--s6,#79C0FF)', 'var(--s7,#D2A8FF)', 'var(--s8,#E3B341)'];
export const OTHER = 'var(--other,#46526A)';
export const TONE = { green: 'var(--gr,#3FB950)', accent: 'var(--acc,#FFB224)', cyan: 'var(--cy,#58C4DD)', red: 'var(--rd,#F85149)', purple: 'var(--pu,#BC8CFF)', dim: 'var(--mut,#8A94A6)' };
export const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";
export const MUT = 'var(--mut,#8A94A6)';
export const BD = 'var(--bd,#1D2430)';

// ---------- formatting (matches the rest of the UI: 1000-based bytes, 1h 5m durations) ----------
export function fmtBytes(b, d = 1) {
  if (b == null || isNaN(b)) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0, v = Math.abs(b);
  while (v >= 1000 && i < 4) { v /= 1000; i++; }
  return (b < 0 ? '-' : '') + (i === 0 ? Math.round(v) : v.toFixed(v >= 100 ? 0 : d)) + ' ' + u[i];
}
export function fmtDur(s) {
  if (s == null || isNaN(s)) return '—';
  s = Math.max(0, Math.round(s));
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm' + (s % 60 && s < 600 ? ' ' + (s % 60) + 's' : '');
  if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm';
  return Math.floor(s / 86400) + 'd ' + Math.floor(s % 86400 / 3600) + 'h';
}
export function fmtNum(v) {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e4) return (v / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'k';
  if (Number.isInteger(v)) return v.toLocaleString('en-US');
  return v.toFixed(a >= 100 ? 0 : a >= 10 ? 1 : 2);
}
export function fmtValue(v, unit) {
  if (v == null || isNaN(v)) return '—';
  if (unit === 'bytes') return fmtBytes(v);
  if (unit === 'seconds') return fmtDur(v);
  if (unit === 'ms') return fmtNum(Math.round(v)) + ' ms';
  if (unit === 'ratio') return Math.round(v * 100) + '%';
  return fmtNum(v) + (unit && unit !== 'count' ? ' ' + unit : '');
}
const pad2 = n => String(n).padStart(2, '0');
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
// Axis time in local time: HH:mm under 24 h, ddd HH:mm up to 7 d, MMM d above (brief §11.6).
export function fmtTime(ts, spanS) {
  const d = new Date(ts * 1000), hm = pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  if (spanS < 86400) return hm;
  if (spanS <= 7 * 86400) return DAYS[d.getDay()] + ' ' + hm;
  return MONTHS[d.getMonth()] + ' ' + d.getDate();
}
// The tooltip's heading: always the full local time.
export function fmtStamp(ts, stepS = 0) {
  const d = new Date(ts * 1000), day = MONTHS[d.getMonth()] + ' ' + d.getDate();
  if (stepS >= 86400) return DAYS[d.getDay()] + ' ' + day;
  return DAYS[d.getDay()] + ' ' + day + ', ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + (stepS && stepS < 60 ? ':' + pad2(d.getSeconds()) : '');
}

// ---------- scales ----------
// Round tick values from 0 (or min) up to at least max: 1, 2, 2.5 or 5 × 10^k apart.
export function niceTicks(min, max, n = 4) {
  if (!(max > min)) max = min + 1;
  const raw = (max - min) / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  const lo = Math.floor(min / step) * step, out = [];
  for (let v = lo; v < max + step * 0.999; v += step) out.push(+v.toPrecision(12));
  return out;
}
// Byte axes tick at round GB values.
export function byteTicks(max, n = 4) { return niceTicks(0, Math.max(max, 1e9) / 1e9, n).map(v => v * 1e9); }

const TIME_STEPS = [10, 30, 60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 2 * 86400, 7 * 86400, 14 * 86400];
// Ticks on local-time boundaries (midnight-aligned), about `n` of them.
export function timeTicks(from, to, n = 5) {
  const span = to - from;
  if (!(span > 0)) return [from];
  const step = TIME_STEPS.find(s => span / s <= n) || TIME_STEPS[TIME_STEPS.length - 1];
  const mid = new Date(from * 1000); mid.setHours(0, 0, 0, 0);
  let t = mid.getTime() / 1000;
  if (step >= 7 * 86400) t -= mid.getDay() * 86400;  // weeks start on Sunday
  t += Math.ceil((from - t) / step) * step;
  const out = [];
  for (; t <= to; t += step) out.push(t);
  return out;
}

// ---------- paths ----------
const num = v => (Math.round(v * 10) / 10);
// A line with breaks where y is null (a gap is never bridged).
export function linePath(xs, ys) {
  let d = '', pen = false;
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] == null) { pen = false; continue; }
    d += (pen ? 'L' : 'M') + num(xs[i]) + ' ' + num(ys[i]);
    pen = true;
  }
  return d;
}
// A filled band between y0 and y1, one closed shape per run of non-null y1.
export function areaPath(xs, y0, y1) {
  let d = '', run = [];
  const flush = () => {
    if (!run.length) return;
    d += 'M' + run.map(i => num(xs[i]) + ' ' + num(y1[i])).join('L');
    d += 'L' + run.slice().reverse().map(i => num(xs[i]) + ' ' + num(y0[i])).join('L') + 'Z';
    run = [];
  };
  for (let i = 0; i < xs.length; i++) { if (y1[i] == null) flush(); else run.push(i); }
  flush();
  return d;
}
// Cumulative tops for a stack: tops[k][i] = sum of values[0..k][i]; null stays null (a gap).
export function stackValues(list) {
  const n = list[0]?.length || 0, base = new Array(n).fill(0), out = [];
  for (const vals of list) {
    const lo = base.slice(), top = vals.map((v, i) => (v == null ? null : (base[i] += v)));
    out.push({ lo, top });
  }
  return out;
}
export const allNull = arrs => arrs.every(a => !a || a.every(v => v == null));
export const maxOf = arrs => arrs.reduce((m, a) => a.reduce((x, v) => (v != null && v > x ? v : x), m), 0);
export function lastValue(vals) { for (let i = vals.length - 1; i >= 0; i--) if (vals[i] != null) return vals[i]; return null; }

// ---------- hooks ----------
// The container's width (ResizeObserver), so charts size themselves.
export function useWidth(initial = 320) {
  const { useState, useRef, useLayoutEffect } = R();
  const ref = useRef(null), [w, setW] = useState(initial);
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return undefined;
    const set = x => { x = Math.floor(x); if (x > 0) setW(p => (p === x ? p : x)); };
    set(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(es => set(es[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
// Hidden legend items.
export function useHidden() {
  const [hidden, set] = R().useState(() => new Set());
  return [hidden, k => set(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; })];
}

// ---------- frame ----------
const shimmer = { background: 'linear-gradient(90deg,var(--inset,#131926) 0,var(--hov,#161C28) 50%,var(--inset,#131926) 100%)', backgroundSize: '960px 100%', animation: 'hubshimmer 1.4s linear infinite', borderRadius: 6 };
// Loading (skeleton), empty ("No data in this range") and error (with retry) for any chart.
export function Frame({ state, height = 140, error, onRetry, emptyText }) {
  const box = { height, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, fontSize: 12, color: MUT, textAlign: 'center', padding: 8 };
  if (state === 'loading') return h('div', { 'aria-busy': true, 'aria-label': 'Loading chart', style: { ...shimmer, height } });
  if (state === 'error') return h('div', { role: 'alert', style: box },
    h('span', { style: { color: TONE.red } }, error || 'Couldn’t load this chart'),
    onRetry && h('button', { onClick: onRetry, style: btnSt }, 'Retry'));
  return h('div', { style: box }, emptyText || 'No data in this range');
}
export const btnSt = { height: 26, padding: '0 10px', borderRadius: 6, border: '1px solid var(--bds,#2A3547)', background: 'var(--inset,#131926)', color: 'var(--tx,#E6EAF2)', fontSize: 12, cursor: 'pointer' };

export function Legend({ items, hidden, onToggle }) {
  if (!items || items.length < 2) return null;
  return h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '2px 10px', marginTop: 4 } }, items.map(it => {
    const off = hidden?.has(it.key);
    return h('button', { key: it.key, type: 'button', 'aria-pressed': !off, title: off ? `Show ${it.label}` : `Hide ${it.label}`, onClick: () => onToggle?.(it.key),
      style: { display: 'inline-flex', alignItems: 'center', gap: 5, padding: '1px 2px', border: 0, background: 'none', cursor: 'pointer', fontSize: 11, color: off ? 'var(--dim,#737D90)' : MUT, textDecoration: off ? 'line-through' : 'none' } },
    h('span', { 'aria-hidden': true, style: { width: 9, height: it.line ? 2 : 9, borderRadius: 2, background: off ? 'transparent' : it.color, border: off ? '1px solid var(--bds,#2A3547)' : 0, flex: 'none' } }), it.label);
  }));
}

// A readout box positioned inside a relative container; `x` is the anchor in px.
export function Tooltip({ x, y = 6, width, title, rows }) {
  if (x == null) return null;
  const W = 190, left = Math.max(0, Math.min(x + 12, width - W)), flip = x + 12 + W > width && x - 12 - W >= 0;
  return h('div', { role: 'presentation', style: { position: 'absolute', top: y, left: flip ? x - 12 - W : left, width: W, pointerEvents: 'none', zIndex: 5, padding: '6px 8px', borderRadius: 7, background: 'var(--card,#11151D)', border: '1px solid var(--bds,#2A3547)', boxShadow: '0 8px 22px rgba(0,0,0,.35)', fontSize: 11.5, lineHeight: 1.45 } },
    title && h('div', { style: { color: MUT, marginBottom: 2 } }, title),
    (rows || []).map((r, i) => h('div', { key: i, style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 } },
      r.color && h('span', { style: { width: 8, height: 8, borderRadius: 2, background: r.color, flex: 'none' } }),
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, r.label),
      h('span', { style: { fontFamily: MONO, fontSize: 11 } }, r.value))));
}

// "View as table": the same data as an accessible table.
export function DataTable({ caption, columns, rows, maxHeight = 260 }) {
  const th = { position: 'sticky', top: 0, background: 'var(--card,#11151D)', padding: '4px 8px', textAlign: 'left', fontSize: 10.5, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase', color: MUT, whiteSpace: 'nowrap', borderBottom: '1px solid ' + BD };
  const td = (i) => ({ padding: '3px 8px', borderTop: '1px solid ' + BD, fontFamily: i ? MONO : undefined, fontSize: i ? 11 : 11.5, textAlign: i ? 'right' : 'left', whiteSpace: 'nowrap' });
  if (!rows.length) return h(Frame, { state: 'empty', height: 80 });
  return h('div', { style: { maxHeight, overflow: 'auto' } },
    h('table', { style: { width: '100%', borderCollapse: 'collapse' } },
      caption && h('caption', { style: { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' } }, caption),
      h('thead', null, h('tr', null, columns.map((c, i) => h('th', { key: i, scope: 'col', style: { ...th, textAlign: i ? 'right' : 'left' } }, c)))),
      h('tbody', null, rows.map((r, j) => h('tr', { key: j }, r.map((c, i) => h(i ? 'td' : 'th', { key: i, scope: i ? undefined : 'row', style: { ...td(i), fontWeight: 400 } }, c)))))));
}

// Arrow keys move a readout index; Home/End jump; Escape clears.
export function keyIndex(e, idx, n, set) {
  const k = e.key;
  if (k === 'ArrowRight' || k === 'ArrowLeft') { e.preventDefault(); set(Math.max(0, Math.min(n - 1, (idx ?? (k === 'ArrowRight' ? -1 : n)) + (k === 'ArrowRight' ? 1 : -1)))); }
  else if (k === 'Home') { e.preventDefault(); set(0); }
  else if (k === 'End') { e.preventDefault(); set(n - 1); }
  else if (k === 'Escape') set(null);
}
export const srOnly = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' };
