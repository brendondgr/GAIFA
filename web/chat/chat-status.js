// Status cards (plan 46.3): the hub's status tools draw as cards under the turn's fold (the `live:` slot of
// chat-live.js), not as JSON: memory with Unload, services with Start and Stop, the GPU queue with Cancel, the
// install checks with their fixes, and what Free GPU freed. Buttons call the hub's routes directly (you are
// acting, not the agent) and the card then shows the hub's state now; stopping or unloading something busy asks first.

import { h, T, MONO, Badge } from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import * as kit from '../live-kit.js';

const R = () => globalThis.React;
const GB = 1e9;
const gb = v => (v == null ? '—' : (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10) + ' GB');

// ---------- the pure parts (tested in utils/tests/web/status-cards.test.mjs) ----------

/** GET /api/memory → hub_memory_status's shape, so a refreshed card reads like the tool's result. */
export function memoryFromApi(m, names = {}) {
  return { total_gb: m.total_bytes / GB, used_gb: m.used_bytes / GB, available_gb: m.available_bytes / GB, reserve_gb: (m.reserve_bytes || 0) / GB,
    by_service: (m.by_service || []).map(s => ({ id: s.id, name: names[s.id] || s.id, used_gb: s.used_bytes / GB, estimate_gb: s.estimate_bytes ? s.estimate_bytes / GB : null, load: s.load })) };
}

/** The memory bar's parts: each mod's share (largest first), then free; widths in % of the total. */
export function memoryBar(r) {
  const total = Math.max(r.total_gb || 0, 0.001);
  const mods = (r.by_service || []).filter(s => s.used_gb > 0.05).sort((a, b) => b.used_gb - a.used_gb)
    .map((s, i) => ({ id: s.id, label: s.name, gb: s.used_gb, pct: s.used_gb / total * 100, color: kit.C && SERIES[i % SERIES.length] }));
  const other = Math.max(0, (r.used_gb || 0) - mods.reduce((a, s) => a + s.gb, 0));
  const out = [...mods];
  if (other > 0.1) out.push({ id: 'other', label: 'Other', gb: other, pct: other / total * 100, color: 'var(--other,#46526A)' });
  return out;
}
const SERIES = ['var(--s1,#58C4DD)', 'var(--s2,#FFB224)', 'var(--s3,#BC8CFF)', 'var(--s4,#3FB950)', 'var(--s5,#F78166)', 'var(--s6,#79C0FF)'];

/** A service's state as a dot colour and its words. */
export function stateTone(s) {
  if (s.state === 'ready') return s.busy ? ['var(--acc,#FFB224)', 'busy'] : ['var(--gr,#3FB950)', s.load === 'loaded' ? 'loaded' : 'ready'];
  if (s.state === 'failed') return ['var(--rd,#F85149)', 'failed'];
  if (s.state === 'starting' || s.state === 'stopping') return ['var(--acc,#FFB224)', s.state];
  return ['var(--mut,#8A94A6)', s.state || 'stopped'];
}

/** The doctor's counts as words: "2 problems, 3 notes, 41 passed". */
export function doctorSummary(r) {
  const c = r.counts || {}, n = (c.fail || 0) + (c.warn || 0);
  return [n ? `${n} problem${n > 1 ? 's' : ''}` : 'No problems', c.note ? `${c.note} note${c.note > 1 ? 's' : ''}` : null, `${c.ok || 0} passed`].filter(Boolean).join(', ');
}

// ---------- the cards ----------

/** The tool's result from its tool_result event (the agent keeps it as JSON in `content`); null when it can't be read. */
export function parsed(ctx) {
  const ev = ctx.liveCard?.row?.item?.result;
  if (ev?.result && typeof ev.result === 'object') return ev.result;
  try { const b = JSON.parse(ev?.content || 'null'); return b && typeof b.result === 'object' ? b.result : null; } catch { return null; }
}
const btn = (label, onClick, o = {}) => h('button', { type: 'button', onClick, disabled: o.disabled, title: o.title, style: { border: '1px solid ' + T.bds, borderRadius: 6, padding: '2px 9px', fontSize: 11.5,
  background: o.pri ? T.acc : 'transparent', color: o.pri ? '#1A1200' : T.tx, cursor: o.disabled ? 'default' : 'pointer', opacity: o.disabled ? 0.5 : 1 } }, label);
