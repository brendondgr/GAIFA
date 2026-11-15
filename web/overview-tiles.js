// The Overview's tiles for what's happening now (plan overview-bento 2.1): Needs you, Running now, Memory,
// the number tiles and Services. Each takes {ctx, size}; ctx is the Dashboard's props. The pure parts
// (needsRows, runningRows, memorySplit, serviceRows) are tested in utils/tests/web/overview-tiles.test.mjs.
// Written by us (web/PATCHES.md).

import { h, MONO, MUT, BD, TONE, OTHER, SERIES, fmtBytes, fmtNum } from './chart-kit.js';
import { Sparkline } from './charts.js';
import { useData, svcColor } from './views.js';
import { LiveThumb } from './live-kit.js';
import { jobGpuText, gpuSummary } from './gpu-queue.js';
import { Icon, useTileSize } from './bento.js';
import { store } from './ui-store.js';

const TX = 'var(--tx,#E6EAF2)';
const GB = b => (b >= 0.05e9 ? fmtBytes(b) : '—');

// ---------- pure ----------
/** A running job's words: GPU wait, queued, its step (plan 44.5), its percent, or running. */
export function jobStatusText(j) {
  if (j.stage === 'waiting_gpu') return 'GPU wait';
  if (j.state === 'queued') return 'queued';
  if (j.live?.step != null && j.live?.steps) return `${Math.min(j.live.step, j.live.steps)}/${j.live.steps}`;
  return j.progress != null ? Math.round(j.progress * 100) + '%' : 'running';
}

// What needs you, worst first: errors and failed mods, approvals, warnings, memories to review.
export function needsRows({ alerts = [], services = [], approvals = [], memReview = 0, setupNotNow = [] }) {
  const rows = [], failedAlert = new Set(alerts.filter(a => a.service && a.level === 'error').map(a => a.service));
  for (const a of alerts) rows.push({ key: 'a:' + a.id, rank: a.level === 'error' ? 0 : 2, tone: a.level === 'error' ? 'red' : 'accent', text: a.text, action: a.action?.label || 'Open', href: a.action?.route || null });
  for (const s of services) {
    const mf = (s.manifest_errors || []).length > 0;
    if ((s.state === 'failed' || mf) && !failedAlert.has(s.id))
      rows.push({ key: 'f:' + s.id, rank: 0, tone: 'red', text: `${s.name} ${mf ? 'has a manifest error' : 'failed'}`, sub: mf ? s.manifest_errors[0] : s.last_error || '', action: mf ? 'Details' : 'Logs', href: `#/s/${s.id}${mf ? '' : '/logs'}` });
  }
  if (approvals.length) rows.push({ key: 'ap', rank: 1, tone: 'purple', text: `${approvals.length} approval${approvals.length > 1 ? 's' : ''} waiting`, sub: [...new Set(approvals.map(a => a.tool))].slice(0, 2).join(', '), action: 'Review', approvals: true });
  // capability-enablement 3.5: the recommended mods that aren't set up, once (until Not now)
  const missing = services.filter(s => s.recommended && s.availability?.status === 'not_set_up');
  if (missing.length && !missing.every(s => setupNotNow.includes(s.id)))
    rows.push({ key: 'setup', rank: 2, tone: 'accent', text: `${missing.length} recommended mod${missing.length > 1 ? 's' : ''} not set up`,
      sub: missing.map(s => s.name).join(', '), action: 'Set up', setup: missing.map(s => s.id) });
  if (memReview > 0) rows.push({ key: 'mem', rank: 3, tone: 'cyan', text: `${memReview} ${memReview > 1 ? 'memories' : 'memory'} to review`, action: 'Review', href: '#/s/agent/review' });
  return rows.sort((a, b) => a.rank - b.rank);
}

