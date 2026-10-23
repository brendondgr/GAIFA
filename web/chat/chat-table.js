// Tables in Chat (plan 47.2), for `show`'s table view and tools' default table views (plan 46.1): sort by a column
// (numbers as numbers), a filter box, 50 rows a page, Copy as CSV, and Save as output (a CSV through
// POST /api/outputs/upload, so it gets a #n that later steps can use). Theme tokens only.

import { h, T, MONO } from './chat-ui.js';

const R = () => globalThis.React;
export const PAGE = 50;

/** A cell as a number when it reads as one ("1,204", "12.5%", 3), else null. */
export function numberOf(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (v == null) return null;
  const s = String(v).trim().replace(/,/g, '').replace(/%$/, '');
  return s !== '' && /^-?\d*\.?\d+(e-?\d+)?$/i.test(s) ? Number(s) : null;
}

/** Rows sorted by column `i` (numbers numerically, text by locale), `dir` 1 or -1; nulls last. */
export function sortRows(rows, i, dir = 1) {
  if (i == null) return rows;
  const num = rows.every(r => r[i] == null || r[i] === '' || numberOf(r[i]) != null);
  return rows.slice().sort((a, b) => {
    const x = a[i], y = b[i];
    if (x == null || x === '') return 1;
    if (y == null || y === '') return -1;
    return dir * (num ? numberOf(x) - numberOf(y) : String(x).localeCompare(String(y), undefined, { numeric: true }));
  });
}

/** Rows with any cell containing every word of `q` (case-insensitive). */
export function filterRows(rows, q) {
  const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter(r => { const s = r.map(c => (c == null ? '' : String(c))).join(' ').toLowerCase(); return words.every(w => s.includes(w)); });
}

/** CSV text, quoting what needs it. */
export function toCsv(columns, rows) {
  const q = v => { const s = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  return [columns, ...rows].map(r => r.map(q).join(',')).join('\n') + '\n';
}

/** CSV text → [columns, rows] (quotes, doubled quotes and newlines inside quotes). */
export function parseCsv(text) {
  const out = [];
  let row = [], cell = '', inQ = false;
  const s = String(text || '').replace(/^﻿/, '');
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQ) {
      if (c === '"' && s[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') inQ = false; else cell += c;
    } else if (c === '"') inQ = true;
    else if (c === ',') { row.push(cell); cell = ''; } else if (c === '\n' || c === '\r') {
      if (c === '\r' && s[i + 1] === '\n') i++;
      row.push(cell); cell = ''; if (row.length > 1 || row[0] !== '') out.push(row); row = [];
    } else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); out.push(row); }
  return [(out[0] || []).map(c => c.trim()), out.slice(1)];
}

/** A CSV or JSON file's text → [columns, rows]. */
export function tableOf(text, name = '') {
  const t = String(text || '').trim();
  if (/\.json$/i.test(name) || t.startsWith('[') || t.startsWith('{')) {
    const o = JSON.parse(t);
    if (o && Array.isArray(o.columns)) return [o.columns.map(String), o.rows || []];
    if (Array.isArray(o) && o.length && typeof o[0] === 'object') { const cols = Object.keys(o[0]); return [cols, o.map(r => cols.map(c => r[c]))]; }
    throw new Error('not a table');
  }
  return parseCsv(t);
}

