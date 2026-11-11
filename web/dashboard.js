// The Overview's Dashboard view (brief §11.4–11.5; plan overview-bento): a bento grid of tiles with fixed
// sizes, what needs you and what's running on top, history below. Customize turns on editing (drag tiles
// to move them) and lists every tile with a switch and a size; each tile's ⋯ menu has its sizes and Hide.
// The layout is saved in Settings (`ui.dashboard`: order, hidden, shown, sizes, ranges) by the shell's
// `onLayout`. Written by us (web/PATCHES.md).

import { h, SERIES, OTHER, TONE, MONO, MUT, BD, fmtNum, useWidth, Frame, btnSt } from './chart-kit.js';
import { AreaChart, LineChart, BarChart, HBarChart, Donut, Heatmap, Timeline } from './charts.js';
import { useData, pollFor, chartState, MemoryChart, StorageChart, svcColor, KIND_COLOR, KIND_LABEL } from './views.js';
import { GpuQueueW } from './gpu-queue.js';
import { PoolBars } from './mem-pools.js';
import { BentoGrid, SIZES, SIZE_LABEL, sizeOf, orderKeys, visibleKeys, isOn, setOn, useTileSize } from './bento.js';
import { NeedsW, needsCount, RunningW, runningCount, MemoryHeroW, ServicesW, statTile, jobStatusText, PATHS, Calm } from './overview-tiles.js';
import { TodayW, ChatsW, NextTaskNum, hasMod } from './overview-day.js';

export { jobStatusText, orderKeys };
const R = () => globalThis.React;
const RANGES = ['1h', '6h', '24h', '7d', '30d'];
const MODEL_KINDS = { llm: 'LLM', tts: 'TTS', stt: 'STT', voice: 'Voice', '3d': '3D', image: 'Image', video: 'Video', 'text-encoder': 'Text encoder', vae: 'VAE', lora: 'LoRA', vision: 'Vision', upscale: 'Upscale', other: 'Other' };
const dayLabel = key => { const d = new Date(key + 'T00:00:00'); return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }); };
const fitH = (min = 70) => { const { h: H } = useTileSize(); return Math.max(min, H || 150); };   // eslint-disable-line react-hooks/rules-of-hooks

// ---------- chart tiles ----------
function MemTimeW({ ctx, range, table }) {
  const H = fitH();
  return h(MemoryChart, { api: ctx.api, services: ctx.services, range, height: H, fit: H, table });
}

function MemNowW({ ctx, table }) {
  const m = ctx.memory, H = fitH(100);
  if (!m) return h(Frame, { state: 'loading', height: H });
  const items = m.by_service.filter(x => x.used_bytes > 0.01e9).sort((a, b) => b.used_bytes - a.used_bytes)
    .map(x => ({ key: x.id, label: ctx.services.find(s => s.id === x.id)?.name || x.id, value: x.used_bytes, color: svcColor(ctx.services, x.id) }));
  items.push({ key: 'other', label: 'Other', value: m.other_bytes, color: OTHER }, { key: 'free', label: 'Free', value: Math.max(0, m.total_bytes - m.used_bytes), color: 'var(--row,#1A2130)' });
  const donut = h(Donut, { items, unit: 'bytes', center: (m.used_bytes / 1e9).toFixed(1) + ' GB', sub: `of ${(m.total_bytes / 1e9).toFixed(0)} GB`, label: 'Memory now', table, size: Math.min(124, H - 8) });
  if ((m.pools || []).length < 2) return donut;               // one pool: GPUs share the RAM
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } }, donut, h(PoolBars, { memory: m, services: ctx.services }));   // plan 36.4
}

function GpuW({ ctx, range, table }) {
  // Dedicated cards (plan 36.4): each one's VRAM; else the shared GPU's GTT, as before.
  const cards = (ctx.memory?.pools || []).slice(1), names = cards.map(p => `gpu.${p.id.split(':')[1]}.mem_used`), H = fitH();
  const series = names.length ? names : ['gpu.gtt_used'];
  const d = useData(() => ctx.api.getMetrics({ series, range }), [ctx.api, range, series.join()], pollFor(range));
  if (d.state !== 'ok') return h(AreaChart, { ...chartState(d), height: H });
  if (!names.length) return h(AreaChart, { t: d.data.t, fit: H, unit: 'bytes', label: 'GPU memory (GTT)', table, series: [{ key: 'gtt', label: 'GTT used', values: d.data.series['gpu.gtt_used'] || [], color: SERIES[2] }] });
  return h(AreaChart, { t: d.data.t, fit: H, unit: 'bytes', label: 'GPU memory (VRAM)', table,
    series: cards.map((p, i) => ({ key: p.id, label: p.name, values: d.data.series[names[i]] || [], color: SERIES[(i + 2) % SERIES.length] })) });
}