// What's running: jobs (running before queued), then models held in memory.
export function runningRows({ jobs = [], services = [] }) {
  const name = id => services.find(s => s.id === id)?.name || id;
  const live = jobs.filter(j => j.state === 'running' || j.state === 'queued').sort((a, b) => (a.state === 'running' ? 0 : 1) - (b.state === 'running' ? 0 : 1));
  const job = live.map(j => ({ key: 'j:' + j.id, kind: 'job', text: j.label, sub: name(j.service), status: jobStatusText(j), progress: j.state === 'running' ? j.progress : null, href: j.route || '#/s/' + j.service, job: j }));
  const models = services.filter(s => s.load === 'loaded' || s.load === 'loading')
    .sort((a, b) => b.memory.used_bytes - a.memory.used_bytes)
    .map(s => ({ key: 'm:' + s.id, kind: 'model', text: s.name, sub: s.load === 'loading' ? 'loading' : 'model loaded', status: GB(s.memory.used_bytes), href: '#/s/' + s.id }));
  return [...job, ...models];
}

// The memory bar: the n largest users above `min`, everything else, free, and the reserve line.
export function memorySplit(memory, services = [], { n = 3, min = 0.5e9 } = {}) {
  if (!memory) return null;
  const total = Math.max(1, memory.total_bytes), used = Math.min(total, memory.used_bytes);
  const name = id => services.find(s => s.id === id)?.name || id;
  const top = (memory.by_service || []).filter(r => r.used_bytes >= min).sort((a, b) => b.used_bytes - a.used_bytes).slice(0, n);
  const topSum = top.reduce((s, r) => s + r.used_bytes, 0), rest = Math.max(0, used - topSum);
  const segs = top.map(r => ({ key: r.id, label: name(r.id), bytes: r.used_bytes, pct: r.used_bytes / total * 100, color: svcColor(services, r.id) }));
  if (rest > 0) segs.push({ key: 'rest', label: top.length ? 'Other' : 'In use', bytes: rest, pct: rest / total * 100, color: OTHER });
  const reserve = memory.reserve_bytes || 0;
  return { used, total, free: Math.max(0, total - used), pct: used / total, segs, reservePct: reserve ? Math.max(0, (total - reserve) / total * 100) : null };
}

// Services in the order worth reading: problems, then those working or holding memory (largest first);
// the rest fold into one row.
export function serviceRows(services = []) {
  const rank = s => ((s.manifest_errors || []).length || s.state === 'failed' ? 0
    : ['degraded', 'starting', 'stopping'].includes(s.state) ? 1
      : s.load === 'loaded' || s.load === 'loading' || s.busy || (s.memory?.used_bytes || 0) >= 0.5e9 ? 2 : 3);
  const all = services.map((s, i) => ({ s, r: rank(s), i }));
  const top = all.filter(x => x.r < 3).sort((a, b) => a.r - b.r || (b.s.memory?.used_bytes || 0) - (a.s.memory?.used_bytes || 0)).map(x => x.s);
  const rest = all.filter(x => x.r === 3).sort((a, b) => (a.s.state === 'ready' ? 0 : 1) - (b.s.state === 'ready' ? 0 : 1) || a.i - b.i).map(x => x.s);
  const count = st => services.filter(s => s.state === st).length;
  return { top, rest, counts: { ready: count('ready'), stopped: count('stopped'), failed: all.filter(x => x.r === 0).length, total: services.length } };
}

