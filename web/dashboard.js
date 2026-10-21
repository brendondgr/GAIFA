// The Overview's Dashboard view (brief §11.4–11.5): the KPI strip, then a 12-column grid of
// widgets you can show, hide, reorder and give a range (Customize). The layout is saved in
// Settings (`ui.dashboard`) by the shell's `onLayout`. Written by us (web/PATCHES.md).

import { h, SERIES, OTHER, TONE, MONO, MUT, BD, fmtNum, useWidth, Frame, btnSt } from './chart-kit.js';
import { AreaChart, LineChart, BarChart, HBarChart, Donut, Heatmap, Timeline, KpiTile, Sparkline } from './charts.js';
import { useData, pollFor, chartState, Card, MemoryChart, StorageChart, svcColor, KIND_COLOR, KIND_LABEL } from './views.js';
import { GpuQueueW, jobGpuText } from './gpu-queue.js';

const R = () => globalThis.React;
const RANGES = ['1h', '6h', '24h', '7d', '30d'];
const MODEL_KINDS = { llm: 'LLM', tts: 'TTS', stt: 'STT', voice: 'Voice', '3d': '3D', image: 'Image', video: 'Video', 'text-encoder': 'Text encoder', vae: 'VAE', lora: 'LoRA', vision: 'Vision', upscale: 'Upscale', other: 'Other' };
const dayLabel = key => { const d = new Date(key + 'T00:00:00'); return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }); };

// ---------- layout (pure; tested in utils/tests/web/dashboard.test.mjs) ----------
// Widget keys in display order: the saved order first (unknown keys dropped), then the rest in
// the default order.
export function orderKeys(defaults, saved = []) {
  const known = new Set(defaults);
  const head = saved.filter((k, i) => known.has(k) && saved.indexOf(k) === i);
  return [...head, ...defaults.filter(k => !head.includes(k))];
}
// Columns a widget spans at a container width: one column under 760 px, doubled under 1100 px.
export function spanAt(span, width) {
  if (width < 760) return 12;
  if (width < 1100) return span <= 4 ? 6 : 12;
  return span;
}
export function moveKey(order, key, dir) {
  const i = order.indexOf(key), j = i + dir;
  if (i < 0 || j < 0 || j >= order.length) return order;
  const o = [...order]; [o[i], o[j]] = [o[j], o[i]];
  return o;
}

// ---------- widgets ----------
function MemTimeW({ ctx, range, table }) { return h(MemoryChart, { api: ctx.api, services: ctx.services, range, height: 160, table }); }

function MemNowW({ ctx, table }) {
  const m = ctx.memory;
  if (!m) return h(Frame, { state: 'loading', height: 140 });
  const items = m.by_service.filter(x => x.used_bytes > 0.01e9).sort((a, b) => b.used_bytes - a.used_bytes)
    .map(x => ({ key: x.id, label: ctx.services.find(s => s.id === x.id)?.name || x.id, value: x.used_bytes, color: svcColor(ctx.services, x.id) }));
  items.push({ key: 'other', label: 'Other', value: m.other_bytes, color: OTHER }, { key: 'free', label: 'Free', value: Math.max(0, m.total_bytes - m.used_bytes), color: 'var(--row,#1A2130)' });
  return h(Donut, { items, unit: 'bytes', center: (m.used_bytes / 1e9).toFixed(1) + ' GB', sub: `of ${(m.total_bytes / 1e9).toFixed(0)} GB`, label: 'Memory now', table, size: 124 });
}

function GpuW({ ctx, range, table }) {
  const d = useData(() => ctx.api.getMetrics({ series: ['gpu.gtt_used'], range }), [ctx.api, range], pollFor(range));
  if (d.state !== 'ok') return h(AreaChart, { ...chartState(d), height: 130 });
  return h(AreaChart, { t: d.data.t, height: 130, unit: 'bytes', label: 'GPU memory (GTT)', table, series: [{ key: 'gtt', label: 'GTT used', values: d.data.series['gpu.gtt_used'] || [], color: SERIES[2] }] });
}