function OutDayW({ ctx, table }) {
  const H = fitH(), d = useData(() => ctx.api.getOutputStats({ range: '30d', by: 'day' }), [ctx.api, ctx.outTick], 120000);
  if (d.state !== 'ok') return h(BarChart, { ...chartState(d), height: H });
  const b = d.data.buckets, kinds = Object.keys(KIND_COLOR).filter(k => b.some(x => x.by_kind[k]));
  return h(BarChart, { categories: b.map(x => { const [, m, dd] = x.key.split('-'); return `${+m}/${+dd}`; }), stacked: true, fit: H, unit: 'count', label: 'Outputs per day', table,
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
  const H = fitH(), d = useData(() => ctx.api.getActivityStats({ range }), [ctx.api, range], 300000);
  if (d.state !== 'ok') return h(Heatmap, { ...chartState(d), height: H });
  const days = [...new Set(d.data.cells.map(c => c.day))].sort();
  const rows = days.map(day => ({ label: dayLabel(day), cells: Array.from({ length: 24 }, (_, hr) => { const c = d.data.cells.find(x => x.day === day && x.hour === hr) || { count: 0, errors: 0 }; return { v: c.count, err: c.errors, tip: `${dayLabel(day)}, ${String(hr).padStart(2, '0')}:00` }; }) }));
  return h(Heatmap, { rows, cols: Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')), label: 'Activity by hour', table });
}

// Any widget a mod declares (§11.7 WidgetData); relay's `traffic` is the LLM traffic tile.
function ModW({ ctx, info, range, table }) {
  const H = fitH(), d = useData(() => ctx.api.getWidget(info.service, info.id, { range }), [ctx.api, info.service, info.id, range], pollFor(range));
  const label = info.title;
  if (d.state !== 'ok') return h(LineChart, { ...chartState(d), height: H, label });
  const w = d.data, unit = w.unit, series = w.series.map((s, i) => ({ key: s.name, label: s.name, values: s.values, axis: s.axis || 'left', color: SERIES[i % SERIES.length], type: info.kind === 'bar' && (s.axis || 'left') === 'right' ? 'line' : undefined }));
  if (info.kind === 'table') return h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 11.5 } },
    h('thead', null, h('tr', null, Object.keys(w.rows?.[0] || {}).map(k => h('th', { key: k, style: { textAlign: 'left', padding: '3px 6px', color: MUT, fontSize: 10.5 } }, k)))),
    h('tbody', null, (w.rows || []).map((r, i) => h('tr', { key: i }, Object.values(r).map((v, j) => h('td', { key: j, style: { padding: '3px 6px', borderTop: '1px solid ' + BD, fontFamily: typeof v === 'number' ? MONO : undefined } }, String(v)))))));
  if (info.kind === 'number') { const v = w.series[0]?.values.at(-1); return h('div', { style: { fontFamily: MONO, fontSize: 22, fontWeight: 600 } }, v == null ? '—' : fmtNum(v), h('span', { style: { fontSize: 12, color: MUT, marginLeft: 6 } }, unit && unit !== 'count' ? unit : '')); }
  if (info.kind === 'donut') return h(Donut, { items: (w.categories || []).map((c, i) => ({ key: c, label: c, value: w.series[0]?.values[i] || 0 })), unit, label, table, size: Math.min(120, H - 8) });
  const Comp = info.kind === 'area' ? AreaChart : info.kind === 'bar' ? BarChart : LineChart;
  return h(Comp, { t: w.t, categories: w.t ? undefined : w.categories, series, unit, fit: H, label, table });
}

function JobsW({ ctx, range, table }) {
  const d = useData(() => ctx.api.getJobStats({ range }), [ctx.api, range], 120000);
  const name = id => ctx.services.find(s => s.id === id)?.name || id;
  if (d.state !== 'ok') return h(HBarChart, { ...chartState(d), height: 90 });
  const b = d.data.by_service;
  if (table) return h(HBarChart, { categories: b.map(x => name(x.service)), unit: 'seconds', table: true, label: 'Job durations', series: [{ key: 'n', label: 'Jobs', values: b.map(x => x.count) }, { key: 'f', label: 'Failed', values: b.map(x => x.failed) }, { key: 'p50', label: 'p50', values: b.map(x => x.p50_s) }, { key: 'p90', label: 'p90', values: b.map(x => x.p90_s) }, { key: 'max', label: 'Max', values: b.map(x => x.max_s) }] });
  return h(HBarChart, { categories: b.map(x => name(x.service)), unit: 'seconds', label: 'Job duration p50 and p90',
    series: [{ key: 'p50', label: 'p50', values: b.map(x => x.p50_s), color: SERIES[0] }, { key: 'p90', label: 'p90', values: b.map(x => x.p90_s), color: SERIES[1] }] });
}

function StorageW({ ctx, table }) {
  const H = fitH(), d = useData(() => ctx.api.listModels(), [ctx.api], 300000);
  if (d.state !== 'ok') return h(Frame, { state: d.state, error: d.error, onRetry: d.retry, height: H });
  return h(StorageChart, { totals: d.data.totals, disk: d.data.disk, kinds: MODEL_KINDS, height: Math.max(60, H - 26), table, onPick: () => ctx.go('#/models') });
}

function UptimeW({ ctx, table }) {
  const d = useData(() => ctx.api.getTimeline({ range: '24h' }), [ctx.api], 60000);
  const name = id => ctx.services.find(s => s.id === id)?.name || id;
  if (d.state !== 'ok') return h(Timeline, { ...chartState(d), lanes: ctx.services.map(s => ({ key: s.id })), laneH: 18 });
  return h(Timeline, { from: d.data.from, to: d.data.to, label: 'Service uptime, 24 hours', table, laneH: 18, labelW: 92, minWidth: 300,
    lanes: d.data.lanes.map(l => ({ key: l.service, label: name(l.service), href: '#/s/' + l.service, states: l.states, loaded: l.loaded, jobs: [], outputs: [], events: l.events.filter(e => e.level === 'error') })),
    onOpen: (k, x, lane) => ctx.go('#/s/' + lane.key + '/logs') });
}

function RecentW({ ctx }) {
  if (!ctx.recent.length) return h(Calm, { icon: PATHS.image, text: 'Nothing made yet', tone: 'dim' });
  return h('div', { style: { display: 'grid', gridAutoFlow: 'column', gridAutoColumns: 'minmax(96px,1fr)', gap: 8, height: '100%', overflowX: 'auto' } }, ctx.recent.slice(0, 8).map(o => h('a', { key: o.id, href: '#/outputs/' + o.id, title: o.title, style: { display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, borderRadius: 7, overflow: 'hidden', border: '1px solid ' + BD, color: 'var(--tx,#E6EAF2)', textDecoration: 'none', background: 'var(--inset,#131926)' } },
    h('span', { style: { position: 'relative', flex: '1 1 0', minHeight: 0, display: 'grid', placeItems: 'center', background: 'var(--row,#1A2130)', color: KIND_COLOR[o.kind] || MUT, fontSize: 11, fontWeight: 600 } },
      o.preview && o.kind !== 'audio' ? h('img', { src: o.preview, alt: '', loading: 'lazy', style: { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' } }) : (KIND_LABEL[o.kind] || o.kind).toUpperCase()),
    h('span', { style: { padding: '3px 6px', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 'none' } }, o.title))));
}

function ActivityW({ ctx }) {
  const React = R(), [lvl, setLvl] = React.useState('all');
  const list = ctx.activity.filter(a => lvl === 'all' || a.level === lvl || (lvl === 'warn' && a.level === 'error')).slice(0, 30);
  const chip = (k, l) => h('button', { key: k, type: 'button', 'aria-pressed': lvl === k, onClick: () => setLvl(k), style: { height: 20, padding: '0 8px', borderRadius: 99, fontSize: 11, cursor: 'pointer', border: '1px solid ' + (lvl === k ? 'var(--cy,#58C4DD)' : 'var(--bds,#2A3547)'), background: lvl === k ? 'var(--tcy,rgba(88,196,221,.13))' : 'transparent', color: lvl === k ? 'var(--tx,#E6EAF2)' : MUT } }, l);
  const clock = ts => { const d = new Date(ts * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('div', { role: 'group', 'aria-label': 'Level', style: { display: 'flex', gap: 4 } }, chip('all', 'All'), chip('warn', 'Problems'), chip('error', 'Errors')),
    list.length ? h('div', { style: { display: 'flex', flexDirection: 'column' } }, list.map((a, i) => {
      const c = a.level === 'error' ? TONE.red : a.level === 'warn' ? TONE.accent : MUT;
      const text = h('span', { title: a.text, style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, a.text);
      return h('div', { key: a.id, style: { display: 'flex', alignItems: 'center', gap: 8, height: 24, borderTop: i ? '1px solid ' + BD : 0, fontSize: 11.5, minWidth: 0 } },
        h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: MUT, flex: 'none' } }, clock(a.ts)),
        h('span', { 'aria-label': a.level, style: { width: 6, height: 6, borderRadius: 9, background: c, flex: 'none' } }),
        a.route ? h('a', { href: a.route, style: { flex: 1, minWidth: 0, display: 'flex', color: 'var(--tx,#E6EAF2)' } }, text) : text);
    })) : h(Calm, { text: 'Nothing here', tone: 'dim' }));
}

// ---------- the tile list ----------
// key → { title, icon, size, sizes, ranges?, def?, href?, link?, areas, C | stat, off?, needs? (mods, any running), noTable? }
const STAT = ['xs'], LIST = ['s', 'm', 'w'], CHART = ['m', 'w', 'l', 'f'];
const BASE = [
  { key: 'needs', title: 'Needs you', icon: PATHS.bell, size: 's', sizes: LIST, areas: ['services'], C: NeedsW, noTable: true, count: needsCount },
  { key: 'running', title: 'Running now', icon: PATHS.play, size: 's', sizes: LIST, areas: ['services', 'events'], C: RunningW, noTable: true, count: runningCount },
  { key: 'memory-hero', title: 'Memory', icon: PATHS.memory, size: 's', sizes: ['s', 'w'], href: '#/settings/memory', areas: ['memory'], C: MemoryHeroW, noTable: true },
  { key: 'stat-services', title: 'Services ready', size: 'xs', sizes: STAT, areas: ['services'], stat: true },
  { key: 'stat-outputs', title: 'Outputs today', size: 'xs', sizes: STAT, areas: ['metrics'], stat: true },
  { key: 'stat-tokens', title: 'LLM tokens today', size: 'xs', sizes: STAT, areas: ['services'], stat: true },
  { key: 'stat-task', title: 'Next scheduled task', size: 'xs', sizes: STAT, areas: ['services'], C: ({ ctx }) => h(NextTaskNum, { ctx }), needs: ['agent'] },
  { key: 'stat-jobs', title: 'Jobs running', size: 'xs', sizes: STAT, areas: ['metrics', 'events'], stat: true, off: true },
  { key: 'stat-models', title: 'Models loaded', size: 'xs', sizes: STAT, areas: ['services'], stat: true, off: true },
  { key: 'services', title: 'Services', icon: PATHS.apps, size: 'm', sizes: ['m', 'w'], link: '#/services', areas: ['services'], C: ServicesW, noTable: true },
  { key: 'today', title: 'Today', icon: PATHS.calendar, size: 'm', sizes: ['m', 'w', 'l'], link: '#/calendar', areas: ['services'], C: TodayW, noTable: true, needs: ['calendar', 'agent'] },
  { key: 'chats', title: 'Recent chats', icon: PATHS.chat, size: 'm', sizes: ['m', 'w'], link: '#/chat/all', areas: ['services'], C: ChatsW, noTable: true, needs: ['agent'] },
  { key: 'memory', title: 'Memory over time', icon: PATHS.chart, size: 'l', sizes: CHART, ranges: RANGES, def: '6h', href: '#/settings/memory', areas: ['metrics'], C: MemTimeW },
  { key: 'activity', title: 'Activity', icon: PATHS.activity, size: 'm', sizes: ['m', 'w'], areas: ['events'], C: ActivityW, noTable: true },
  { key: 'recent', title: 'Recent outputs', icon: PATHS.image, size: 'f', sizes: ['w', 'l', 'f'], link: '#/outputs', href: '#/outputs', areas: ['outputs'], C: RecentW, noTable: true },
  { key: 'llm', title: 'LLM traffic', icon: PATHS.relay, size: 'w', sizes: CHART, ranges: ['24h', '7d'], def: '24h', areas: ['widgets'], mod: ['relay', 'traffic'] },
  { key: 'uptime', title: 'Service uptime (24 h)', icon: PATHS.clock, size: 'w', sizes: ['w', 'l', 'f'], areas: ['metrics'], C: UptimeW },
  { key: 'memory-now', title: 'Memory now', size: 'm', sizes: ['m', 'w'], areas: ['memory'], C: MemNowW, off: true },
  { key: 'gpu-queue', title: 'GPU queue', size: 'm', sizes: ['m', 'w'], ranges: ['24h', '7d'], def: '24h', areas: ['gpu', 'metrics'], C: GpuQueueW, off: true },  // plan 31.5
  { key: 'outputs-day', title: 'Outputs per day', size: 'w', sizes: CHART, href: '#/outputs', areas: ['metrics'], C: OutDayW, off: true },
  { key: 'activity-heat', title: 'Activity heatmap', size: 'w', sizes: ['w', 'l', 'f'], ranges: ['7d', '14d'], def: '14d', areas: ['metrics'], C: HeatW, off: true },
  { key: 'jobs', title: 'Job durations', size: 'm', sizes: ['m', 'w'], ranges: ['24h', '7d', '30d'], def: '7d', areas: ['metrics', 'events'], C: JobsW, off: true },
  { key: 'storage', title: 'Model storage', icon: PATHS.layers, size: 'm', sizes: ['m', 'w'], href: '#/models', areas: ['models'], C: StorageW, off: true },
  { key: 'gpu', title: 'GPU memory', size: 'w', sizes: CHART, ranges: RANGES, def: '6h', areas: ['metrics'], C: GpuW, off: true },
  { key: 'outputs-service', title: 'Outputs by service', size: 'm', sizes: ['m', 'w'], ranges: ['24h', '7d', '30d'], def: '7d', href: '#/outputs', areas: ['metrics'], C: OutSvcW, off: true },
];
export const DEFAULT_KEYS = BASE.map(w => w.key);

// The tile list for this install: the built-ins (LLM traffic only while relay declares it) plus one per mod
// widget, off until turned on. `services` drops tiles whose mods (`needs`) aren't running.
export function widgetDefs(widgets = [], services = null) {
  const defs = [], relay = widgets.find(w => w.service === 'relay' && w.id === 'traffic');
  for (const w of BASE) {
    if (w.mod) { if (relay) defs.push({ ...w, ranges: relay.ranges, def: relay.ranges[0], info: relay, href: '#/s/relay' }); continue; }
    if (w.needs && services && !w.needs.some(id => hasMod(services, id))) continue;
    defs.push(w);
  }
  for (const w of widgets) if (w !== relay) {
    const size = w.span >= 12 ? 'f' : w.span >= 8 ? 'l' : w.span >= 6 ? 'w' : 'm';
    defs.push({ key: `mod:${w.service}:${w.id}`, title: w.title, size, sizes: w.kind === 'number' ? ['xs', 's', 'm'] : CHART, ranges: w.ranges, def: w.ranges[0], href: '#/s/' + w.service, areas: ['widgets'], info: w, off: true, noTable: w.kind === 'number' });
  }
  return defs;
}

// ---------- customize ----------
function Customize({ defs, layout, onLayout, onClose, cols = 2 }) {
  const order = orderKeys(defs.map(d => d.key), layout.order);
  const row = k => {
    const d = defs.find(x => x.key === k), on = isOn(d, layout), size = sizeOf(d, layout), sizes = d.sizes || [d.size];
    return h('li', { key: k, style: { display: 'flex', alignItems: 'center', gap: 8, height: 30, borderBottom: '1px solid ' + BD, fontSize: 12.5, minWidth: 0 } },
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, cursor: 'pointer', color: on ? 'var(--tx,#E6EAF2)' : MUT } },
        h('input', { type: 'checkbox', checked: on, 'aria-label': `Show ${d.title}`, onChange: () => onLayout(setOn(layout, d, !on)) }),
        h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, d.title)),
      sizes.length > 1 ? h('select', { 'aria-label': `${d.title} size`, value: size, onChange: e => onLayout({ ...layout, sizes: { ...(layout.sizes || {}), [k]: e.target.value } }),
        style: { height: 24, fontSize: 11.5, borderRadius: 5, border: '1px solid var(--bds,#2A3547)', background: 'var(--inset,#131926)', color: 'var(--tx,#E6EAF2)' } },
      sizes.map(z => h('option', { key: z, value: z }, `${SIZE_LABEL[z]} ${SIZES[z].join('×')}`)))
        : h('span', { style: { fontSize: 11, color: MUT } }, SIZE_LABEL[size]));
  };
  return h('div', { role: 'dialog', 'aria-label': 'Customize dashboard', style: { background: 'var(--card,#11151D)', border: '1px solid var(--acc,#FFB224)', borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
      h('strong', { style: { fontSize: 13 } }, 'Customize'),
      h('span', { style: { fontSize: 11.5, color: MUT } }, 'Drag tiles to move them (or focus a grip and use the arrow keys). Pick sizes here or in a tile’s ⋯ menu.'),
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', onClick: () => onLayout({ order: [], hidden: [], shown: [], sizes: {}, ranges: {} }), style: btnSt }, 'Reset'),
      h('button', { type: 'button', onClick: onClose, style: { ...btnSt, background: 'var(--acc,#FFB224)', color: '#1A1200', borderColor: 'transparent', fontWeight: 600 } }, 'Done')),
    h('ul', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'grid', gridAutoFlow: 'column', gridTemplateColumns: `repeat(${cols},minmax(0,1fr))`, gridTemplateRows: `repeat(${Math.ceil(order.length / cols)},auto)`, columnGap: 24 } }, order.map(row)));
}

