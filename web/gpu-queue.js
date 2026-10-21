// The GPU queue in the UI (plan 31.5, brief §11.7): what holds the GPU slot and what waits for it, in order,
// each waiting lease with Cancel. Drawn in the header's memory popover (`GpuSection`) and as the Overview's
// "GPU queue" widget (`GpuQueueW`, with the mean wait and hold times per mod from the metrics). The queue
// itself is `GET /api/gpu` (`GpuState`), kept fresh by `gpu` events. Written by us (web/PATCHES.md).

import { h, MONO, MUT, BD, TONE, SERIES, fmtDur, btnSt, Frame } from './chart-kit.js';
import { HBarChart } from './charts.js';
import { useData, chartState } from './views.js';

const R = () => globalThis.React;

// ---------- pure (tested in utils/tests/web/gpu-queue.test.mjs) ----------
export const CLASS_LABEL = { interactive: 'interactive', job: 'job', background: 'background' };

// "about 4 min", "about 40 s", "" (unknown)
export function fmtEta(s) {
  if (s == null || !(s > 0)) return '';
  return s >= 90 ? `about ${Math.max(1, Math.round(s / 60))} min` : `about ${Math.round(s)} s`;
}

// The queue as rows: holders first, then the waiting leases in the order they will run.
export function gpuRows(gpu, nameOf = id => id, now = Date.now() / 1000) {
  if (!gpu) return { holder: [], waiting: [], on: true };
  const name = l => l.name || nameOf(l.service) || l.service;
  const holder = (gpu.holder?.leases || []).map(l => ({
    id: l.id, service: l.service, name: name(l), label: l.label, cls: l.class, nested: !!l.parent,
    elapsed: fmtDur(l.elapsed_s ?? (l.granted_ts ? now - l.granted_ts : 0)), eta: fmtEta(l.eta_s), thread: l.thread || null,
  }));
  const waiting = (gpu.waiting || []).map((l, i) => ({
    id: l.id, service: l.service, name: name(l), label: l.label, cls: l.class, pos: i + 1,
    waited: fmtDur(l.waited_s ?? (now - l.created_ts)), eta: fmtEta(l.eta_s), thread: l.thread || null,
  }));
  return { holder, waiting, on: gpu.queue !== false };
}

// One line for the header and lists: "Images & Video · 2 waiting", "free".
export function gpuSummary(gpu, nameOf = id => id) {
  if (!gpu) return '';
  const top = gpu.holder?.leases?.find(l => !l.parent) || gpu.holder?.leases?.[0];
  const n = gpu.waiting?.length || 0;
  const head = top ? (top.name || nameOf(top.service)) : 'free';
  return n ? `${head} · ${n} waiting` : head;
}

// A job row's text while it waits for the slot (`stage: "waiting_gpu"`, `ahead`, `eta_s`), else null.
export function jobGpuText(job, nameOf = id => id) {
  if (!job || job.stage !== 'waiting_gpu') return null;
  const first = (job.ahead || []).find(a => a && a.service);
  let t = 'Waiting for the GPU';
  if (first) t += `: ${nameOf(first.service) || first.service}${first.label ? ` (${first.label})` : ''}`;
  const eta = fmtEta(job.eta_s);
  return eta ? `${t}, ${eta}` : t;
}

// Mean of the non-null values in each `gpu.<what>.<mod>` series: [{service, wait, hold}].
export function waitTimes(metrics) {
  const by = {};
  for (const [name, values] of Object.entries(metrics?.series || {})) {
    const m = /^gpu\.(wait|hold)\.(.+)$/.exec(name);
    if (!m) continue;
    const v = (values || []).filter(x => x != null);
    if (!v.length) continue;
    (by[m[2]] ||= { service: m[2], wait: null, hold: null })[m[1]] = v.reduce((a, b) => a + b, 0) / v.length;
  }
  return Object.values(by).sort((a, b) => (b.wait || 0) - (a.wait || 0));
}

