// The Settings page's hub blocks (plan settings-redesign 1.3): the pieces that aren't one value, moved out of
// Hub.dc.html's template and vmSettings as React components. Each takes `{ctx, row}`: `ctx` is the page's
// (api, services, system, draft, setDraft, copy, toast, icons). Written by us (web/PATCHES.md).

import { h, T, MONO } from '../chat/chat-ui.js';
import { Toggle, cardSt, label11 } from './rows.js';
import { MemoryChart } from '../views.js';
import { overrideLines, showValue } from './schema.js';
import { settingsHash } from './route.js';
import { HardwareCard as Hardware } from '../hardware.js';
import { SessionsPanel } from '../sessions.js';
import { StatusCell } from './blocks-setup.js';

const R = () => globalThis.React;
const GB = 1e9;
export const fb = (b, d = 1) => { if (b == null || isNaN(b)) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0, v = b; while (v >= 1000 && i < 4) { v /= 1000; i++; } return (i === 0 ? v : v.toFixed(v >= 100 ? 0 : d)) + ' ' + u[i]; };
export const fdur = s => { if (s == null) return '—'; s = Math.max(0, Math.round(s)); if (s < 60) return s + 's'; if (s < 3600) return Math.floor(s / 60) + 'm'; if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm'; return Math.floor(s / 86400) + 'd ' + Math.floor(s % 86400 / 3600) + 'h'; };
const COPY = 'M9 9h11v11H9zM5 15V4h11', CHEV_U = 'M6 15l6-6 6 6', CHEV_D = 'M6 9l6 6 6-6', PUZZLE = 'M10 3h4v3a2 2 0 1 0 4 0V3h3v7h-3a2 2 0 1 0 0 4h3v7h-7v-3a2 2 0 1 0-4 0v3H3v-7h3a2 2 0 1 0 0-4H3V3z';
const svg = (d, size = 14, style) => h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style }, h('path', { d }));
const iconBtn = { width: 28, height: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 6, background: 'transparent', color: T.mut, cursor: 'pointer', flex: 'none' };
const card = (extra, ...kids) => h('section', { style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10, ...extra } }, ...kids);
const code = t => h('code', { style: { fontFamily: MONO, padding: '1px 5px', borderRadius: 4, background: T.inset } }, t);
const moveIn = (list, i, dir) => { const j = i + dir; if (j < 0 || j >= list.length) return list; const l = [...list]; [l[i], l[j]] = [l[j], l[i]]; return l; };

// ---------- pure views (tested in utils/tests/web/settings-blocks.test.mjs) ----------
export function processInfo(sys) {
  return sys ? [['Version', 'v' + sys.hub.version], ['PID', sys.hub.pid], ['Uptime', fdur(sys.hub.uptime_s)], ['Memory (RSS)', fb(sys.hub.rss_bytes)]].map(([k, v]) => ({ k, v: String(v) })) : [];
}
export function pathRows(sys) {
  if (!sys) return [];
  return [['Project root', sys.paths.root, ''], ['Models', sys.paths.models, fb(sys.usage.models_bytes)], ['Databases', sys.paths.databases, fb(sys.usage.databases_bytes)],
    ['Outputs', sys.paths.outputs, fb(sys.usage.outputs_bytes)], ...(sys.paths.logs ? [['Logs', sys.paths.logs, fb(sys.usage.logs_bytes)]] : []),
    ...(sys.paths.state ? [['State', sys.paths.state, fb(sys.usage.state_bytes)]] : [])].map(([k, p, sz]) => ({ k, p, sz }));
}
export function doctorView(rep, all) {
  if (!rep) return null;
  const c = rep.counts, s = n => (n === 1 ? '' : 's');
  return { summary: (c.fail ? `${c.fail} problem${c.fail > 1 ? 's' : ''}` : c.warn ? 'No problems' : 'All good') + ` · ${c.ok} ok, ${c.warn} warning${s(c.warn)}, ${c.note} note${s(c.note)}`,
    tone: c.fail ? 'fail' : c.warn ? 'warn' : 'ok', rows: rep.checks.filter(x => all || x.level !== 'ok'), total: rep.checks.length };
}
export const CLI = ['gaifa status', 'gaifa start <id>', 'gaifa logs <id> -f', 'gaifa new <id>', 'gaifa doctor'];

// ---------- blocks ----------
export function ProcessCard({ ctx }) {
  return card({}, h('h2', { style: { ...label11, marginBottom: 2 } }, 'GAIFA process'),
    h('dl', { style: { margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 12 } },
      processInfo(ctx.system).map(x => h('div', { key: x.k }, h('dt', { style: { fontSize: 12, color: T.mut } }, x.k), h('dd', { style: { margin: 0, fontFamily: MONO, fontSize: 15 } }, x.v)))));
}