// ---------- shared pieces ----------
export const dotSt = c => ({ width: 7, height: 7, borderRadius: 9, background: c, flex: 'none' });
const ellip = { flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' };
/** One row in a tile's list: a lead (dot, thumbnail), the text and a muted second part, and something at the right. */
export function Row({ lead, text, sub, right, href, onClick, first, dim, title, height = 26 }) {
  const st = { display: 'flex', alignItems: 'center', gap: 8, minHeight: height, padding: 0, margin: 0, boxSizing: 'border-box', borderWidth: first ? 0 : '1px 0 0', borderStyle: 'solid', borderColor: BD,
    fontFamily: 'inherit', fontSize: 12, color: dim ? MUT : TX, minWidth: 0, textDecoration: 'none', background: 'transparent', width: '100%', textAlign: 'left', cursor: href || onClick ? 'pointer' : 'default' };
  const body = [lead, h('span', { key: 't', title: title || undefined, style: ellip }, text, sub ? h('span', { style: { color: MUT, marginLeft: 6, fontSize: 11.5 } }, sub) : null), right];
  if (href) return h('a', { href, style: st }, body);
  if (onClick) return h('button', { type: 'button', onClick, style: st }, body);
  return h('div', { style: st }, body);
}
export const Muted = ({ children, mono, style }) => h('span', { style: { flex: 'none', fontSize: 11, color: MUT, fontFamily: mono ? MONO : undefined, whiteSpace: 'nowrap', ...style } }, children);
/** A quiet empty state that fills the tile. */
export function Calm({ icon, text, tone = 'green' }) {
  return h('div', { style: { height: '100%', minHeight: 40, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontSize: 12, color: MUT } },
    icon && h('span', { style: { color: TONE[tone], display: 'flex' } }, h(Icon, { d: icon, size: 15 })), text);
}
export const PATHS = {
  check: 'M5 12l5 5 9-10', bell: 'M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 21h4', play: 'M8 5v14l11-7z', memory: 'M3 8h18v8H3zM7 8v8M11 8v8M15 8v8M7 16v3M17 16v3',
  apps: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z', calendar: 'M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5v12a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5zM4 10h16M8.5 3v4M15.5 3v4',
  chat: 'M4 5h16v11H9l-5 4z', activity: 'M3 12h4l3-8 4 16 3-8h4', image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 8.5h.01', chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  relay: 'M4 7h12M12 3l4 4-4 4M20 17H8M12 13l-4 4 4 4', clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2', layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5', cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
};

// ---------- Needs you ----------
export function NeedsW({ ctx }) {
  const React = globalThis.React, [, redraw] = React.useState(0);
  const notNow = store.get('hub.overview.setupNotNow', []) || [];
  const rows = needsRows({ ...ctx, setupNotNow: notNow });
  if (!rows.length) return h(Calm, { icon: PATHS.check, text: 'All clear: nothing needs you' });
  const setup = ids => globalThis.dispatchEvent?.(new CustomEvent('gaifa:setup', { detail: { ids } }));   // the Set up dialog (3.4)
  const later = ids => { store.set('hub.overview.setupNotNow', [...new Set([...notNow, ...ids])]); redraw(n => n + 1); };
  return h('div', null, rows.map((r, i) => h(Row, { key: r.key, first: i === 0, href: r.href || undefined,
    onClick: r.approvals ? ctx.onApprovals : r.setup ? () => setup(r.setup) : undefined, title: r.sub ? `${r.text}: ${r.sub}` : r.text,
    lead: h('span', { style: dotSt(TONE[r.tone]) }), text: r.text, sub: r.sub,
    right: r.setup ? h('span', { style: { display: 'flex', gap: 8 } },
        h('span', { role: 'button', tabIndex: 0, onClick: e => { e.stopPropagation(); later(r.setup); },        // inside the row's button: not a button itself
          onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); later(r.setup); } },
          style: { fontSize: 11.5, color: MUT, cursor: 'pointer', textDecoration: 'underline', whiteSpace: 'nowrap', flex: 'none' } }, 'Not now'),
        h(Muted, { style: { color: 'var(--cy,#58C4DD)' } }, r.action + ' →'))
      : h(Muted, { style: { color: TONE[r.tone] === TONE.red ? TONE.red : 'var(--cy,#58C4DD)' } }, r.action + ' →') })));
}
export const needsCount = ctx => { const r = needsRows({ ...ctx, setupNotNow: store.get('hub.overview.setupNotNow', []) || [] }); return { count: r.length || null, tone: r.some(x => x.tone === 'red') ? 'red' : r.length ? 'accent' : null }; };