// ---------- components ----------
const rowSt = { display: 'flex', alignItems: 'center', gap: 8, minHeight: 26, fontSize: 12, minWidth: 0 };
const ell = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' };
const dot = c => h('span', { 'aria-hidden': true, style: { width: 7, height: 7, borderRadius: 9, background: c, flex: 'none' } });

function Row({ r, held, onCancel, busy }) {
  return h('div', { style: { ...rowSt, borderTop: '1px solid ' + BD } },
    held ? dot(TONE.green) : h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: MUT, width: 14, textAlign: 'right', flex: 'none' } }, r.pos),
    h('span', { style: { flex: 1, minWidth: 0, ...ell }, title: `${r.name}: ${r.label} (${r.cls})` },
      h('span', { style: { fontWeight: 600 } }, r.name), r.label ? h('span', { style: { color: MUT } }, ' · ' + r.label) : null,
      r.nested ? h('span', { style: { color: MUT, fontSize: 10.5 } }, ' (under its caller)') : null),
    h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: MUT, flex: 'none' } },
      held ? [r.elapsed, r.eta ? ` · ${r.eta} left` : ''].join('') : [`waited ${r.waited}`, r.eta ? ` · starts in ${r.eta.replace('about ', '~')}` : ''].join('')),
    !held && onCancel ? h('button', { type: 'button', disabled: busy, 'aria-label': `Cancel ${r.name} ${r.label}`, onClick: () => onCancel(r.id), style: { ...btnSt, height: 22, padding: '0 8px', fontSize: 11 } }, 'Cancel') : null);
}

// props: gpu (GpuState), nameOf(id), onCancel(leaseId) → Promise, title?
export function GpuSection({ gpu, nameOf, onCancel, title = 'GPU' }) {
  const React = R(), [busy, setBusy] = React.useState(null);
  const rows = gpuRows(gpu, nameOf);
  const cancel = onCancel ? async id => { setBusy(id); try { await onCancel(id); } finally { setBusy(null); } } : null;
  return h('section', { 'aria-label': 'GPU queue', style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } },
    title ? h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 } },
      h('h2', { style: { margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: MUT } }, title),
      h('span', { style: { marginLeft: 'auto', fontSize: 11, color: MUT } }, !gpu ? '' : rows.on ? 'one job at a time' : 'queue off: memory only')) : null,
    !gpu ? h('div', { style: { fontSize: 12, color: MUT } }, 'Loading…')
      : !rows.holder.length && !rows.waiting.length ? h('div', { style: { ...rowSt, color: MUT } }, dot(MUT), 'Free: nothing is using the GPU slot')
        : [...rows.holder.map(r => h(Row, { key: r.id, r, held: true })),
          ...rows.waiting.map(r => h(Row, { key: r.id, r, onCancel: cancel, busy: busy === r.id }))]);
}

// The Overview widget: the queue now, and the mean wait / time on the GPU per mod over the range.
export function GpuQueueW({ ctx, range, table }) {
  const name = id => ctx.services.find(s => s.id === id)?.name || id;
  const d = useData(() => ctx.api.getMetrics({ series: ['gpu.wait.*', 'gpu.hold.*'], range }), [ctx.api, range, ctx.gpu?.recent?.[0]?.id], 120000);
  let chart;
  if (d.state !== 'ok') chart = h(HBarChart, { ...chartState(d), height: 80 });
  else {
    const rows = waitTimes(d.data);
    chart = rows.length ? h(HBarChart, { categories: rows.map(x => name(x.service)), unit: 'seconds', label: 'Mean wait and time on the GPU', table,
      series: [{ key: 'wait', label: 'Wait', values: rows.map(x => x.wait), color: SERIES[1] }, { key: 'hold', label: 'On the GPU', values: rows.map(x => x.hold), color: SERIES[0] }] })
      : h(Frame, { state: 'empty', height: 60, emptyText: 'No GPU work in this range' });
  }
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } },
    h(GpuSection, { gpu: ctx.gpu, nameOf: name, onCancel: ctx.cancelGpu, title: null }), chart);
}