export function PathsList({ ctx }) {
  const sys = ctx.system;
  return h('div', { style: { paddingBottom: 14 } },
    pathRows(sys).map(p => h('div', { key: p.k, style: { display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0', borderBottom: '1px solid ' + T.bd, flexWrap: 'wrap' } },
      h('div', { style: { flex: '1 1 260px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, p.k), h('div', { style: { fontFamily: MONO, fontSize: 12, color: T.mut, wordBreak: 'break-all' } }, p.p)),
      h('span', { style: { fontFamily: MONO, fontSize: 12.5 } }, p.sz),
      h('button', { type: 'button', 'aria-label': 'Copy path', onClick: () => ctx.copy?.(p.p, 'Path copied'), style: iconBtn }, svg(COPY)))),
    sys ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 14 } },
      h('div', { style: { display: 'flex', fontSize: 12.5 } }, h('span', { style: { fontWeight: 500 } }, 'Disk'), h('span', { style: { marginLeft: 'auto', fontFamily: MONO } }, `${fb(sys.disk.free_bytes)} free of ${fb(sys.disk.total_bytes)}`)),
      h('span', { style: { height: 8, borderRadius: 9, background: T.row, overflow: 'hidden', display: 'block' } },
        h('span', { style: { display: 'block', height: '100%', width: ((1 - sys.disk.free_bytes / sys.disk.total_bytes) * 100) + '%', background: T.cy, borderRadius: 9 } }))) : null);
}

export function MemoryHistory({ ctx }) {
  const res = ctx.draft?.memory?.reserve_gb, ok = String(res ?? '') !== '' && Number(res) >= 0 && Number(res) <= 64;
  return h('div', { style: { padding: '12px 0 4px' } }, h('div', { style: { ...label11, marginBottom: 6 } }, 'Last 24 hours'),
    h(MemoryChart, { api: ctx.api, services: ctx.services || [], range: '24h', height: 150, label: 'Memory, last 24 hours', reserveBytes: ok ? Number(res) * GB : undefined }));
}

/** Every folder in services/: enabled, autostart and sidebar order on the draft; broken mods with their errors. */
export function ServicesTable({ ctx }) {
  const d = ctx.draft, map = Object.fromEntries((ctx.services || []).map(s => [s.id, s])), set = ctx.setDraft;
  if (!d) return null;
  const ids = d.services.order.filter(id => map[id]), extra = ctx.toolCounts ? { label: 'Tools', value: id => (ctx.toolCounts[id] ? String(ctx.toolCounts[id]) : '—') } : null;
  const head = { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: T.mut };
  const col = w => ({ width: w, display: 'flex', justifyContent: 'center' });
  const move = (i, dir) => set(y => { y.services.order = moveIn(y.services.order.filter(z => map[z]), i, dir); });
  return h('section', { style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, overflow: 'hidden' } },
    h('div', { style: { display: 'flex', gap: 12, padding: '10px 16px', ...head } }, h('span', { style: { flex: 1 } }, 'Folders in services/'),
      extra ? h('span', { style: { width: 50, textAlign: 'center' } }, extra.label) : null,
      h('span', { style: { width: 60, textAlign: 'center' } }, 'On'), h('span', { style: { width: 64, textAlign: 'center' } }, 'Autostart'), h('span', { style: { width: 60, textAlign: 'center' } }, 'Order')),
    ids.map((id, i) => { const x = map[id], bad = (x.manifest_errors || []).length > 0;
      return h('div', { key: id, style: { display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', borderTop: '1px solid ' + T.bd, flexWrap: 'wrap' } },
        h('div', { style: { flex: '1 1 220px', minWidth: 0, display: 'flex', alignItems: 'center', gap: 10 } },
          svg(ctx.icons?.[x.icon] || ctx.icons?.puzzle || PUZZLE, 16, { flex: 'none', color: T.mut }),
          h('div', { style: { minWidth: 0 } }, h('a', { href: `#/s/${id}/settings`, style: { fontWeight: 500, color: T.tx } }, x.name), ' ',
            h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, `services/${id} · ${x.port ? ':' + x.port : '—'}`),
            bad ? h('div', { style: { fontFamily: MONO, fontSize: 11.5, color: T.rd } }, x.manifest_errors.join(' · ')) : null,
            h(StatusCell, { x, ctx }))),   // capability-enablement 3.5: its state in words, with what turns it on
        extra ? h('span', { style: { width: 50, textAlign: 'center', fontFamily: MONO, fontSize: 12, color: T.mut } }, extra.value(id)) : null,
        h('span', { style: col(60) }, h(Toggle, { label: 'On', on: d.services.enabled[id] ?? true, onChange: on => set(y => { y.services.enabled[id] = on; }) })),
        h('span', { style: col(64) }, h(Toggle, { label: 'Autostart', on: d.services.autostart[id] ?? false, onChange: on => set(y => { y.services.autostart[id] = on; }) })),
        h('span', { style: col(60) },
          h('button', { type: 'button', disabled: i === 0, 'aria-label': `Move ${x.name} up`, onClick: () => move(i, -1), style: { ...iconBtn, color: T.tx } }, svg(CHEV_U)),
          h('button', { type: 'button', disabled: i === ids.length - 1, 'aria-label': `Move ${x.name} down`, onClick: () => move(i, 1), style: { ...iconBtn, color: T.tx } }, svg(CHEV_D)))); }));
}

export function AddModCard() {
  return card({ border: '1px dashed ' + T.pu },
    h('h2', { style: { margin: 0, fontSize: 14, fontWeight: 600, color: T.pu } }, 'Add a mod'),
    h('ol', { style: { margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6 } },
      h('li', null, 'Create it from the template: ', code('gaifa new <id>')),
      h('li', null, 'Edit ', code('services/<id>/service.toml'), ' — name, run command, port, health path.'),
      h('li', null, 'Restart GAIFA. The mod gets a sidebar item, an overview tile, and API, Logs and Settings tabs with no UI code.')),
    h('a', { href: '#/s/example', style: { fontSize: 12.5 } }, 'See the Example mod and its page module →'));
}

export function Versions({ ctx }) {
  const v = [['GAIFA', 'v' + (ctx.system?.hub?.version || '0.1.0')], ...(ctx.services || []).map(x => [x.name, x.version ? 'v' + x.version : '—'])];
  return card({},
    h('p', { style: { margin: '0 0 4px', fontSize: 13 } }, h('strong', null, 'GAIFA'), ' ', h('span', { style: { color: T.mut } }, '· Great, Another Interface For Agents · say “guy-fuh”')),
    h('h2', { style: label11 }, 'Versions'),
    h('dl', { style: { margin: 0, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: '6px 14px', fontSize: 13 } },
      v.flatMap(([k, val], i) => [h('dt', { key: 'k' + i }, k), h('dd', { key: 'v' + i, style: { margin: 0, fontFamily: MONO, fontSize: 12, color: T.mut } }, val)])));
}

export function CliList({ ctx }) {
  return card({ gap: 8 }, h('h2', { style: label11 }, 'Command line'),
    CLI.map(c => h('div', { key: c, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 7, background: T.inset, fontFamily: MONO, fontSize: 12.5 } },
      h('span', { style: { color: T.mut } }, '$'), h('span', { style: { flex: 1, minWidth: 0, overflowX: 'auto', whiteSpace: 'nowrap' } }, c),
      h('button', { type: 'button', 'aria-label': 'Copy command', onClick: () => ctx.copy?.(c, 'Command copied'), style: { ...iconBtn, width: 26, height: 26 } }, svg(COPY, 13)))));
}

const LV = { fail: ['Problem', T.rd], warn: ['Warning', T.acc], note: ['Note', T.cy], ok: ['OK', T.gr] };
/** Doctor (plan 12.4): GET /api/doctor, the warn and fail checks with their fixes, Show all, Run again. */
export function DoctorPanel({ ctx, initial = null }) {
  const React = R(), [st, setSt] = React.useState({ report: initial, loading: !initial, err: null, all: false });
  const run = async () => {
    setSt(s => ({ ...s, loading: true, err: null }));
    try { const report = await ctx.api.getDoctor(); setSt(s => ({ ...s, report, loading: false })); } catch (e) { setSt(s => ({ ...s, loading: false, err: e })); }
  };
  React.useEffect(() => { if (!initial) run(); }, []);
  const rep = st.report, v = doctorView(rep, st.all);
  const btn = { height: 28, padding: '0 10px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer' };
  return h('section', { 'aria-label': 'Doctor', style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' } }, h('h2', { style: label11 }, 'Doctor'),
      v ? h('span', { style: { padding: '2px 8px', borderRadius: 99, fontSize: 11.5, fontWeight: 600, color: T.bg, background: LV[v.tone][1] } }, v.summary) : null,
      h('span', { style: { flex: 1 } }), h('span', { style: { fontSize: 12, color: T.mut } }, rep ? 'Checked ' + new Date(rep.ts * 1000).toLocaleTimeString() : ''),
      h('button', { type: 'button', onClick: run, disabled: st.loading, style: btn }, st.loading ? 'Checking…' : 'Run again')),
    h('div', { style: { fontSize: 12, color: T.mut } }, 'Models on disk, mod manifests, paths outside the project, ports, units, disk space and offline mods. The same report as ', h('code', null, 'gaifa doctor'), '.'),
    st.loading && !rep ? h('div', { style: { fontSize: 13, color: T.mut } }, 'Checking…') : null,
    st.err ? h('div', { role: 'alert', style: { fontSize: 13, color: T.rd } }, st.err.detail || String(st.err.message || st.err)) : null,
    v && !v.rows.length ? h('div', { style: { fontSize: 13 } }, 'Nothing needs attention.') : null,
    ...(v ? v.rows : []).map((c, i) => h('div', { key: i, style: { display: 'flex', gap: 10, padding: '8px 10px', borderRadius: 7, background: T.inset } },
      h('span', { 'aria-label': LV[c.level][0], style: { flex: '0 0 auto', width: 8, height: 8, marginTop: 5, borderRadius: 9, background: LV[c.level][1] } }),
      h('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 } },
        h('div', { style: { fontSize: 13 } }, h('span', { style: { color: T.mut, fontSize: 11.5, marginRight: 6 } }, c.area), c.title),
        c.detail ? h('div', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut, overflowWrap: 'anywhere' } }, c.detail) : null,
        c.fix ? h('div', { style: { fontSize: 12 } }, 'Fix: ' + c.fix) : null))),
    v ? h('button', { type: 'button', onClick: () => setSt(s => ({ ...s, all: !s.all })), style: { alignSelf: 'flex-start', border: 0, background: 'transparent', padding: 0, color: T.cy, fontSize: 12.5, cursor: 'pointer' } },
      st.all ? 'Hide passed checks' : `Show all ${v.total} checks`) : null);
}