// ---------- Running now ----------
export function RunningW({ ctx }) {
  const rows = runningRows(ctx), name = id => ctx.services.find(s => s.id === id)?.name || id;
  const gpu = ctx.gpu && (ctx.gpu.waiting?.length || ctx.gpu.holder?.leases?.length) ? gpuSummary(ctx.gpu, name) : '';
  if (!rows.length && !gpu) return h(Calm, { icon: PATHS.play, text: 'Nothing running', tone: 'dim' });
  return h('div', null,
    gpu && h(Row, { key: 'gpu', first: true, lead: h('span', { style: { color: TONE.accent, display: 'flex' } }, h(Icon, { d: PATHS.cpu, size: 12 })), text: 'GPU', sub: gpu, href: '#/overview?view=timeline' }),
    rows.map((r, i) => h(Row, { key: r.key, first: !gpu && i === 0, href: r.href, title: r.job ? jobGpuText(r.job, name) || r.text : r.text,
      lead: r.job?.live?.preview ? h(LiveThumb, { live: r.job.live, size: 22 }) : h('span', { style: dotSt(r.kind === 'job' ? TONE.accent : TONE.cyan) }),
      text: r.text, sub: r.sub,
      right: h('span', { style: { display: 'flex', alignItems: 'center', gap: 6, flex: 'none' } },
        r.progress != null && h('span', { style: { width: 44, height: 4, borderRadius: 9, background: 'var(--row,#1A2130)', overflow: 'hidden', display: 'block' } }, h('span', { style: { display: 'block', height: '100%', width: (r.progress || 0) * 100 + '%', background: TONE.accent } })),
        h(Muted, { mono: true }, r.status)) })));
}
export const runningCount = ctx => { const n = (ctx.jobs || []).filter(j => j.state === 'running').length; return { count: n || null, tone: n ? 'accent' : null }; };

