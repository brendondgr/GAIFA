// Tools' default views (plan 46.1): a tool that declares `view` (utils/tools/views.py) has its result drawn as a table
// or a chart under the fold when no card is registered for it: gen3d's jobs, the models, the sessions, the engines…
// A result too big for the chat's event (over 8 KB: {truncated, preview, full}) is read whole from the hub.

import { h, T } from './chat-ui.js';
import { DataTable } from './chat-table.js';
import { LineChart, AreaChart, BarChart, HBarChart, Donut } from '../charts.js';

const R = () => globalThis.React;

/** A tool's declared view from the catalog, or null. */
export const viewOf = (tools, name) => (tools || []).find(t => t.name === name)?.view || null;

/** A dotted path in an object ('' → the object). */
export function getPath(obj, path) {
  if (!path) return obj;
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

/** A cell as the view's format says: time, bytes, seconds, gb, list, yesno. */
export function fmtCell(v, format) {
  if (v == null || v === '') return '';
  if (format === 'time' && typeof v === 'number') { const d = new Date(v * 1000); return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  if (format === 'bytes' && typeof v === 'number') return v >= 1e9 ? (v / 1e9).toFixed(1) + ' GB' : v >= 1e6 ? Math.round(v / 1e6) + ' MB' : Math.round(v / 1e3) + ' KB';
  if (format === 'gb' && typeof v === 'number') return v.toFixed(1) + ' GB';
  if (format === 'seconds' && typeof v === 'number') return v < 60 ? Math.round(v) + ' s' : Math.floor(v / 60) + 'm ' + Math.round(v % 60) + 's';
  if (format === 'list' && Array.isArray(v)) return v.map(x => (typeof x === 'object' ? x.id || x.name || JSON.stringify(x) : String(x))).join(', ');
  if (format === 'yesno') return v ? 'yes' : 'no';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

/** The rows of a result as the view picks them. */
export function rowsOf(view, result) {
  const r = getPath(result, view.rows);
  return Array.isArray(r) ? r : [];
}

/** A table view → {columns, rows} for DataTable. Without declared columns: the first row's plain keys, up to 8. */
export function tableFromView(view, result) {
  const rows = rowsOf(view, result);
  const cols = view.columns || Object.keys(rows[0] || {}).filter(k => rows.every(r => r[k] == null || typeof r[k] !== 'object')).slice(0, 8).map(k => ({ key: k, label: k }));
  return { columns: cols.map(c => c.label), rows: rows.map(r => cols.map(c => { const v = getPath(r, c.key); return c.format ? fmtCell(v, c.format) : v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : v; })) };
}

/** A chart view → {x, series}. */
export function chartFromView(view, result) {
  const rows = rowsOf(view, result);
  return { x: rows.map(r => String(getPath(r, view.x) ?? '')), series: view.y.map(k => ({ key: k, label: k, values: rows.map(r => { const v = Number(getPath(r, k)); return Number.isFinite(v) ? v : null; }) })) };
}

/** The tool's result: from the event, or the whole of it from the hub when the event holds only a preview. */
function useResult(ev) {
  const React = R();
  const inEvent = React.useMemo(() => {
    if (ev?.result && typeof ev.result === 'object') return ev.result;
    try { const b = JSON.parse(ev?.content || 'null'); return b && typeof b === 'object' ? b.result ?? null : null; } catch { return null; }
  }, [ev]);
  const [full, setFull] = React.useState(null);
  const truncated = inEvent && inEvent.truncated && ev?.call_id;
  React.useEffect(() => {
    if (!truncated) return undefined;
    let alive = true;
    (async () => {
      let text = '', offset = 0;
      for (let i = 0; i < 50; i++) {
        const r = await fetch(`/api/tools/calls/${encodeURIComponent(ev.call_id)}/result?offset=${offset}&limit=100000`);
        if (!r.ok) return;
        const p = await r.json();
        text += p.text; offset += p.text.length;
        if (offset >= p.total || !p.text) break;
      }
      try { if (alive) setFull(JSON.parse(text)); } catch { /* not JSON */ }
    })();
    return () => { alive = false; };
  }, [truncated]);
  return truncated ? full : inEvent;
}

export function ViewCard({ row, view, ctx }) {
  const result = useResult(row.item?.result);
  if (!result) return null;
  let body;
  if (view.kind === 'table') { const t = tableFromView(view, result); if (!t.rows.length) return null; body = h(DataTable, { columns: t.columns, rows: t.rows, ctx, title: view.title || row.name }); }
  else {
    const d = chartFromView(view, result);
    if (!d.x.length) return null;
    const C = view.kind === 'hbar' ? HBarChart : view.kind === 'line' ? LineChart : view.kind === 'area' ? AreaChart : BarChart;
    body = view.kind === 'donut' ? h(Donut, { items: d.x.map((x, i) => ({ key: x, label: x, value: d.series[0].values[i] || 0 })), unit: view.unit })
      : h(C, { categories: d.x, series: d.series, unit: view.unit, height: view.kind === 'hbar' ? Math.max(90, d.x.length * 24) : 170 });
  }
  return h('div', { style: { border: '1px solid ' + T.bd, background: T.card, borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    view.title ? h('div', { style: { fontWeight: 600, fontSize: 13 } }, view.title) : null, body);
}
