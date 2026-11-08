// Chart-backed pieces the shell uses outside the dashboard grid (brief §11.4, §11.8): the widget
// card, the data hook, the Overview's Table and Timeline views, the memory history chart (header
// popover, Settings → Machine → Memory, dashboard), model storage, the outputs histogram, and the generic
// Overview tab's stat charts. Written by us (web/PATCHES.md).

import { h, SERIES, OTHER, TONE, MONO, MUT, BD, fmtBytes, fmtDur, srOnly, Frame } from './chart-kit.js';
import { AreaChart, LineChart, BarChart, Sparkline, Timeline, Treemap } from './charts.js';
import { store } from './ui-store.js';

const R = () => globalThis.React;
export const svcColor = (services, id) => { const i = services.findIndex(s => s.id === id); return i < 0 ? OTHER : SERIES[i % SERIES.length]; };
export const KIND_COLOR = { audio: SERIES[1], image: SERIES[0], video: SERIES[4], model3d: SERIES[2], text: SERIES[3], document: SERIES[7], archive: SERIES[5], other: OTHER };
export const KIND_LABEL = { audio: 'Audio', image: 'Image', video: 'Video', model3d: '3D', text: 'Text', document: 'Document', archive: 'Archive', other: 'Other' };
const errText = e => e?.detail || e?.message || String(e);

// Fetch with loading/error state; refetch when `deps` change, and every `every` ms while the tab
// is visible (never while hidden: a hidden tab makes no chart requests). A failed poll keeps the
// last data on screen.
export function useData(load, deps, every = 0) {
  const React = R(), tok = React.useRef(0);
  const [st, set] = React.useState({ state: 'loading', data: null, error: null });
  const run = React.useCallback(() => {
    const my = ++tok.current;
    Promise.resolve().then(load).then(
      d => { if (my === tok.current) set({ state: 'ok', data: d, error: null }); },
      e => { if (my === tok.current) set(s => (s.data && s.state === 'ok' ? s : { state: 'error', data: null, error: errText(e) })); });
  }, deps);  // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    set(s => ({ ...s, state: 'loading', data: null }));
    run();
    if (!every) return () => { tok.current++; };
    const tick = () => { if (!document.hidden) run(); };
    const iv = setInterval(tick, every);
    document.addEventListener('visibilitychange', tick);
    return () => { clearInterval(iv); document.removeEventListener('visibilitychange', tick); tok.current++; };
  }, [run, every]);
  return { ...st, retry: () => { set(s => ({ ...s, state: 'loading' })); run(); } };
}
export const pollFor = range => (range === '1h' ? 15000 : range === '6h' ? 30000 : 60000);
export const chartState = d => ({ state: d.state === 'ok' ? 'ok' : d.state, error: d.error, onRetry: d.retry });