// ---------- Memory ----------
export function MemoryHeroW({ ctx, size }) {
  const m = memorySplit(ctx.memory, ctx.services), { h: bodyH } = useTileSize();
  if (!m) return h(Calm, { text: 'Reading memory…', tone: 'dim' });
  const hot = m.pct > 0.92 ? TONE.red : m.pct > 0.8 ? TONE.accent : TX;
  const spark = (ctx.hist1?.series?.['mem.used'] || []), room = spark.length > 1 && bodyH - 82 >= 14;   // the 1 h sparkline, in a tile tall enough
  return h('a', { href: '#/settings/memory', 'aria-label': `Memory: ${fmtBytes(m.used)} of ${fmtBytes(m.total)} used`, style: { display: 'flex', flexDirection: 'column', gap: 6, height: '100%', color: TX, textDecoration: 'none', minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6 } },
      h('span', { style: { fontFamily: MONO, fontSize: 24, fontWeight: 600, color: hot, letterSpacing: '-.01em' } }, fmtBytes(m.used)),
      h('span', { style: { fontFamily: MONO, fontSize: 12, color: MUT } }, '/ ' + fmtBytes(m.total, 0)),
      h('span', { style: { marginLeft: 'auto', fontSize: 11, color: MUT, whiteSpace: 'nowrap' } }, h('span', { style: { fontFamily: MONO, color: hot } }, Math.round(m.pct * 100) + '%'), ' · ',
        h('span', { style: { fontFamily: MONO, color: TX } }, fmtBytes(m.free)), ' free')),
    h('div', { style: { position: 'relative', display: 'flex', height: 8, borderRadius: 5, overflow: 'hidden', background: 'var(--row,#1A2130)', flex: 'none' } },
      m.segs.map(s => h('span', { key: s.key, title: `${s.label}: ${fmtBytes(s.bytes)}`, style: { display: 'block', width: s.pct + '%', minWidth: 2, background: s.color } })),
      m.reservePct != null && h('span', { title: 'Reserve: GAIFA unloads models past this line', style: { position: 'absolute', left: m.reservePct + '%', top: 0, bottom: 0, width: 2, background: TX, opacity: 0.55 } })),
    // one line, the largest first; what doesn't fit is cut (each is also the bar's tooltip)
    h('div', { style: { display: 'flex', gap: 12, fontSize: 11, color: MUT, minWidth: 0, overflow: 'hidden', height: 16, flex: 'none', marginTop: room ? 0 : 'auto' } },
      m.segs.map(s => h('span', { key: s.key, style: { display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap', flex: 'none' } }, h('span', { style: dotSt(s.color) }), s.label, h('span', { style: { fontFamily: MONO, color: TX } }, fmtBytes(s.bytes))))),
    room && h('div', { style: { marginTop: 'auto' } }, h(Sparkline, { values: spark, color: SERIES[0], height: Math.min(48, bodyH - 82), label: 'Memory used, last hour', unit: 'bytes' })));
}

// ---------- the number tiles ----------
export const NUM_ST = { display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0, height: 20, overflow: 'hidden', color: 'var(--tx,#E6EAF2)', textDecoration: 'none' };
function Num({ value, sub, tone, href, spark, unit, label }) {
  const body = [
    h('span', { key: 'v', style: { fontFamily: MONO, fontSize: 17, lineHeight: '20px', fontWeight: 600, color: tone ? TONE[tone] : TX, whiteSpace: 'nowrap' } }, value),
    sub && h('span', { key: 's', style: { fontSize: 11, lineHeight: '20px', color: MUT, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 } }, sub),
    spark && spark.values?.length > 1 && h('span', { key: 'k', style: { marginLeft: 'auto', width: 64, flex: 'none', alignSelf: 'center' } }, h(Sparkline, { values: spark.values, color: spark.color, width: 64, height: 18, label, unit })),
  ];
  const st = NUM_ST;
  return href ? h('a', { href, style: st, 'aria-label': `${label}: ${value}${sub ? ' ' + sub : ''}` }, body) : h('div', { style: st }, body);
}

function OutputsNum({ ctx }) {
  const d = useData(() => ctx.api.getOutputStats({ range: '7d', by: 'day' }), [ctx.api, ctx.outTick], 120000);
  const days = d.data?.buckets || [], today = days.at(-1)?.count ?? null, yday = days.at(-2)?.count ?? null;
  const delta = today != null && yday != null ? today - yday : null;
  return h(Num, { label: 'Outputs today', value: today == null ? '—' : String(today), sub: delta == null ? '' : `${delta >= 0 ? '+' : ''}${delta} vs yday`, href: '#/outputs?range=today', spark: { values: days.map(b => b.count), color: SERIES[3] }, unit: 'count' });
}

export function statTile(key, ctx) {
  const s = ctx.services, h24 = ctx.hist24?.series || {};
  if (key === 'stat-services') {
    const ready = s.filter(x => x.state === 'ready').length, failed = serviceRows(s).counts.failed;
    return h(Num, { label: 'Services ready', value: `${ready}/${s.length}`, sub: failed ? `${failed} failed` : 'ready', tone: failed ? 'red' : null, href: '#/overview?view=table' });
  }
  if (key === 'stat-outputs') return h(OutputsNum, { ctx });
  if (key === 'stat-tokens') {
    const tok = s.flatMap(x => x.stats.map(st => ({ st, x }))).find(({ st }) => /tokens today/i.test(st.label));
    const v = tok ? (typeof tok.st.value === 'number' ? tok.st.value : Number(tok.st.value)) : null;
    return h(Num, { label: 'LLM tokens today', value: v == null || Number.isNaN(v) ? '—' : fmtNum(v), sub: tok ? tok.x.name : 'no LLM relay', href: tok ? '#/s/' + tok.x.id : undefined,
      spark: tok?.st.series ? { values: h24[tok.st.series] || [], color: SERIES[2] } : null, unit: 'count' });
  }
  if (key === 'stat-jobs') {
    const run = ctx.jobs.filter(j => j.state === 'running').length, q = ctx.jobs.filter(j => j.state === 'queued').length;
    return h(Num, { label: 'Jobs running', value: String(run), sub: q ? `${q} queued` : 'now', tone: run ? 'accent' : null, spark: { values: h24['jobs.running'] || [], color: SERIES[1] }, unit: 'count' });
  }
  if (key === 'stat-models') return h(Num, { label: 'Models loaded', value: String(s.filter(x => x.load === 'loaded').length), sub: 'in memory', href: '#/overview?view=timeline' });
  return null;
}

// ---------- Services ----------
const LOAD_TONE = { loaded: TONE.cyan, loading: TONE.accent, unloading: TONE.accent };
function SvcRow({ s, ctx, first, wide }) {
  const b = ctx.badge(s.state), mem = s.memory?.used_bytes || 0, mf = (s.manifest_errors || []).length > 0;
  return h(Row, { first, href: '#/s/' + s.id, dim: s.state === 'stopped', title: `${s.name}, ${mf ? 'manifest error' : s.state}`,
    lead: mf ? h('span', { style: dotSt(TONE.red) }) : b.dot, text: s.name,
    right: h('span', { style: { display: 'flex', alignItems: 'center', gap: 8, flex: 'none' } },
      LOAD_TONE[s.load] && h(Muted, { style: { color: LOAD_TONE[s.load] } }, s.load),
      s.state === 'failed' && h(Muted, { style: { color: TONE.red } }, 'failed'),
      h(Muted, { mono: true, style: { width: 52, textAlign: 'right', color: mem >= 0.05e9 ? TX : MUT } }, GB(mem)),
      wide && h('span', { style: { width: 56, display: 'block' } }, h(Sparkline, { values: ctx.hist24?.series?.['mem.svc.' + s.id] || [], color: svcColor(ctx.services, s.id), width: 56, height: 16, label: `${s.name} memory, 24 h`, unit: 'bytes' }))) });
}
export function ServicesW({ ctx }) {
  const { w } = useTileSize(), { top, rest, counts } = serviceRows(ctx.services);
  if (!ctx.services.length) return h(Calm, { text: 'No mods installed yet', tone: 'dim' });
  const wide = w === 0 || w > 330;
  const chip = (c, n, l) => h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 5 } }, h('span', { style: dotSt(c) }), h('span', { style: { fontFamily: MONO, color: TX } }, n), l);
  // The idle ones as small pills: every service in view at once, without a row each.
  const pill = s => h('a', { key: s.id, href: '#/s/' + s.id, title: `${s.name}, ${s.state}`, style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 22, padding: '0 8px', borderRadius: 99, border: '1px solid ' + BD, background: 'var(--inset,#131926)', fontSize: 11.5, color: s.state === 'stopped' ? MUT : TX, textDecoration: 'none', maxWidth: '100%', minWidth: 0 } },
    h('span', { style: dotSt(s.state === 'ready' ? TONE.green : s.state === 'stopped' ? 'var(--bds,#2A3547)' : TONE.accent) }), h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.name));
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    h('div', { style: { display: 'flex', gap: 12, fontSize: 11, color: MUT } },
      chip(TONE.green, counts.ready, 'ready'), chip(MUT, counts.stopped, 'stopped'), counts.failed ? chip(TONE.red, counts.failed, 'failed') : null),
    top.length > 0 && h('div', null, top.map((s, i) => h(SvcRow, { key: s.id, s, ctx, first: i === 0, wide }))),
    rest.length > 0 && h('div', { 'aria-label': 'Idle services', style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, rest.map(pill)));
}