// ---------- dashboard ----------
// props: api, services, memory, gpu (GpuState) and cancelGpu(id) (plan 31.5), jobs, activity, recent, alerts, approvals, memReview,
// onApprovals, hist1, hist24, widgets (WidgetInfo[]), layout ({order, hidden, shown, sizes, ranges}), onLayout, customizing,
// onCustomize, go, badge, compact, outTick
export function Dashboard(props) {
  const React = R(), [ref, width] = useWidth(1200), [tables, setTables] = React.useState({});
  const { layout = {}, onLayout, api, customizing } = props;
  const ctx = { alerts: [], approvals: [], memReview: 0, ...props };
  const defs = widgetDefs(props.widgets || [], props.services);
  const keys = visibleKeys(defs, layout), order = orderKeys(defs.map(d => d.key), layout.order);
  const tiles = keys.map(k => {
    const d = defs.find(x => x.key === k), size = sizeOf(d, layout), table = !!tables[k];
    const range = layout.ranges?.[k] && d.ranges?.includes(layout.ranges[k]) ? layout.ranges[k] : d.def;
    const mock = (d.areas || []).some(a => api.isLive && !api.isLive(a));
    const badge = d.count ? d.count(ctx) : {};
    return { key: k, title: d.title, icon: d.icon, size, sizes: d.sizes || [d.size], ranges: d.ranges, range, href: d.href, link: d.link, mock, table, count: badge.count, tone: badge.tone,
      onTable: d.noTable ? undefined : v => setTables(t => ({ ...t, [k]: v })),
      onRange: r => onLayout({ ...layout, ranges: { ...layout.ranges, [k]: r } }),
      onSize: z => onLayout({ ...layout, sizes: { ...(layout.sizes || {}), [k]: z } }),
      onHide: () => onLayout(setOn(layout, d, false)),
      render: () => (d.stat ? statTile(k, ctx) : d.info ? h(ModW, { ctx, info: d.info, range, table }) : h(d.C, { ctx, range, table, size })) };
  });
  return h('div', { ref, style: { display: 'flex', flexDirection: 'column', gap: props.compact ? 10 : 14, minWidth: 0 } },
    customizing && h(Customize, { defs, layout, onLayout, onClose: () => props.onCustomize(false), cols: width < 760 ? 1 : width < 1100 ? 2 : 3 }),
    tiles.length ? h(BentoGrid, { tiles, width, compact: props.compact !== false, editing: customizing, order, onOrder: o => onLayout({ ...layout, order: o }) })
      : h(Frame, { state: 'empty', height: 120, emptyText: 'Every tile is hidden. Use Customize to show some.' }));
}