// ---------- card ----------
const segBtn = on => ({ height: 22, padding: '0 7px', border: 0, borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: 'pointer', background: on ? 'var(--hov,#161C28)' : 'transparent', color: on ? 'var(--tx,#E6EAF2)' : MUT, boxShadow: on ? '0 0 0 1px var(--bds,#2A3547)' : 'none' });
export function RangePicker({ ranges, value, onChange, label = 'Range' }) {
  if (!ranges || ranges.length < 2) return null;
  return h('div', { role: 'group', 'aria-label': label, style: { display: 'inline-flex', padding: 1, borderRadius: 6, border: '1px solid ' + BD, background: 'var(--sb,#0D1119)', flex: 'none' } },
    ranges.map(r => h('button', { key: r, type: 'button', 'aria-pressed': r === value, onClick: () => onChange(r), style: segBtn(r === value) }, r)));
}
export const MockBadge = () => h('span', { title: 'Mock data: this area isn’t live yet', style: { height: 16, padding: '0 5px', borderRadius: 3, border: '1px solid var(--pu,#BC8CFF)', color: 'var(--pu,#BC8CFF)', fontSize: 9.5, fontWeight: 600, letterSpacing: '.06em', display: 'inline-flex', alignItems: 'center', flex: 'none' } }, 'MOCK');
// A dashboard widget: title, range picker, ⋯ menu ("View as table", "Open page"), MOCK badge.
export function Card({ title, ranges, range, onRange, href, table, onTable, mock, children, style, extra, pad = 10 }) {
  const React = R(), [open, setOpen] = React.useState(false), id = React.useId ? React.useId() : title;
  const menu = [];
  if (onTable) menu.push(h('button', { key: 't', role: 'menuitem', type: 'button', onClick: () => { setOpen(false); onTable(!table); }, style: menuItem }, table ? 'View as chart' : 'View as table'));
  if (href) menu.push(h('a', { key: 'o', role: 'menuitem', href, onClick: () => setOpen(false), style: { ...menuItem, color: 'var(--tx,#E6EAF2)', textDecoration: 'none' } }, 'Open page'));
  return h('section', { 'aria-labelledby': id, style: { background: 'var(--card,#11151D)', border: '1px solid ' + BD, borderRadius: 9, padding: pad, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0, ...style } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, minHeight: 24, position: 'relative' } },
      h('h2', { id, style: { margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: MUT, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, title),
      mock && h(MockBadge), extra,
      h(RangePicker, { ranges, value: range, onChange: onRange, label: `${title} range` }),
      menu.length > 0 && h('button', { type: 'button', 'aria-label': `${title} options`, 'aria-haspopup': 'menu', 'aria-expanded': open, onClick: () => setOpen(!open), style: { width: 24, height: 22, display: 'grid', placeItems: 'center', border: 0, borderRadius: 4, background: open ? 'var(--hov,#161C28)' : 'transparent', color: MUT, cursor: 'pointer', flex: 'none' } },
        h('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': true }, h('path', { d: 'M5 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0M10.5 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0M16 12a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0' }))),
      open && h('div', { onClick: () => setOpen(false), 'aria-hidden': true, style: { position: 'fixed', inset: 0, zIndex: 30 } }),
      open && h('div', { role: 'menu', style: { position: 'absolute', right: 0, top: 26, zIndex: 31, minWidth: 150, padding: 4, borderRadius: 8, background: 'var(--card,#11151D)', border: '1px solid var(--bds,#2A3547)', boxShadow: '0 12px 30px rgba(0,0,0,.4)', display: 'flex', flexDirection: 'column' } }, menu)),
    children);
}
const menuItem = { display: 'flex', alignItems: 'center', height: 28, padding: '0 8px', border: 0, borderRadius: 5, background: 'transparent', textAlign: 'left', cursor: 'pointer', fontSize: 12 };

// ---------- memory history ----------
// Stacked area per service + "other", with the reserve line (total − reserve) and available
// memory. `reserveBytes` overrides the recorded reserve (Settings draws your unsaved value).
export function MemoryChart({ api, services, range = '1h', height = 150, reserveBytes, table, label = 'Memory over time' }) {
  const d = useData(() => api.getMetrics({ series: ['mem.svc.*', 'mem.other', 'mem.total', 'mem.reserve', 'mem.available'], range }), [api, range], pollFor(range));
  if (d.state !== 'ok') return h(AreaChart, { ...chartState(d), height, label });
  const m = d.data, S = m.series, ids = Object.keys(S).filter(k => k.startsWith('mem.svc.')).map(k => k.slice(8));
  ids.sort((a, b) => services.findIndex(s => s.id === a) - services.findIndex(s => s.id === b));
  const total = S['mem.total'] || [], res = S['mem.reserve'] || [];
  const series = ids.filter(id => (S['mem.svc.' + id] || []).some(v => v)).map(id => ({ key: id, label: services.find(s => s.id === id)?.name || id, values: S['mem.svc.' + id], color: svcColor(services, id) }));
  series.push({ key: 'other', label: 'Other', values: S['mem.other'] || [], color: OTHER });
  series.push({ key: 'reserve', label: 'Reserve line', type: 'line', dash: true, color: 'var(--tx,#E6EAF2)', values: total.map((t, i) => (t == null ? null : t - (reserveBytes ?? res[i] ?? 0))) });
  series.push({ key: 'avail', label: 'Available', type: 'line', dash: true, color: 'var(--gr,#3FB950)', values: S['mem.available'] || [] });
  const yMax = Math.max(0, ...total.filter(v => v != null));
  return h(AreaChart, { t: m.t, series, stacked: true, unit: 'bytes', height, label, table, yMax: yMax || undefined });
}