export function DataTable({ columns, rows, ctx, name = 'table', title }) {
  const React = R(), [sort, setSort] = React.useState({ i: null, dir: 1 }), [q, setQ] = React.useState(''), [page, setPage] = React.useState(0);
  const [saved, setSaved] = React.useState(null), [copied, setCopied] = React.useState(false);
  const shown = React.useMemo(() => sortRows(filterRows(rows, q), sort.i, sort.dir), [rows, q, sort]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE)), p = Math.min(page, pages - 1);
  const numCol = React.useMemo(() => columns.map((_, i) => rows.length > 0 && rows.every(r => r[i] == null || r[i] === '' || numberOf(r[i]) != null)), [columns, rows]);
  const copy = async () => { try { await globalThis.navigator?.clipboard?.writeText(toCsv(columns, shown)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { ctx?.toast?.('Copy failed', 'error'); } };
  const save = async () => {
    try {
      const fname = (title || name).replace(/[^\w.-]+/g, '-').toLowerCase().slice(0, 60) + '.csv';
      const o = await ctx.api.uploadOutput(new File([toCsv(columns, shown)], fname, { type: 'text/csv' }));
      setSaved(o); ctx.toast?.('Saved to Outputs', 'success');
    } catch (e) { ctx?.toast?.(e.detail || e.message || String(e), 'error'); }
  };
  const btn = (label, onClick, o = {}) => h('button', { type: 'button', onClick, disabled: o.disabled, style: { border: '1px solid ' + T.bds, borderRadius: 6, padding: '2px 9px', fontSize: 11.5, background: 'transparent', color: T.tx, cursor: o.disabled ? 'default' : 'pointer', opacity: o.disabled ? 0.5 : 1 } }, label);
  const th = { position: 'sticky', top: 0, background: T.card, textAlign: 'left', fontWeight: 600, fontSize: 11.5, color: T.mut, padding: '6px 8px', borderBottom: '1px solid ' + T.bds, cursor: 'pointer', whiteSpace: 'nowrap' };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' } },
      h('input', { type: 'search', value: q, placeholder: 'Filter', 'aria-label': 'Filter the rows', onChange: e => { setQ(e.target.value); setPage(0); },
        style: { height: 26, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, fontSize: 12, minWidth: 0, flex: '1 1 140px', maxWidth: 220 } }),
      h('span', { style: { fontSize: 11.5, color: T.dim } }, shown.length === rows.length ? `${rows.length} rows` : `${shown.length} of ${rows.length} rows`),
      h('span', { style: { flex: 1 } }),
      btn(copied ? 'Copied' : 'Copy as CSV', copy),
      ctx?.api?.uploadOutput ? (saved ? h('span', { style: { fontSize: 11.5, color: T.gr } }, 'Saved to Outputs') : btn('Save as output', save)) : null),
    h('div', { style: { overflow: 'auto', maxHeight: 360, border: '1px solid ' + T.bd, borderRadius: 6 } },
      h('table', { style: { borderCollapse: 'collapse', width: '100%', fontSize: 12.5 } },
        h('thead', null, h('tr', null, columns.map((c, i) => h('th', { key: i, scope: 'col', 'aria-sort': sort.i === i ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none',
          onClick: () => setSort(s => ({ i, dir: s.i === i ? -s.dir : 1 })), style: { ...th, textAlign: numCol[i] ? 'right' : 'left' } }, c, sort.i === i ? (sort.dir > 0 ? ' ▲' : ' ▼') : '')))),
        h('tbody', null, shown.slice(p * PAGE, (p + 1) * PAGE).map((r, j) => h('tr', { key: j }, columns.map((_, i) => h('td', { key: i,
          style: { padding: '5px 8px', borderTop: '1px solid ' + T.bd, textAlign: numCol[i] ? 'right' : 'left', fontFamily: numCol[i] ? MONO : undefined, whiteSpace: 'nowrap', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis' } },
          r[i] == null ? '' : typeof r[i] === 'object' ? JSON.stringify(r[i]) : String(r[i])))))))),
    pages > 1 ? h('div', { style: { display: 'flex', gap: 6, alignItems: 'center', fontSize: 11.5, color: T.mut } },
      btn('‹ Back', () => setPage(Math.max(0, p - 1)), { disabled: p === 0 }), `Page ${p + 1} of ${pages}`, btn('Next ›', () => setPage(Math.min(pages - 1, p + 1)), { disabled: p >= pages - 1 })) : null);
}