function OutDayW({ ctx, table }) {
  const d = useData(() => ctx.api.getOutputStats({ range: '30d', by: 'day' }), [ctx.api, ctx.outTick], 120000);
  if (d.state !== 'ok') return h(BarChart, { ...chartState(d), height: 140 });
  const b = d.data.buckets, kinds = Object.keys(KIND_COLOR).filter(k => b.some(x => x.by_kind[k]));
  return h(BarChart, { categories: b.map(x => { const [, m, dd] = x.key.split('-'); return `${+m}/${+dd}`; }), stacked: true, height: 140, unit: 'count', label: 'Outputs per day', table,
    series: kinds.map(k => ({ key: k, label: KIND_LABEL[k], values: b.map(x => x.by_kind[k] || 0), color: KIND_COLOR[k] })),
    onPick: i => ctx.go(`#/outputs?from=${b[i].key}&to=${b[i].key}`) });
}

function OutSvcW({ ctx, range, table }) {
  const d = useData(() => ctx.api.getOutputStats({ range, by: 'service' }), [ctx.api, range, ctx.outTick], 120000);
  if (d.state !== 'ok') return h(HBarChart, { ...chartState(d), height: 110 });
  const b = d.data.buckets;
  return h(HBarChart, { categories: b.map(x => ctx.services.find(s => s.id === x.key)?.name || x.key), unit: 'count', label: 'Outputs by service', table,
    series: [{ key: 'n', label: 'Outputs', values: b.map(x => x.count), color: SERIES[0] }], onPick: i => ctx.go('#/s/' + b[i].key + '/outputs') });
}

function HeatW({ ctx, range, table }) {
  const d = useData(() => ctx.api.getActivityStats({ range }), [ctx.api, range], 300000);
  if (d.state !== 'ok') return h(Heatmap, { ...chartState(d), height: 150 });
  const days = [...new Set(d.data.cells.map(c => c.day))].sort();
  const rows = days.map(day => ({ label: dayLabel(day), cells: Array.from({ length: 24 }, (_, hr) => { const c = d.data.cells.find(x => x.day === day && x.hour === hr) || { count: 0, errors: 0 }; return { v: c.count, err: c.errors, tip: `${dayLabel(day)}, ${String(hr).padStart(2, '0')}:00` }; }) }));
  return h(Heatmap, { rows, cols: Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')), label: 'Activity by hour', table });
}

// Any widget a mod declares (§11.7 WidgetData); relay's `traffic` is the LLM traffic widget.
function ModW({ ctx, info, range, table }) {
  const d = useData(() => ctx.api.getWidget(info.service, info.id, { range }), [ctx.api, info.service, info.id, range], pollFor(range));
  const label = info.title;
  if (d.state !== 'ok') return h(LineChart, { ...chartState(d), height: 140, label });
  const w = d.data, unit = w.unit, series = w.series.map((s, i) => ({ key: s.name, label: s.name, values: s.values, axis: s.axis || 'left', color: SERIES[i % SERIES.length], type: info.kind === 'bar' && (s.axis || 'left') === 'right' ? 'line' : undefined }));
  if (info.kind === 'table') return h('div', { style: { overflow: 'auto', maxHeight: 220 } }, h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 11.5 } },
    h('thead', null, h('tr', null, Object.keys(w.rows?.[0] || {}).map(k => h('th', { key: k, style: { textAlign: 'left', padding: '3px 6px', color: MUT, fontSize: 10.5 } }, k)))),
    h('tbody', null, (w.rows || []).map((r, i) => h('tr', { key: i }, Object.values(r).map((v, j) => h('td', { key: j, style: { padding: '3px 6px', borderTop: '1px solid ' + BD, fontFamily: typeof v === 'number' ? MONO : undefined } }, String(v))))))));
  if (info.kind === 'number') { const v = w.series[0]?.values.at(-1); return h('div', { style: { fontFamily: MONO, fontSize: 26, fontWeight: 600, padding: '12px 0' } }, v == null ? '—' : fmtNum(v), h('span', { style: { fontSize: 12, color: MUT, marginLeft: 6 } }, unit && unit !== 'count' ? unit : '')); }
  if (info.kind === 'donut') return h(Donut, { items: (w.categories || []).map((c, i) => ({ key: c, label: c, value: w.series[0]?.values[i] || 0 })), unit, label, table, size: 120 });
  const Comp = info.kind === 'area' ? AreaChart : info.kind === 'bar' ? BarChart : LineChart;
  return h(Comp, { t: w.t, categories: w.t ? undefined : w.categories, series, unit, height: 150, label, table });
}