// ---------- model storage: size by kind + disk free ----------
export function StorageChart({ totals, disk, kinds, height = 120, table, onPick }) {
  const items = Object.entries(totals?.by_kind || {}).map(([k, v], i) => ({ key: k, label: kinds?.[k] || k, value: v.size_bytes, color: SERIES[i % SERIES.length] }));
  const used = disk ? disk.total_bytes - disk.free_bytes : 0, pct = disk ? used / disk.total_bytes : 0, tone = disk && disk.free_bytes < 50e9 ? (disk.free_bytes < 10e9 ? 'red' : 'accent') : 'cyan';
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    h(Treemap, { items, height, label: 'Model storage by kind', table, onPick }),
    disk && h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: MUT } },
      h('span', { style: { flex: 'none' } }, 'Disk'),
      h('span', { role: 'meter', 'aria-label': 'Disk used', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(pct * 100), style: { flex: 1, height: 6, borderRadius: 9, background: 'var(--row,#1A2130)', overflow: 'hidden', display: 'block' } },
        h('span', { style: { display: 'block', height: '100%', width: (pct * 100).toFixed(1) + '%', background: TONE[tone], borderRadius: 9 } })),
      h('span', { style: { fontFamily: MONO, color: tone === 'cyan' ? 'var(--tx,#E6EAF2)' : TONE[tone], flex: 'none' } }, `${fmtBytes(disk.free_bytes)} free`)));
}

// ---------- outputs per day (Outputs page): drag across it to set the date filter ----------
export function OutputsHistogram({ api, range = '30d', onRange, selected, height = 90, refresh = 0 }) {
  const d = useData(() => api.getOutputStats({ range, by: 'day' }), [api, range, refresh], 120000);
  if (d.state !== 'ok') return h(BarChart, { ...chartState(d), height, label: 'Outputs per day' });
  const b = d.data.buckets, kinds = Object.keys(KIND_COLOR).filter(k => b.some(x => x.by_kind[k]));
  const cats = b.map(x => { const [, m, dd] = x.key.split('-'); return `${+m}/${+dd}`; });
  const sel = selected ? b.map((x, i) => (x.key >= selected[0] && x.key <= selected[1] ? i : -1)).filter(i => i >= 0) : [];
  return h(BarChart, { categories: cats, stacked: true, height, label: 'Outputs per day — drag to filter', unit: 'count',
    series: kinds.map(k => ({ key: k, label: KIND_LABEL[k], values: b.map(x => x.by_kind[k] || 0), color: KIND_COLOR[k] })),
    brush: sel.length ? [sel[0], sel[sel.length - 1]] : null,
    onBrush: (i, j) => onRange?.(b[i].key, b[j].key) });
}

// ---------- generic Overview tab: a chart per numeric stat + memory + the mod's lane ----------
export function ServiceCharts({ api, service, range = '24h' }) {
  const id = service.id;
  const d = useData(() => Promise.all([api.getMetrics({ series: [`svc.${id}.stat.*`, `mem.svc.${id}`], range }), api.getTimeline({ range, services: id })]), [api, id, range], pollFor(range));
  const stats = (service.stats || []).filter(s => s.series);
  const cell = (key, title, el) => h('div', { key, style: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 } }, h('div', { style: { fontSize: 11.5, color: MUT } }, title), el);
  if (d.state !== 'ok') return h(LineChart, { ...chartState(d), height: 110, label: `${service.name} history` });
  const [m, tl] = d.data, lane = tl.lanes[0];
  const charts = [cell('mem', 'Memory', h(AreaChart, { t: m.t, height: 110, unit: 'bytes', label: `${service.name} memory`, series: [{ key: 'm', label: 'Memory', values: m.series[`mem.svc.${id}`] || [], color: SERIES[0] }] }))];
  stats.forEach((s, i) => charts.push(cell(s.series, s.label, h(LineChart, { t: m.t, height: 110, unit: s.unit === 'ms' ? 'ms' : 'count', label: s.label, series: [{ key: s.series, label: s.label, values: m.series[s.series] || [], color: SERIES[(i + 1) % SERIES.length] }] }))));
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(min(100%,260px),1fr))', gap: 12 } }, charts),
    lane && h(Timeline, { from: tl.from, to: tl.to, lanes: [{ ...lane, key: id, label: service.name }], laneH: 26, labelW: 90, minWidth: 320, label: `${service.name} timeline` }));
}