const rowSt = { display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', fontSize: 12.5, minWidth: 0, borderTop: '1px solid ' + T.bd };
const ask = async (ctx, o) => (ctx.confirm ? ctx.confirm(o) : globalThis.confirm?.(o.title));

function useAct(ctx, refresh) {
  const React = R(), [busy, setBusy] = React.useState(null);
  return [busy, async (key, f) => {
    setBusy(key);
    try { await f(); await new Promise(r => setTimeout(r, 600)); await refresh(); } catch (e) { ctx.toast?.(e.detail || e.message || String(e), 'error'); }
    setBusy(null);
  }];
}

function Frame({ icon = 'job', title, meta, children, foot }) {
  return h(kit.LiveCard, { icon, title, meta, done: true, foot }, children);
}

function MemoryCard({ ctx }) {
  const React = R(), [now, setNow] = React.useState(null), r = now || parsed(ctx);
  const refresh = async () => { const [m, s] = await Promise.all([ctx.api.getMemory(), ctx.api.listServices()]); setNow(memoryFromApi(m, Object.fromEntries((s || []).map(x => [x.id, x.name])))); };
  const [busy, act] = useAct(ctx, refresh);
  if (!r) return null;
  const parts = memoryBar(r);
  return h(Frame, { icon: 'job', title: 'Memory', meta: `${gb(r.used_gb)} of ${gb(r.total_gb)} used · ${gb(r.available_gb)} free${now ? ' · now' : ''}` },
    h('div', { style: { padding: '0 12px 8px' } },
      h('div', { role: 'img', 'aria-label': parts.map(p => `${p.label} ${gb(p.gb)}`).join(', '), style: { display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: T.inset } },
        parts.map(p => h('span', { key: p.id, title: `${p.label}: ${gb(p.gb)}`, style: { width: p.pct + '%', background: p.color } })))),
    ...memoryRows(r).rows.map(s => h('div', { key: s.id, style: rowSt },
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.name),
      h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, gb(s.used_gb)),
      s.load ? h(Badge, { tone: s.load === 'loaded' ? 'green' : 'dim' }, s.load) : null,
      s.load === 'loaded' ? btn(busy === s.id ? 'Unloading…' : 'Unload', () => act(s.id, () => ctx.api.unloadService(s.id)), { disabled: !!busy }) : null)),
    memoryRows(r).rest.n ? h('div', { style: { ...rowSt, color: T.mut } }, `${memoryRows(r).rest.n} more running with nothing loaded`, h('span', { style: { marginLeft: 'auto', fontFamily: MONO, fontSize: 11.5 } }, gb(memoryRows(r).rest.gb))) : null);
}

/** The rows worth a line (loaded, or holding 0.5 GB or more), largest first; the rest summed. */
export function memoryRows(r) {
  const all = (r.by_service || []).slice().sort((a, b) => b.used_gb - a.used_gb);
  const rows = all.filter(s => s.load === 'loaded' || s.load === 'loading' || s.used_gb >= 0.5), rest = all.filter(s => !rows.includes(s));
  return { rows, rest: { n: rest.length, gb: rest.reduce((a, s) => a + (s.used_gb || 0), 0) } };
}

function ServicesCard({ ctx }) {
  const React = R(), [now, setNow] = React.useState(null), r = now || parsed(ctx);
  const refresh = async () => setNow({ services: (await ctx.api.listServices()).map(s => ({ id: s.id, name: s.name, state: s.state, load: s.load, busy: s.busy })) });
  const [busy, act] = useAct(ctx, refresh);
  if (!r) return null;
  const list = r.services || [], up = list.filter(s => s.state === 'ready').length;
  const stop = s => act(s.id, async () => {
    if (s.busy && !(await ask(ctx, { title: `Stop ${s.name}?`, body: 'It is working on something now; its running jobs are cancelled.', confirmLabel: 'Stop', danger: true }))) return;
    await ctx.api.stopService(s.id);
  });
  return h(Frame, { icon: 'job', title: 'Services', meta: `${up} of ${list.length} running${now ? ' · now' : ''}` },
    list.map(s => { const [c, w] = stateTone(s); return h('div', { key: s.id, style: rowSt },
      h('span', { style: { width: 8, height: 8, borderRadius: '50%', background: c, flex: 'none' } }),
      h('span', { style: { flex: 1, minWidth: 0 } }, s.name, h('span', { style: { color: T.dim, marginLeft: 6, fontSize: 11.5 } }, w)),
      s.state === 'ready' || s.state === 'degraded' ? btn(busy === s.id ? 'Stopping…' : 'Stop', () => stop(s), { disabled: !!busy })
        : s.state === 'stopped' || s.state === 'failed' ? btn(busy === s.id ? 'Starting…' : 'Start', () => act(s.id, () => ctx.api.startService(s.id)), { disabled: !!busy }) : null); }));
}