function JobsW({ ctx, range, table }) {
  const d = useData(() => ctx.api.getJobStats({ range }), [ctx.api, range], 120000);
  const now = ctx.jobs.filter(j => j.state === 'running' || j.state === 'queued');
  const name = id => ctx.services.find(s => s.id === id)?.name || id;
  const live = h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
    now.length ? now.slice(0, 3).map(j => h('a', { key: j.id, href: j.route || '#/s/' + j.service, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: 'var(--tx,#E6EAF2)', minWidth: 0 } },
      h('span', { title: jobGpuText(j, name) || undefined, style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, j.label),
      h('span', { style: { width: 60, height: 5, borderRadius: 9, background: 'var(--row,#1A2130)', overflow: 'hidden', display: 'block', flex: 'none' } }, h('span', { style: { display: 'block', height: '100%', width: (j.progress || 0) * 100 + '%', background: TONE.accent } })),
      h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: MUT, width: 48, textAlign: 'right' } }, j.stage === 'waiting_gpu' ? 'GPU wait' : j.state === 'queued' ? 'queued' : j.progress != null ? Math.round(j.progress * 100) + '%' : 'running')))
      : h('div', { style: { fontSize: 11.5, color: MUT } }, 'No jobs running'));
  let chart;
  if (d.state !== 'ok') chart = h(HBarChart, { ...chartState(d), height: 90 });
  else {
    const b = d.data.by_service;
    chart = table ? h('div', null, h(HBarChart, { categories: b.map(x => name(x.service)), unit: 'seconds', table: true, label: 'Job durations', series: [{ key: 'n', label: 'Jobs', values: b.map(x => x.count) }, { key: 'f', label: 'Failed', values: b.map(x => x.failed) }, { key: 'p50', label: 'p50', values: b.map(x => x.p50_s) }, { key: 'p90', label: 'p90', values: b.map(x => x.p90_s) }, { key: 'max', label: 'Max', values: b.map(x => x.max_s) }] }))
      : h(HBarChart, { categories: b.map(x => name(x.service)), unit: 'seconds', label: 'Job duration p50 and p90',
        series: [{ key: 'p50', label: 'p50', values: b.map(x => x.p50_s), color: SERIES[0] }, { key: 'p90', label: 'p90', values: b.map(x => x.p90_s), color: SERIES[1] }] });
  }
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } }, live, chart);
}

function StorageW({ ctx, table }) {
  const d = useData(() => ctx.api.listModels(), [ctx.api], 300000);
  if (d.state !== 'ok') return h(Frame, { state: d.state, error: d.error, onRetry: d.retry, height: 120 });
  return h(StorageChart, { totals: d.data.totals, disk: d.data.disk, kinds: MODEL_KINDS, height: 110, table, onPick: () => ctx.go('#/models') });
}

function UptimeW({ ctx, table }) {
  const d = useData(() => ctx.api.getTimeline({ range: '24h' }), [ctx.api], 60000);
  const name = id => ctx.services.find(s => s.id === id)?.name || id;
  if (d.state !== 'ok') return h(Timeline, { ...chartState(d), lanes: ctx.services.map(s => ({ key: s.id })), laneH: 20 });
  return h(Timeline, { from: d.data.from, to: d.data.to, label: 'Service uptime, 24 hours', table, laneH: 20, labelW: 92, minWidth: 300,
    lanes: d.data.lanes.map(l => ({ key: l.service, label: name(l.service), href: '#/s/' + l.service, states: l.states, loaded: l.loaded, jobs: [], outputs: [], events: l.events.filter(e => e.level === 'error') })),
    onOpen: (k, x, lane) => ctx.go('#/s/' + lane.key + '/logs') });
}