// ---------- Overview → Table ----------
const COLS = [['name', 'Service'], ['state', 'State'], ['load', 'Load'], ['mem', 'Memory'], ['spark', '1 h'], ['idle', 'Idle'], ['jobs', 'Jobs'], ['err', 'Last error'], ['act', '']];
export function ServiceTable({ services, hist1, jobs, icons, actionsFor, badge, compact }) {
  const React = R(), [sort, setSort] = React.useState(() => store.get('hub.table.sort', null) || { k: null, dir: 1 });   // the UI store (settings-that-stick 4.3)
  const setS = k => { const s = { k, dir: sort.k === k ? -sort.dir : 1 }; setSort(s); store.set('hub.table.sort', s); };
  const maxMem = Math.max(1, ...services.map(s => s.memory.used_bytes));
  const rows = services.map((s, i) => ({ s, i, jobs: jobs.filter(j => j.service === s.id).length, idle: s.load === 'loaded' && s.idle_s != null ? s.idle_s : null }));
  const key = { name: r => r.s.name.toLowerCase(), state: r => r.s.state, load: r => r.s.load, mem: r => r.s.memory.used_bytes, idle: r => r.idle ?? -1, jobs: r => r.jobs, err: r => r.s.last_error || '' }[sort.k];
  if (key) rows.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * sort.dir);
  const pad = compact ? '4px 8px' : '8px 10px';
  const th = { padding: pad, textAlign: 'left', fontSize: 10.5, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: MUT, whiteSpace: 'nowrap', borderBottom: '1px solid ' + BD };
  const td = { padding: pad, borderTop: '1px solid ' + BD, verticalAlign: 'middle', whiteSpace: 'nowrap', height: compact ? 30 : 38 };
  return h('div', { style: { overflowX: 'auto', background: 'var(--card,#11151D)', border: '1px solid ' + BD, borderRadius: 9 } },
    h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 860 } },
      h('caption', { style: srOnly }, 'Services'),
      h('thead', null, h('tr', null, COLS.map(([k, l]) => h('th', { key: k, scope: 'col', 'aria-sort': sort.k === k ? (sort.dir > 0 ? 'ascending' : 'descending') : undefined, style: th },
        ['spark', 'act'].includes(k) ? l : h('button', { type: 'button', onClick: () => setS(k), style: { border: 0, background: 'none', padding: 0, font: 'inherit', color: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit', cursor: 'pointer' } }, l + (sort.k === k ? (sort.dir > 0 ? ' ▲' : ' ▼') : '')))))),
      h('tbody', null, rows.map(({ s, i, jobs: nj, idle }) => {
        const sb = badge(s.state), lb = s.load === 'n/a' ? null : badge(s.load, true), mem = s.memory.used_bytes, col = SERIES[i % SERIES.length];
        return h('tr', { key: s.id },
          h('th', { scope: 'row', style: { ...td, fontWeight: 500, textAlign: 'left' } }, h('a', { href: '#/s/' + s.id, style: { display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--tx,#E6EAF2)' } },
            h('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { color: MUT } }, h('path', { d: icons[s.icon] || icons.puzzle })), s.name)),
          h('td', { style: td }, h('span', { style: sb.st }, sb.dot, sb.label)),
          h('td', { style: td }, lb ? h('span', { style: lb.st }, lb.dot, lb.label) : h('span', { style: { color: MUT } }, '—')),
          h('td', { style: td }, h('span', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
            h('span', { style: { width: 70, height: 6, borderRadius: 9, background: 'var(--row,#1A2130)', overflow: 'hidden', display: 'block', flex: 'none' } }, h('span', { style: { display: 'block', height: '100%', width: (mem / maxMem * 100) + '%', background: col } })),
            h('span', { style: { fontFamily: MONO, fontSize: 11.5 } }, mem > 0.05e9 ? fmtBytes(mem) : '—'))),
          h('td', { style: { ...td, width: 100 } }, h(Sparkline, { values: hist1?.series?.['mem.svc.' + s.id] || [], color: col, width: 90, height: 20, label: `${s.name} memory, last hour`, unit: 'bytes' })),
          h('td', { style: { ...td, fontFamily: MONO, fontSize: 11.5, color: MUT } }, idle != null ? fmtDur(idle) : '—'),
          h('td', { style: { ...td, fontFamily: MONO, fontSize: 11.5 } }, nj ? String(nj) : '—'),
          h('td', { style: { ...td, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', color: s.last_error ? 'var(--rd,#F85149)' : MUT, fontFamily: s.last_error ? MONO : undefined, fontSize: 11.5 }, title: s.last_error || '' }, s.manifest_errors?.length ? s.manifest_errors[0] : s.last_error || '—'),
          h('td', { style: { ...td, textAlign: 'right' } }, h('span', { style: { display: 'inline-flex', gap: 4 } }, actionsFor(s).map((a, k) => h(IconBtn, { key: k, ...a })))));
      }))));
}
export function IconBtn({ label, d, on, dis, primary, size = 28 }) {
  return h('button', { type: 'button', onClick: on, disabled: dis, title: label, 'aria-label': label,
    style: { width: size, height: size, display: 'inline-grid', placeItems: 'center', padding: 0, borderRadius: 6, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.5 : 1, flex: 'none',
      border: primary ? '1px solid transparent' : '1px solid var(--bds,#2A3547)', background: primary ? 'var(--acc,#FFB224)' : 'var(--inset,#131926)', color: primary ? '#1A1200' : 'var(--tx,#E6EAF2)' } },
  h('svg', { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }, h('path', { d })));
}

// ---------- Overview → Timeline ----------
export const TL_RANGES = ['1h', '6h', '24h', '7d'];
export function TimelineView({ api, services, go, range, onRange, table, onTable, mock }) {
  const d = useData(() => api.getTimeline({ range }), [api, range], pollFor(range));
  const name = id => services.find(s => s.id === id)?.name || id;
  const open = (kind, x, lane) => go(kind === 'output' ? '#/outputs/' + x.id : kind === 'event' ? `#/s/${lane.key}/logs` : x.route || '#/s/' + lane.key);
  const body = d.state !== 'ok' ? h(Timeline, { ...chartState(d), lanes: services.map(s => ({ key: s.id })) })
    : h(Timeline, { from: d.data.from, to: d.data.to, label: 'Service timeline', table, onOpen: open, lanes: d.data.lanes.map(l => ({ ...l, key: l.service, label: name(l.service), href: '#/s/' + l.service })), laneH: 34, labelW: 120, minWidth: 640 });
  return h(Card, { title: 'Timeline', ranges: TL_RANGES, range, onRange, table, onTable, mock, pad: 12,
    extra: h('span', { style: { display: 'inline-flex', gap: 10, fontSize: 11, color: MUT, marginRight: 6, flexWrap: 'wrap' } },
      [['var(--gr,#3FB950)', 'ready'], ['var(--acc,#FFB224)', 'starting / job'], ['var(--rd,#F85149)', 'failed'], ['var(--cy,#58C4DD)', 'model loaded'], ['var(--pu,#BC8CFF)', 'output']].map(([c, l]) => h('span', { key: l, style: { display: 'inline-flex', alignItems: 'center', gap: 4 } }, h('span', { style: { width: 8, height: 8, borderRadius: 2, background: c } }), l))) }, body);
}
export { Frame };
