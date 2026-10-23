// `show` in Chat (plan 47.2): the agent's chart, table or pictures (agent/show.py's checked spec, `data.show` on the
// tool_result), drawn under the turn's fold with the dashboard's own charts (web/charts.js): the site's series
// colours, tooltips, legends, "View as table", loading and error states. A file source is read here; AIHub's own
// data is fetched here and kept current every 30 s while the chat is open.

import { h, T } from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import { OutputBlock } from './chat-results.js';
import { DataTable, numberOf, tableOf } from './chat-table.js';
import { LineChart, AreaChart, BarChart, HBarChart, Donut, Heatmap, KpiTile } from '../charts.js';

const R = () => globalThis.React;
const MAX_POINTS = 500;
const CHARTS = { line: LineChart, area: AreaChart, bar: BarChart };

// ---------- the pure parts (tested in utils/tests/web/chat-show.test.mjs) ----------

/** Every `n`th row so a chart keeps at most `max` points (the last row always kept). */
export function sample(rows, max = MAX_POINTS) {
  if (rows.length <= max) return rows;
  const step = rows.length / max, out = [];
  for (let i = 0; i < max - 1; i++) out.push(rows[Math.floor(i * step)]);
  out.push(rows[rows.length - 1]);
  return out;
}

/** A file's table → chart data: {x, series} from its x and y columns. */
export function chartFromTable(columns, rows, x, ys) {
  const xi = columns.indexOf(x), picked = sample(rows);
  return { x: picked.map(r => String(r[xi] ?? '')), series: ys.map(y => { const j = columns.indexOf(y); return { name: y, values: picked.map(r => numberOf(r[j])) }; }) };
}

/** `show`'s spec + its data → the chart component's props. */
export function chartProps(view, d, unit) {
  const series = d.series.map(s => ({ key: s.name, label: s.name, values: s.values, unit: s.unit || unit }));
  if (view === 'hbar') return { categories: d.x, series, unit };
  return { categories: d.x, series, unit, type: view === 'bar' ? 'bar' : view === 'area' ? 'area' : 'line' };
}

/** A metric series' name → a person's words: mem.svc.comfy → "Images & Video". */
export function seriesLabel(name, names = {}) {
  const m = /^mem\.svc\.(.+)$/.exec(name);
  if (m) return names[m[1]] || m[1];
  if (name === 'mem.used') return 'Used';
  return name.replace(/^svc\.[^.]+\.stat\./, '').replace(/_/g, ' ');
}

const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'stat';

/** Loads what a hub source shows: {kind: 'xy'|'hbar'|'bar', props}. */
export async function loadHub(api, hub) {
  if (hub.name === 'memory') {
    const [m, svcs] = await Promise.all([api.getMetrics({ series: 'mem.svc.*', range: hub.range }), api.listServices().catch(() => [])]);
    const names = Object.fromEntries((svcs || []).map(s => [s.id, s.name]));
    const series = Object.entries(m.series || {}).filter(([, v]) => v.some(x => x)).map(([k, v]) => ({ key: k, label: seriesLabel(k, names), values: v }));
    return { kind: 'area', props: { t: m.t, series, unit: 'bytes', stacked: true } };
  }
  if (hub.name === 'outputs_per_day') {
    const r = await api.getOutputStats({ range: hub.range === '1h' || hub.range === '6h' || hub.range === '24h' ? '7d' : hub.range, by: 'day' });
    const kinds = [...new Set((r.buckets || []).flatMap(b => Object.keys(b.by_kind || {})))];
    return { kind: 'bar', props: { categories: r.buckets.map(b => b.key.slice(5)), stacked: true, series: kinds.map(k => ({ key: k, label: k, values: r.buckets.map(b => (b.by_kind || {})[k] || 0) })) } };
  }
  if (hub.name === 'job_times') {
    const r = await api.getJobStats({ range: hub.range === '1h' || hub.range === '6h' ? '24h' : hub.range });
    const rows = r.by_service || [];
    return { kind: 'hbar', props: { categories: rows.map(s => s.service), unit: 'seconds', series: [{ key: 'p50', label: 'Typical (p50)', values: rows.map(s => s.p50_s) }, { key: 'p90', label: 'Slow (p90)', values: rows.map(s => s.p90_s) }] } };
  }
  if (hub.name === 'mod_stat') {
    const name = `svc.${hub.mod}.stat.${slug(hub.stat)}`, m = await api.getMetrics({ series: name, range: hub.range });
    return { kind: 'line', props: { t: m.t, series: [{ key: name, label: hub.stat, values: (m.series || {})[name] || [] }] } };
  }
  throw new Error('unknown source ' + hub.name);
}

// ---------- the card ----------

function useLoad(fn, deps, every = 0) {
  const React = R(), [st, setSt] = React.useState({ state: 'loading' });
  React.useEffect(() => {
    let alive = true, t = 0;
    const go = () => fn().then(d => alive && setSt({ state: 'ok', data: d }), e => alive && setSt({ state: 'error', error: e.detail || e.message || String(e) }));
    go();
    if (every) t = setInterval(go, every);
    return () => { alive = false; clearInterval(t); };
  }, deps);
  return st;
}