function ServicesW({ ctx }) {
  if (!ctx.services.length) return h(Frame, { state: 'empty', height: 80, emptyText: 'No mods installed yet' });
  return h('div', { style: { display: 'flex', flexDirection: 'column' } }, ctx.services.map((s, i) => {
    const b = ctx.badge(s.state), mem = s.memory.used_bytes;
    return h('a', { key: s.id, href: '#/s/' + s.id, style: { display: 'flex', alignItems: 'center', gap: 8, height: 27, borderTop: i ? '1px solid ' + BD : 0, color: 'var(--tx,#E6EAF2)', fontSize: 12, minWidth: 0, textDecoration: 'none' } },
      b.dot, h('span', { style: { flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.name, h('span', { style: { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' } }, ', ' + s.state)),
      s.load === 'loaded' && h('span', { style: { fontSize: 10.5, color: TONE.cyan, flex: 'none' } }, 'loaded'),
      h('span', { style: { fontFamily: MONO, fontSize: 11, color: mem > 0.05e9 ? 'var(--tx,#E6EAF2)' : MUT, width: 56, textAlign: 'right', flex: 'none' } }, mem > 0.05e9 ? (mem / 1e9).toFixed(1) + ' GB' : '—'),
      h('span', { style: { width: 64, flex: 'none' } }, h(Sparkline, { values: ctx.hist24?.series?.['mem.svc.' + s.id] || [], color: svcColor(ctx.services, s.id), width: 64, height: 18, label: `${s.name} memory, 24 h`, unit: 'bytes' })));
  }));
}

function RecentW({ ctx }) {
  if (!ctx.recent.length) return h(Frame, { state: 'empty', height: 100, emptyText: 'Nothing produced yet' });
  return h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(104px,1fr))', gap: 8 } }, ctx.recent.slice(0, 8).map(o => h('a', { key: o.id, href: '#/outputs/' + o.id, title: o.title, style: { display: 'flex', flexDirection: 'column', minWidth: 0, borderRadius: 7, overflow: 'hidden', border: '1px solid ' + BD, color: 'var(--tx,#E6EAF2)', textDecoration: 'none', background: 'var(--inset,#131926)' } },
    h('span', { style: { position: 'relative', aspectRatio: '4/3', display: 'grid', placeItems: 'center', background: 'var(--row,#1A2130)', color: KIND_COLOR[o.kind] || MUT, fontSize: 11, fontWeight: 600 } },
      o.preview && o.kind !== 'audio' ? h('img', { src: o.preview, alt: '', loading: 'lazy', style: { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' } }) : (KIND_LABEL[o.kind] || o.kind).toUpperCase()),
    h('span', { style: { padding: '4px 6px', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, o.title))));
}

function ActivityW({ ctx }) {
  const React = R(), [lvl, setLvl] = React.useState('all');
  const list = ctx.activity.filter(a => lvl === 'all' || a.level === lvl).slice(0, 14);
  const chip = (k, l) => h('button', { key: k, type: 'button', 'aria-pressed': lvl === k, onClick: () => setLvl(k), style: { height: 20, padding: '0 8px', borderRadius: 99, fontSize: 11, cursor: 'pointer', border: '1px solid ' + (lvl === k ? 'var(--cy,#58C4DD)' : 'var(--bds,#2A3547)'), background: lvl === k ? 'var(--tcy,rgba(88,196,221,.13))' : 'transparent', color: lvl === k ? 'var(--tx,#E6EAF2)' : MUT } }, l);
  const clock = ts => { const d = new Date(ts * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('div', { role: 'group', 'aria-label': 'Level', style: { display: 'flex', gap: 4 } }, chip('all', 'All'), chip('info', 'Info'), chip('warn', 'Warnings'), chip('error', 'Errors')),
    list.length ? h('div', { style: { display: 'flex', flexDirection: 'column' } }, list.map(a => {
      const c = a.level === 'error' ? TONE.red : a.level === 'warn' ? TONE.accent : MUT;
      const text = h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, a.text);
      return h('div', { key: a.id, style: { display: 'flex', alignItems: 'center', gap: 8, height: 24, borderTop: '1px solid ' + BD, fontSize: 11.5, minWidth: 0 } },
        h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: MUT, flex: 'none' } }, clock(a.ts)),
        h('span', { 'aria-label': a.level, style: { width: 6, height: 6, borderRadius: 9, background: c, flex: 'none' } }),
        a.route ? h('a', { href: a.route, style: { flex: 1, minWidth: 0, display: 'flex', color: 'var(--tx,#E6EAF2)' } }, text) : text);
    })) : h(Frame, { state: 'empty', height: 60, emptyText: 'Nothing here' }));
}

// key → { title, span, ranges?, def?, href?, areas, C }
const BASE = [
  { key: 'services', title: 'Services', span: 4, areas: ['services'], C: ServicesW, noTable: true },
  { key: 'memory', title: 'Memory over time', span: 4, ranges: RANGES, def: '6h', href: '#/settings/memory', areas: ['metrics'], C: MemTimeW },
  { key: 'memory-now', title: 'Memory now', span: 4, areas: ['memory'], C: MemNowW },
  { key: 'gpu-queue', title: 'GPU queue', span: 4, ranges: ['24h', '7d'], def: '24h', areas: ['gpu', 'metrics'], C: GpuQueueW },  // plan 31.5
  { key: 'outputs-day', title: 'Outputs per day', span: 6, href: '#/outputs', areas: ['metrics'], C: OutDayW },
  { key: 'llm', title: 'LLM traffic', span: 6, ranges: ['24h', '7d'], def: '24h', areas: ['widgets'], mod: ['relay', 'traffic'] },
  { key: 'activity-heat', title: 'Activity heatmap', span: 6, ranges: ['7d', '14d'], def: '14d', areas: ['metrics'], C: HeatW },
  { key: 'jobs', title: 'Jobs', span: 3, ranges: ['24h', '7d', '30d'], def: '7d', areas: ['metrics', 'events'], C: JobsW },
  { key: 'storage', title: 'Model storage', span: 3, href: '#/models', areas: ['models'], C: StorageW },
  { key: 'uptime', title: 'Service uptime (24 h)', span: 6, areas: ['metrics'], C: UptimeW },
  { key: 'gpu', title: 'GPU memory (GTT)', span: 3, ranges: RANGES, def: '6h', areas: ['metrics'], C: GpuW },
  { key: 'outputs-service', title: 'Outputs by service', span: 3, ranges: ['24h', '7d', '30d'], def: '7d', href: '#/outputs', areas: ['metrics'], C: OutSvcW },
  { key: 'recent', title: 'Recent outputs', span: 6, href: '#/outputs', areas: ['outputs'], C: RecentW, noTable: true },
  { key: 'activity', title: 'Activity feed', span: 6, areas: ['events'], C: ActivityW, noTable: true },
];
export const DEFAULT_KEYS = BASE.map(w => w.key);

// The widget list for this install: the built-ins plus one per mod widget (relay's traffic is "LLM traffic").
export function widgetDefs(widgets = []) {
  const defs = [], relay = widgets.find(w => w.service === 'relay' && w.id === 'traffic');
  for (const w of BASE) {
    if (w.mod) { if (relay) defs.push({ ...w, ranges: relay.ranges, def: relay.ranges[0], info: relay, href: '#/s/relay' }); continue; }
    defs.push(w);
  }
  for (const w of widgets) if (w !== relay) defs.push({ key: `mod:${w.service}:${w.id}`, title: w.title, span: w.span, ranges: w.ranges, def: w.ranges[0], href: '#/s/' + w.service, areas: ['widgets'], info: w });
  return defs;
}

// ---------- KPI strip ----------
function Kpis({ ctx }) {
  const d = useData(() => ctx.api.getOutputStats({ range: '7d', by: 'day' }), [ctx.api, ctx.outTick], 120000);
  const s = ctx.services, m = ctx.memory, ready = s.filter(x => x.state === 'ready').length, failed = s.filter(x => x.state === 'failed').length;
  const pct = m ? m.used_bytes / m.total_bytes : 0, h1 = ctx.hist1?.series || {}, h24 = ctx.hist24?.series || {};
  const days = d.data?.buckets || [], today = days.at(-1)?.count ?? null, yday = days.at(-2)?.count ?? null;
  const tokStat = s.flatMap(x => x.stats.map(st => ({ st, x }))).find(({ st }) => /tokens today/i.test(st.label));
  const running = ctx.jobs.filter(j => j.state === 'running').length, queued = ctx.jobs.filter(j => j.state === 'queued').length;
  const tiles = [
    { label: 'Memory used', value: m ? `${(m.used_bytes / 1e9).toFixed(1)} GB` : '—', sub: m ? `of ${(m.total_bytes / 1e9).toFixed(0)} GB` : '', tone: pct > 0.92 ? 'red' : pct > 0.8 ? 'accent' : null, delta: m ? Math.round(pct * 100) + '%' : '', spark: { values: h1['mem.used'] || [], color: SERIES[0] }, unit: 'bytes', href: '#/settings/memory' },
    { label: 'Services ready', value: `${ready}/${s.length}`, sub: failed ? `${failed} failed` : 'ready', tone: failed ? 'red' : null, href: '#/overview?view=table' },
    { label: 'Models loaded', value: String(s.filter(x => x.load === 'loaded').length), sub: 'in memory', spark: null, href: '#/overview?view=timeline' },
    { label: 'Jobs running', value: String(running), sub: queued ? `${queued} queued` : 'now', tone: running ? 'accent' : null, spark: { values: h24['jobs.running'] || [], color: SERIES[1] }, unit: 'count' },
    { label: 'Outputs today', value: today == null ? '—' : String(today), sub: 'files', delta: today != null && yday != null ? `${today - yday >= 0 ? '+' : ''}${today - yday} vs yday` : '', deltaTone: today != null && yday != null && today > yday ? 'green' : null, spark: { values: days.map(b => b.count), color: SERIES[3] }, unit: 'count', href: '#/outputs?range=today' },
    { label: 'LLM tokens today', value: tokStat ? fmtNum(typeof tokStat.st.value === 'number' ? tokStat.st.value : Number(tokStat.st.value)) + (tokStat.st.unit && tokStat.st.unit !== 'count' ? tokStat.st.unit : '') : '—', sub: tokStat ? tokStat.x.name : 'no LLM relay', spark: tokStat?.st.series ? { values: h24[tokStat.st.series] || [], color: SERIES[2] } : null, unit: 'count', href: tokStat ? '#/s/' + tokStat.x.id : undefined },
  ];
  return h('div', { role: 'region', 'aria-label': 'Key figures', style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: ctx.gap } }, tiles.map(t => h(KpiTile, { key: t.label, ...t })));
}

// ---------- customize ----------
function Customize({ defs, layout, onLayout, onClose, cols = 2 }) {
  const order = orderKeys(defs.map(d => d.key), layout.order), hidden = new Set(layout.hidden || []);
  const set = p => onLayout({ ...layout, ...p });
  const row = (k, i) => {
    const d = defs.find(x => x.key === k), on = !hidden.has(k);
    return h('li', { key: k, style: { display: 'flex', alignItems: 'center', gap: 8, height: 32, borderBottom: '1px solid ' + BD, fontSize: 12.5, minWidth: 0 } },
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, cursor: 'pointer' } },
        h('input', { type: 'checkbox', checked: on, 'aria-label': `Show ${d.title}`, onChange: () => set({ hidden: on ? [...hidden, k] : [...hidden].filter(x => x !== k) }) }), d.title),
      h('span', { style: { fontSize: 10.5, color: MUT, fontFamily: MONO } }, `${d.span}/12`),
      h('button', { type: 'button', 'aria-label': `Move ${d.title} up`, disabled: i === 0, onClick: () => set({ order: moveKey(order, k, -1) }), style: { ...btnSt, width: 26, padding: 0 } }, '↑'),
      h('button', { type: 'button', 'aria-label': `Move ${d.title} down`, disabled: i === order.length - 1, onClick: () => set({ order: moveKey(order, k, 1) }), style: { ...btnSt, width: 26, padding: 0 } }, '↓'));
  };
  return h('div', { role: 'dialog', 'aria-label': 'Customize dashboard', style: { background: 'var(--card,#11151D)', border: '1px solid var(--acc,#FFB224)', borderRadius: 9, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
      h('strong', { style: { fontSize: 13 } }, 'Customize dashboard'),
      h('span', { style: { fontSize: 11.5, color: MUT } }, 'Saved to config.toml, so it follows you between browsers.'),
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', onClick: () => onLayout({ order: [], hidden: [], ranges: {} }), style: btnSt }, 'Reset'),
      h('button', { type: 'button', onClick: onClose, style: { ...btnSt, background: 'var(--acc,#FFB224)', color: '#1A1200', borderColor: 'transparent', fontWeight: 600 } }, 'Done')),
    h('ul', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'grid', gridAutoFlow: 'column', gridTemplateColumns: `repeat(${cols},minmax(0,1fr))`, gridTemplateRows: `repeat(${Math.ceil(order.length / cols)},auto)`, columnGap: 24 } }, order.map(row)));
}