function GpuCard({ ctx }) {
  const React = R(), [now, setNow] = React.useState(null), r = now || parsed(ctx);
  const refresh = async () => { const v = await ctx.api.getGpu(); setNow({ holder: v.holder?.leases || [], waiting: v.waiting || [], recent: (v.recent || []).slice(0, 5) }); };
  const [busy, act] = useAct(ctx, refresh);
  if (!r) return null;
  const line = (x, wait) => h('div', { key: x.id, style: rowSt },
    h('span', { style: { flex: 1, minWidth: 0 } }, x.name || x.service, x.label ? h('span', { style: { color: T.dim, marginLeft: 6 } }, x.label) : null),
    h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, wait ? (x.eta_s != null ? `starts in ${kit.fmtLeft(x.eta_s)?.replace(' left', '')}` : 'waiting') : x.eta_s != null ? kit.fmtLeft(x.eta_s) : x.elapsed_s != null ? `${Math.round(x.elapsed_s)} s in` : ''),
    wait ? btn(busy === x.id ? 'Cancelling…' : 'Cancel', () => act(x.id, () => ctx.api.cancelGpuLease(x.id)), { disabled: !!busy }) : null);
  const holder = r.holder || [], waiting = r.waiting || [];
  return h(Frame, { icon: 'job', title: 'GPU', meta: holder.length ? `in use · ${waiting.length} waiting` : 'free' },
    holder.length ? holder.map(x => line(x, false)) : h('div', { style: { ...rowSt, color: T.mut } }, 'Nothing is using the GPU.'),
    waiting.map(x => line(x, true)));
}

function DoctorCard({ ctx }) {
  const React = R(), [open, setOpen] = React.useState(false), r = parsed(ctx);
  if (!r) return null;
  const tone = { fail: 'var(--rd,#F85149)', warn: 'var(--acc,#FFB224)', note: T.cy };
  return h(Frame, { icon: 'job', title: r.ok ? 'The install looks right' : 'The install has problems', meta: doctorSummary(r),
    foot: (r.passed || []).length ? h('button', { type: 'button', onClick: () => setOpen(!open), style: { background: 'none', border: 0, color: T.mut, cursor: 'pointer', fontSize: 12, padding: 0 } },
      open ? 'Hide what passed' : `Show the ${r.passed.length} that passed`) : null },
    (r.checks || []).map((c, i) => h('div', { key: i, style: { ...rowSt, alignItems: 'flex-start', flexDirection: 'column', gap: 2 } },
      h('span', null, h('span', { style: { color: tone[c.level] || T.mut, fontWeight: 600, marginRight: 6, textTransform: 'uppercase', fontSize: 10.5 } }, c.level), c.title),
      c.detail ? h('span', { style: { color: T.mut, fontSize: 12 } }, c.detail) : null,
      c.fix ? h('span', { style: { fontSize: 12 } }, 'Fix: ', h('code', { style: { fontFamily: MONO, fontSize: 11.5 } }, c.fix)) : null)),
    open ? h('div', { style: { ...rowSt, color: T.mut, flexWrap: 'wrap' } }, (r.passed || []).join(' · ')) : null);
}

function FreedCard({ ctx }) {
  const r = parsed(ctx);
  if (!r) return null;
  const freed = r.freed || [], kept = r.kept || [], failed = r.failed || [];
  return h(Frame, { icon: 'job', title: freed.length ? `Freed ${gb(r.freed_gb)}` : 'Nothing to free', meta: freed.length ? `${freed.length} unloaded` : '' },
    freed.map(f => h('div', { key: f.id, style: rowSt }, h('span', { style: { flex: 1 } }, f.name), h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, gb(f.gb)), h(Badge, { tone: 'green' }, 'unloaded'))),
    kept.map(f => h('div', { key: 'k' + f.id, style: { ...rowSt, color: T.mut } }, h('span', { style: { flex: 1 } }, f.name), h('span', { style: { fontSize: 11.5 } }, 'kept: ' + f.why))),
    failed.map(f => h('div', { key: 'f' + f.id, style: { ...rowSt, color: 'var(--rd,#F85149)' } }, h('span', { style: { flex: 1 } }, f.name), h('span', { style: { fontSize: 11.5 } }, f.error))));
}

export const STATUS_CARDS = { hub_memory_status: MemoryCard, hub_list_services: ServicesCard, hub_gpu_status: GpuCard, hub_doctor: DoctorCard, hub_free_gpu: FreedCard };
for (const [name, C] of Object.entries(STATUS_CARDS)) registerCard('live:' + name, ({ ctx }) => h(C, { ctx }));