export function HardwareCard({ ctx }) { return h(Hardware, { api: ctx.api }); }
export function SessionsBlock({ ctx }) {
  return h('section', { style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: 16 } }, h(SessionsPanel, { api: ctx.api, toast: ctx.toast, on: ctx.on }));
}

/** Reset the dashboard layout: the Overview's order, hidden and shown tiles, sizes and ranges back to the defaults ([ui.dashboard], saved at once). */
export function DashboardReset({ ctx }) {
  const dash = ctx.dash || {}, custom = (dash.order || []).length + (dash.hidden || []).length + (dash.shown || []).length + Object.keys(dash.sizes || {}).length + Object.keys(dash.ranges || {}).length > 0;
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0', borderTop: '1px solid ' + T.bd, flexWrap: 'wrap' } },
    h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, 'Dashboard layout'),
      h('div', { style: { fontSize: 12, color: T.mut } }, custom ? 'The Overview’s tiles are in your order, with some shown, hidden, resized or ranges changed.' : 'The Overview shows its default tiles, in the default order and sizes.')),
    h('button', { type: 'button', disabled: !custom, onClick: () => { ctx.onLayout?.({ order: [], hidden: [], shown: [], sizes: {}, ranges: {} }); ctx.toast?.('Dashboard layout reset', 'success'); },
      style: { height: 30, padding: '0 12px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 12.5, cursor: custom ? 'pointer' : 'not-allowed', opacity: custom ? 1 : 0.5 } }, 'Reset the dashboard layout'));
}

/** Set on this machine (5.1): the saved values that differ from the defaults, each a link to its row; Copy gives them as TOML. */
export function OverridesCard({ ctx }) {
  const list = ctx.overrides || [];
  return card({ gap: 8 },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } }, h('h2', { style: label11 }, 'Set on this machine'), h('span', { style: { flex: 1 } }),
      list.length ? h('button', { type: 'button', onClick: () => ctx.copy?.(overrideLines(list), 'Copied as TOML'),
        style: { height: 26, padding: '0 10px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 12, cursor: 'pointer' } }, 'Copy as TOML') : null),
    !ctx.defaults ? h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Reading the defaults…')
      : !list.length ? h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Nothing changed from the defaults.')
        : list.map(c => h('a', { key: c.ref, href: settingsHash(c.section, c.group, c.row), style: { display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '6px 10px', borderRadius: 7, background: T.inset, color: T.tx, textDecoration: 'none', fontSize: 12.5 } },
          h('span', { style: { fontFamily: MONO, fontSize: 12 } }, c.key), h('span', { style: { color: T.mut } }, '·'), h('span', null, showValue(c.rowDef, c.value)),
          h('span', { style: { color: T.mut, fontSize: 12 } }, `(default ${showValue(c.rowDef, c.default)})`))));
}

export const HUB_BLOCKS = { ProcessCard, PathsList, MemoryHistory, ServicesTable, AddModCard, Versions, CliList, DoctorPanel, HardwareCard, SessionsPanel: SessionsBlock, DashboardReset, OverridesCard };
export { cardSt };