// ---------- dashboard ----------
// props: api, services, memory, gpu (GpuState) and cancelGpu(id) (plan 31.5), jobs, activity, recent, hist1, hist24, widgets (WidgetInfo[]),
// layout ({order, hidden, ranges}), onLayout, customizing, onCustomize, go, badge, compact, outTick
export function Dashboard(props) {
  const React = R(), [ref, width] = useWidth(1200), [tables, setTables] = React.useState({});
  const { layout = { order: [], hidden: [], ranges: {} }, onLayout, api } = props;
  const gap = props.compact ? 10 : 14, ctx = { ...props, gap };
  const defs = widgetDefs(props.widgets || []);
  const hidden = new Set(layout.hidden || []);
  const keys = orderKeys(defs.map(d => d.key), layout.order).filter(k => !hidden.has(k));
  const cards = keys.map(k => {
    const d = defs.find(x => x.key === k), range = layout.ranges?.[k] && d.ranges?.includes(layout.ranges[k]) ? layout.ranges[k] : d.def, table = !!tables[k];
    const mock = (d.areas || []).some(a => api.isLive && !api.isLive(a));
    const body = d.info ? h(ModW, { ctx, info: d.info, range, table }) : h(d.C, { ctx, range, table });
    return h(Card, { key: k, title: d.title, ranges: d.ranges, range, href: d.href, mock, table, onTable: d.noTable ? undefined : v => setTables(t => ({ ...t, [k]: v })),
      onRange: r => onLayout({ ...layout, ranges: { ...layout.ranges, [k]: r } }), style: { gridColumn: `span ${spanAt(d.span, width)}` } }, body);
  });
  return h('div', { ref, style: { display: 'flex', flexDirection: 'column', gap, minWidth: 0 } },
    h(Kpis, { ctx }),
    props.customizing && h(Customize, { defs, layout, onLayout, onClose: () => props.onCustomize(false), cols: width < 760 ? 1 : 2 }),
    cards.length ? h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(12,minmax(0,1fr))', gridAutoFlow: 'row dense', gap, alignItems: 'start' } }, cards)
      : h(Frame, { state: 'empty', height: 120, emptyText: 'Every widget is hidden. Use Customize to show some.' }));
}