function Chart({ view, data, unit, title, table }) {
  if (view === 'hbar') return h(HBarChart, { ...chartProps(view, data, unit), label: title, table, height: Math.max(90, data.x.length * 26) });
  if (view === 'donut') return h(Donut, { items: data.items.map(i => ({ key: i.label, label: i.label, value: i.value })), unit, label: title, table });
  if (view === 'kpi') return h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 } },
    data.items.map(i => h(KpiTile, { key: i.label, label: i.label, value: i.value, unit: i.unit || unit, sub: i.sub })));
  if (view === 'heatmap') return h(Heatmap, { rows: data.rows.map((r, j) => ({ label: r, cells: data.values[j].map(v => ({ v })) })), cols: data.columns, label: title, table });
  const C = CHARTS[view] || LineChart;
  return h(C, { ...chartProps(view, data, unit), label: title, table, height: 170 });
}

function FileView({ spec, ctx }) {
  const f = spec.file;
  const st = useLoad(async () => {
    const r = await fetch(`/api/outputs/${encodeURIComponent(f.output_id)}/file`);
    if (!r.ok) throw new Error(`the file isn't there (HTTP ${r.status})`);
    return tableOf(await r.text(), (r.headers.get('content-type') || '').includes('json') ? 'x.json' : 'x.csv');
  }, [f.output_id]);
  if (st.state !== 'ok') return h('div', { style: { fontSize: 12.5, color: st.state === 'error' ? T.rd : T.mut, padding: '8px 0' } }, st.state === 'error' ? st.error : 'Reading the file…');
  const [cols, rows] = st.data;
  if (spec.view === 'table') { const keep = (f.show || cols).map(c => cols.indexOf(c)); return h(DataTable, { columns: keep.map(i => cols[i]), rows: rows.map(r => keep.map(i => r[i])), ctx, title: spec.title }); }
  if (spec.view === 'donut' || spec.view === 'kpi') {
    const xi = cols.indexOf(f.x), yi = cols.indexOf(f.y[0]);
    return h(Chart, { view: spec.view, data: { items: rows.slice(0, 12).map(r => ({ label: String(r[xi]), value: numberOf(r[yi]) || 0 })) }, unit: spec.unit, title: spec.title });
  }
  return h(Chart, { view: spec.view, data: chartFromTable(cols, rows, f.x, f.y), unit: spec.unit, title: spec.title });
}

function HubView({ spec, ctx }) {
  const st = useLoad(() => loadHub(ctx.api, spec.hub), [JSON.stringify(spec.hub)], 30000);
  if (st.state !== 'ok') return h(LineChart, { state: st.state, error: st.error, height: 170 });
  const { kind, props } = st.data, C = kind === 'hbar' ? HBarChart : kind === 'bar' ? BarChart : kind === 'area' ? AreaChart : LineChart;
  return h(C, { ...props, label: spec.title, height: kind === 'hbar' ? Math.max(90, (props.categories || []).length * 26) : 170 });
}

function ShowCard({ ctx }) {
  const spec = ctx.liveCard?.row?.item?.result?.data?.show;
  if (!spec) return null;
  let body;
  if (spec.outputs) {
    const outs = spec.outputs.map(id => (ctx.outputs || []).find(o => o.output_id === id)).filter(Boolean);
    body = spec.view === 'image' && outs[0] ? h(OutputBlock, { output: outs[0], ctx, cap: 420 })
      : h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 } },
        outs.map(o => h('button', { key: o.output_id, type: 'button', title: `#${o.n} ${o.title || ''}`, onClick: () => ctx.openOutput?.(o.output_id),
          style: { position: 'relative', padding: 0, border: '1px solid ' + T.bd, borderRadius: 6, overflow: 'hidden', background: T.inset, aspectRatio: '1', cursor: 'zoom-in' } },
          o.preview || (o.kind === 'image' && o.url) ? h('img', { src: o.preview || o.url, alt: o.title || '', loading: 'lazy', style: { width: '100%', height: '100%', objectFit: 'cover', display: 'block' } }) : h('span', { style: { color: T.mut, fontSize: 12 } }, o.kind),
          h('span', { style: { position: 'absolute', left: 4, top: 4, padding: '0 5px', borderRadius: 3, background: T.card, fontSize: 10.5, fontWeight: 600, color: T.pu } }, '#' + o.n))));
  } else if (spec.file) body = h(FileView, { spec, ctx });
  else if (spec.hub) body = h(HubView, { spec, ctx });
  else if (spec.view === 'table') body = h(DataTable, { columns: spec.data.columns, rows: spec.data.rows, ctx, title: spec.title });
  else body = h(Chart, { view: spec.view, data: spec.data, unit: spec.unit, title: spec.title });
  return h('div', { style: { border: '1px solid ' + T.bd, background: T.card, borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    spec.title ? h('div', { style: { fontWeight: 600, fontSize: 13 } }, spec.title, spec.hub ? h('span', { style: { fontWeight: 400, color: T.dim, fontSize: 11.5, marginLeft: 8 } }, `live · ${spec.hub.range}`) : null) : null,
    body,
    spec.caption ? h('div', { style: { fontSize: 12, color: T.mut } }, spec.caption) : null);
}

registerCard('live:show', ({ ctx }) => h(ShowCard, { ctx }));
