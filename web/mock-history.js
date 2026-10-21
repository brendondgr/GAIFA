// AIHub mock — chart history (brief §11.7, §11.9): metrics, timeline, output/activity/job stats, widgets.
// The past is a deterministic function of time (seeded day plans, no big arrays): lcpp loaded ~09–18,
// tts spikes with a 180 s idle tail, gen3d bursts to ~52 GB while jobs run, comfy sessions of ~20 GB.
// The last 20 min before the mock started settle on its starting state; from then on the mock's own
// `memory` events are recorded on a 10 s grid (none while the hub is "down": those are gaps).
const GB = 1e9, MIN = 60, HOUR = 3600, DAY = 86400;
export const RANGES = { '1h': HOUR, '6h': 6 * HOUR, '24h': DAY, '7d': 7 * DAY, '14d': 14 * DAY, '30d': 30 * DAY };
const DEFAULT_STEP = { [HOUR]: 10, [6 * HOUR]: MIN, [DAY]: 5 * MIN, [7 * DAY]: 30 * MIN, [14 * DAY]: HOUR, [30 * DAY]: 2 * HOUR };
const LIVE = ['ready', 'degraded'], TAIL = 20 * MIN, HISTORY = 32 * DAY, KEEP_REC = 48 * HOUR;
const MODEL_IDS = ['relay', 'lcpp', 'tts', 'gen3d', 'comfy', 'example'];
const MEM = { 'mem.total': ['total', 'Memory total'], 'mem.used': ['used', 'Memory used'], 'mem.available': ['available', 'Memory available'],
  'mem.reserve': ['reserve', 'Memory reserve'], 'mem.other': ['other', 'Other (not mods)'], 'gpu.gtt_used': ['gtt', 'GPU memory (GTT) used'],
  'gpu.vram_used': ['vram', 'GPU VRAM used'], 'jobs.running': ['jobs', 'Jobs running'] };
const PROMPTS = ['low-poly fox', 'wooden armchair', 'sci-fi supply crate', 'medieval lantern', 'toy robot', 'mossy boulder', 'desk lamp', 'treasure chest'];
export const WIDGET = { service: 'relay', id: 'traffic', title: 'LLM traffic', kind: 'bar', ranges: ['24h', '7d'], span: 6 };

function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const hash = (a, b) => { let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b | 0, 0xc2b2ae35); h ^= h >>> 16; h = Math.imul(h, 0x7feb352d); h ^= h >>> 15; h = Math.imul(h, 0x846ca68b); h ^= h >>> 16; return (h >>> 0) / 4294967296; };
const noise = (k, ts, per = MIN) => hash(k, Math.floor(ts / per));
const dayStart = ts => { const d = new Date(ts * 1000); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };
const nextDay = d0 => dayStart(d0 + DAY + 2 * HOUR);   // DST-safe
const ymd = ts => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const isNum = v => typeof v === 'number' && Number.isFinite(v);
const list = v => (Array.isArray(v) ? v : String(v ?? '').split(',')).flatMap(x => String(x).split(',')).map(x => x.trim()).filter(Boolean);
export const statSlug = label => String(label).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'stat';
export const statSeries = (id, label) => `svc.${id}.stat.${statSlug(label)}`;
/** A Stat as the summary shows it: numeric stats gain `series` (the metric they are recorded as). */
export const withSeries = (id, st) => (isNum(st.value) ? { ...st, series: statSeries(id, st.label) } : { ...st });

/** `"24h"` → ["24h", 86400]; `<n>m|h|d` up to 400 d. null when invalid. */
export function parseRange(r, def = '1h') {
  r = String(r || def).trim().toLowerCase();
  if (RANGES[r]) return [r, RANGES[r]];
  const m = /^(\d{1,4})([mhd])$/.exec(r); if (!m) return null;
  const s = Number(m[1]) * { m: MIN, h: HOUR, d: DAY }[m[2]];
  return s > 0 && s <= 400 * DAY ? [r, s] : null;
}
/** The hub's step rule: the range's default (or `step`) rounded to the table resolution, ≤ 2000 points. null when invalid. */
export function pickStep(secs, step) {
  const res = secs <= 6 * HOUR ? 10 : secs <= 7 * DAY ? MIN : HOUR;
  step = step == null || step === '' ? DEFAULT_STEP[secs] || Math.max(res, Math.ceil(secs / 360)) : Number(step);
  if (!(step > 0)) return null;
  step = Math.max(res, Math.ceil(step / res) * res);
  while (Math.ceil(secs / step) > 2000) step += res;
  return step;
}
export function axis(frm, to, step) { const t0 = Math.floor(frm / step) * step, out = []; for (let x = t0; x < to; x += step) out.push(x); return out.length ? out : [t0]; }
const days = (frm, to) => { const out = []; for (let d = dayStart(frm); d <= to; d = nextDay(d)) out.push(ymd(d)); return out; };

// ---------- the model: one plan per local day ----------
const plans = new Map();
function plan(d0) {
  let p = plans.get(d0); if (p) return p;
  const r = rng(Math.round(d0 / HOUR) * 7 + 11), h = x => d0 + x * HOUR, key = ymd(d0);
  p = { d0, lcpp: { from: h(9 + (r() - 0.5)), to: h(18 + (r() - 0.5) * 1.5) }, tts: [], gen3d: [], comfy: null, degraded: null, warns: [] };
  for (let a = h(8 + r() * 2); a < h(22);) { const busy = 120 + r() * 900; p.tts.push({ from: a, busy: a + busy, to: a + busy + 180, clips: 1 + Math.floor(busy / 150) }); a += busy + 180 + 1800 + r() * 4 * HOUR; }
  if (r() > 0.15) for (let a = h(10 + r() * 3), i = 0; a < h(21) && i < 3; i++) {
    const dur = 600 + r() * 1200, failed = r() < 0.12, prompt = PROMPTS[Math.floor(r() * PROMPTS.length)];
    p.gen3d.push({ id: `j_${key}_${i}`, label: `3D: ${prompt}`, prompt, from: a, to: a + (failed ? dur * 0.4 : dur), state: failed ? 'failed' : 'done', service: 'gen3d' });
    a += dur + 1800 + r() * 3 * HOUR;
  }
  if (r() < 0.55) { const a = h(13 + r() * 6); p.comfy = { from: a, to: a + HOUR + r() * 2.5 * HOUR, gb: 18 + r() * 4 }; }
  if (r() < 0.3) { const a = h(r() * 23); p.degraded = { from: a, to: a + 60 + r() * 120 }; }
  for (let n = Math.floor(r() * 3), i = 0; i < n; i++) p.warns.push(h(r() * 24));
  plans.set(d0, p); if (plans.size > 500) plans.delete(plans.keys().next().value);
  return p;
}
const inSpan = (s, ts) => s && ts >= s.from && ts < s.to;
function memModel(id, ts) {
  const p = plan(dayStart(ts));
  switch (id) {
    case 'relay': return 0.2 * GB + noise(1, ts) * 0.02 * GB;
    case 'example': return 0.05 * GB;
    case 'lcpp': return inSpan(p.lcpp, ts) ? (18.6 + noise(2, ts) * 0.3) * GB : 0.3 * GB;
    case 'tts': { const s = p.tts.find(x => inSpan(x, ts)); return s ? 9.2 * GB * Math.min(1, 0.05 + (ts - s.from) / 20) : 0; }
    case 'gen3d': { const j = p.gen3d.find(x => ts >= x.from && ts < x.to + 120); if (!j) return 0; if (ts >= j.to) return 30 * GB;
      const f = (ts - j.from) / (j.to - j.from); return (f < 0.1 ? 30 : f < 0.5 ? 40 : 50 + 2 * noise(3, ts)) * GB; }
    case 'comfy': { const c = p.comfy; return !inSpan(c, ts) ? 0 : ts < c.from + 40 ? 0.4 * GB : (c.gb + (noise(4, ts, 300) - 0.5) * 3) * GB; }
  }
  return null;
}
function stateModel(id, ts) {
  if (!MODEL_IDS.includes(id)) return null;
  const p = plan(dayStart(ts));
  if (id === 'comfy') return !inSpan(p.comfy, ts) ? 'stopped' : ts < p.comfy.from + 40 ? 'starting' : 'ready';
  return id === 'relay' && inSpan(p.degraded, ts) ? 'degraded' : 'ready';
}
const otherModel = ts => (13.5 + 0.8 * Math.sin(2 * Math.PI * (ts - dayStart(ts)) / DAY - 1.5) + 0.35 * Math.sin(ts / 5400) + 0.4 * (noise(9, ts) - 0.5)) * GB;
// relay traffic per hour (widget + stats)
function reqRate(hs) {
  const d = new Date(hs * 1000), hr = d.getHours(), wk = d.getDay() % 6 === 0 ? 0.45 : 1;
  return Math.round((6 + 120 * Math.exp(-(((hr - 13.5) / 3.8) ** 2))) * wk * (0.75 + 0.5 * hash(21, Math.floor(hs / HOUR))));
}
const tokRate = hs => Math.round(reqRate(hs) * (700 + 1100 * hash(23, Math.floor(hs / HOUR))));
const ttft = hs => Math.round(340 + 140 * hash(22, Math.floor(hs / HOUR)) + reqRate(hs) * 0.4);
function reqToday(ts) { let n = 0, hs = dayStart(ts); for (; hs + HOUR <= ts; hs += HOUR) n += reqRate(hs); return Math.round(n + reqRate(hs) * (ts - hs) / HOUR); }
function clipsToday(ts) { let n = 0; for (const s of plan(dayStart(ts)).tts) for (let i = 0; i < s.clips; i++) if (s.from + (i + 0.5) * (s.busy - s.from) / s.clips <= ts) n++; return n; }
// what the hub's activity log would hold for one day
function planActivity(p) {
  if (p.items) return p.items;
  const it = [], A = (ts, service, level, text) => it.push({ ts, service, level, text });
  A(p.lcpp.from, 'lcpp', 'info', 'LLM Launcher loaded (18.6 GB)'); A(p.lcpp.to, 'lcpp', 'info', 'LLM Launcher unloaded (freed 18.6 GB)');
  for (const s of p.tts) { A(s.from, 'tts', 'info', 'Speech loaded (9.2 GB)'); for (let i = 0; i < s.clips; i++) A(s.from + (i + 0.5) * (s.busy - s.from) / s.clips, 'tts', 'info', 'Speech generated a clip');
    A(s.to, 'tts', 'info', 'Speech unloaded — idle 3m (freed 9.2 GB)'); }
  for (const j of p.gen3d) { A(j.from, 'gen3d', 'info', `3D Generate started "${j.prompt}"`);
    A(j.to, 'gen3d', j.state === 'failed' ? 'error' : 'info', j.state === 'failed' ? `3D Generate failed "${j.prompt}": HIP error: out of memory` : `3D Generate finished "${j.prompt}"`); }
  if (p.comfy) { A(p.comfy.from, 'comfy', 'info', 'Images & Video started'); A(p.comfy.to, 'comfy', 'info', 'Images & Video stopped'); }
  if (p.degraded) { A(p.degraded.from, 'relay', 'warn', 'LLM Relay is not responding'); A(p.degraded.to, 'relay', 'info', 'LLM Relay recovered'); }
  for (const ts of p.warns) A(ts, 'relay', 'warn', 'Endpoint lab-box is unreachable');
  return (p.items = it.sort((a, b) => a.ts - b.ts));
}

/**
 * The chart half of the mock. `ctx`: { now, net, err, memory(), summaries(), outputs(), activity(), jobs() }.
 * Returns { api (the eight §11.7 methods), observe(ev) (a mock event listener), mode, setMode(mode) }.
 */
export function createHistory(ctx) {
  const { now, net, err } = ctx;
  const T0 = now(), rec = new Map(), liveJobs = new Map();
  let mode = 'normal', emptySince = 0, gap = null, lastRec = 0, liveCache = null;
  const sampleOf = (mem, sums) => {
    const s = { total: mem.total_bytes, used: mem.used_bytes, available: mem.available_bytes, reserve: mem.reserve_bytes, other: mem.other_bytes,
      gtt: mem.gpu?.gtt_used_bytes ?? null, vram: mem.gpu?.vram_total_bytes ? mem.gpu.vram_used_bytes : null,
      jobs: ctx.jobs().filter(j => j.state === 'running').length, svc: {}, state: {}, stats: {} };
    for (const r of mem.by_service) s.svc[r.id] = r.used_bytes;
    for (const x of sums) { s.state[x.id] = x.state; if (LIVE.includes(x.state)) for (const st of x.stats) if (isNum(st.value)) s.stats[statSeries(x.id, st.label)] ??= st.value; }
    return s;
  };
  const snapSums = ctx.summaries(), snap = sampleOf(ctx.memory(), snapSums);
  const snapSince = Object.fromEntries(snapSums.map(x => [x.id, x.state_since]));
  const snapStats = Object.fromEntries(snapSums.flatMap(x => x.stats.filter(st => isNum(st.value)).map(st => [statSeries(x.id, st.label), st.value])));
  const record = s => { const b = Math.floor(now() / 10) * 10; rec.set(b, s); lastRec = b; for (const k of rec.keys()) { if (k >= b - KEEP_REC) break; rec.delete(k); } };
  record(snap);
  const tailFrom = id => ['stopped', 'failed'].includes(snap.state[id]) ? Math.min(T0 - TAIL, snapSince[id] ?? T0) : T0 - TAIL;
  const inHist = ts => ts <= now() + 1 && ts >= (mode === 'empty' ? emptySince : T0 - HISTORY) && !(gap && ts >= gap[0] && ts < gap[1]);

  function liveSample() { const t = now(); if (!liveCache || t - liveCache.t > 1) liveCache = { t, s: sampleOf(ctx.memory(), ctx.summaries()) }; return liveCache.s; }
  const modelStatId = (id, name) => MODEL_IDS.includes(id) && name in snapStats;
  function modelSample(ts) {
    const s = { svc: {}, state: {}, stats: null, ts };
    let sum = 0;
    for (const id of MODEL_IDS) {
      const tail = ts >= tailFrom(id), v = tail ? snap.svc[id] ?? null : memModel(id, ts);
      s.svc[id] = v; s.state[id] = tail ? snap.state[id] ?? null : stateModel(id, ts); sum += v || 0;
    }
    const tf = T0 - TAIL;
    s.other = ts < tf ? otherModel(ts) : otherModel(tf) + (snap.other - otherModel(tf)) * Math.min(1, (ts - tf) / TAIL);
    Object.assign(s, { total: snap.total, reserve: liveSample().reserve, used: s.other + sum, gtt: snap.gtt == null ? null : 0.9 * sum, vram: snap.vram,
      jobs: ts >= tailFrom('gen3d') ? snap.jobs : plan(dayStart(ts)).gen3d.filter(j => inSpan(j, ts)).length });
    s.available = Math.max(0, s.total - s.used);
    s.stat = (id, name) => {
      if (!modelStatId(id, name) || !LIVE.includes(s.state[id])) return null;
      if (ts >= tailFrom(id)) return snap.stats[name] ?? null;
      const d0 = dayStart(ts);
      switch (name) {
        case 'svc.relay.stat.requests_today': return ts - d0 < 10 ? null : reqToday(ts);
        case 'svc.relay.stat.p50_ttft': return ttft(Math.floor(ts / HOUR) * HOUR);
        case 'svc.lcpp.stat.running': return inSpan(plan(d0).lcpp, ts) ? 1 : 0;
        case 'svc.tts.stat.clips_today': return ts - d0 < 10 ? null : clipsToday(ts);
        case 'svc.gen3d.stat.jobs': return Math.max(0, snapStats[name] - modelJobs(ts, T0).length);
      }
      return snapStats[name];
    };
    return s;
  }
  // The sample in effect at ts: null outside the history (gap, before it, after now).
  function sampleAt(ts) {
    if (!inHist(ts)) return null;
    if (ts < T0) return modelSample(ts);
    const b = Math.floor(ts / 10) * 10;
    return rec.get(b) ?? (b > lastRec ? liveSample() : null);
  }
  function pick(s, name) {
    if (!s) return null;
    if (MEM[name]) return s[MEM[name][0]] ?? null;
    if (name.startsWith('mem.svc.')) return s.svc[name.slice(8)] ?? null;
    const m = /^svc\.([^.]+)\.stat\..+$/.exec(name);
    return m ? (s.stat ? s.stat(m[1], name) : s.stats[name]) ?? null : null;
  }
  function seriesInfos() {
    const sums = ctx.summaries(), mem = ctx.memory(), out = [];
    for (const [n, [, label]] of Object.entries(MEM)) if (!n.startsWith('gpu.') || (n === 'gpu.gtt_used' ? mem.gpu : mem.gpu?.vram_total_bytes)) out.push({ name: n, label, unit: n === 'jobs.running' ? 'count' : 'bytes' });
    for (const x of sums) if (!x.manifest_errors?.length) {
      out.push({ name: `mem.svc.${x.id}`, label: x.name, unit: 'bytes', service: x.id });
      for (const st of x.stats) if (isNum(st.value)) out.push({ name: statSeries(x.id, st.label), label: st.label, unit: st.unit === 'ms' ? 'ms' : 'count', service: x.id, ...(st.reset ? { reset: st.reset } : {}) });
    }
    return [...new Map(out.map(i => [i.name, i])).values()].sort((a, b) => (a.name < b.name ? -1 : 1));
  }

  // ---------- events: jobs, activity ----------
  function modelJobs(frm, to) {
    const out = [], hi = Math.min(to, T0, tailFrom('gen3d'));
    for (let d = dayStart(Math.max(frm, T0 - HISTORY)); d < hi; d = nextDay(d)) for (const j of plan(d).gen3d) if (j.from >= frm && j.from < hi) out.push(j);
    return out;
  }
  function jobsIn(frm, to) {   // jobs overlapping [frm, to) that the hub would have recorded
    const all = [...modelJobs(frm - DAY, to).filter(j => j.to >= frm), ...[...liveJobs.values()].filter(j => j.from < to && (j.to == null || j.to >= frm))];
    return all.filter(j => inHist(j.from) || (j.from < frm && inHist(frm)));
  }
  function activityIn(frm, to) {
    const out = [];
    for (let d = dayStart(Math.max(frm, T0 - HISTORY)); d < Math.min(to, T0); d = nextDay(d)) for (const a of planActivity(plan(d))) if (a.ts >= frm && a.ts < Math.min(to, T0, tailFrom(a.service)) && inHist(a.ts)) out.push(a);
    for (const a of ctx.activity()) if (a.ts >= frm && a.ts < to && inHist(a.ts)) out.push(a);
    return out.sort((a, b) => a.ts - b.ts);
  }
  function observe(ev) {
    if (ev.type === 'memory') { liveCache = null; record(sampleOf(ev.memory, ctx.summaries())); }
    else if (ev.type === 'job') { const j = ev.job, t = now(), cur = liveJobs.get(j.id) ?? { id: j.id, service: j.service, from: t, to: null };
      Object.assign(cur, { label: j.label || j.id, state: j.state }); if (['done', 'failed', 'cancelled'].includes(j.state)) cur.to ??= t; liveJobs.set(j.id, cur); }
  }

  const range = (r, def) => { const x = parseRange(r, def); if (!x) throw err(422, 'invalid_request', `range ${JSON.stringify(r)}: use 1h, 6h, 24h, 7d, 30d or <n>m|h|d`); return x; };
  const pct = (xs, p) => { if (!xs.length) return 0; xs = [...xs].sort((a, b) => a - b); return +xs[Math.max(0, Math.min(xs.length - 1, Math.ceil(p * xs.length) - 1))].toFixed(3); };

  const api = {
    async getMetrics({ series, range: r = '1h', step } = {}) {
      await net();
      const [name, secs] = range(r, '1h'), names = list(series);
      if (!names.length) throw err(422, 'invalid_request', 'series: name at least one series');
      const step_s = pickStep(secs, step); if (!step_s) throw err(422, 'invalid_request', 'step must be a positive number of seconds');
      const known = seriesInfos().map(i => i.name);
      const want = [...new Set(names.flatMap(n => (n.endsWith('.*') ? known.filter(k => k.startsWith(n.slice(0, -1))) : [n])))];
      const to = now(), t = axis(to - secs, to, step_s), out = Object.fromEntries(want.map(n => [n, []]));
      const k = step_s <= 10 ? 1 : Math.min(24, Math.ceil(step_s / 10));
      for (const b of t) {
        const pts = []; for (let i = 0; i < k; i++) { const p = b + (i + 0.5) * step_s / k; if (p <= to) pts.push(p); }
        if (to >= b && to < b + step_s && !pts.includes(to)) pts.push(to);
        if (!pts.length) pts.push(b);
        const samples = pts.map(sampleAt);
        for (const n of want) {
          let sum = 0, c = 0; for (const s of samples) { const v = pick(s, n); if (v != null) { sum += v; c++; } }
          out[n].push(c ? sum / c : null);
        }
      }
      return { range: name, step_s, t, series: out };
    },
    async listMetricSeries() { await net(); return seriesInfos(); },
    async getTimeline({ range: r = '24h', services } = {}) {
      await net();
      const [, secs] = range(r, '24h'), to = now(), frm = to - secs, sums = ctx.summaries();
      const ids = list(services).length ? list(services) : sums.map(x => x.id);
      const est = Object.fromEntries(sums.map(x => [x.id, x.memory.estimate_bytes]));
      const res = [10, 20, 30, 60, 120, 300, 600, 1800, 3600].find(x => secs / x <= 5000) || 3600;
      const grid = []; for (let g = frm; g < to; g += res) grid.push(g);
      const samples = grid.map(g => sampleAt(Math.min(to, g + res / 2)));
      const runs = vals => { const out = []; let cur = null;
        vals.forEach((v, i) => { if (v == null || v === false) { cur = null; return; } const b = Math.min(to, grid[i] + res);
          if (cur && cur.v === v) cur.to = b; else out.push(cur = { from: grid[i], to: b, v }); });
        return out; };
      const jobs = jobsIn(frm, to), acts = activityIn(frm, to), outs = ctx.outputs();
      const lanes = ids.map(id => ({
        service: id,
        states: runs(samples.map(s => s?.state[id] ?? null)).map(x => ({ from: x.from, to: x.to, state: x.v })),
        loaded: est[id] ? runs(samples.map(s => s?.svc[id] != null && s.svc[id] > est[id] * 0.5)).map(x => ({ from: x.from, to: x.to })) : [],
        jobs: jobs.filter(j => j.service === id).sort((a, b) => a.from - b.from).map(j => ({ id: j.id, label: j.label, from: Math.max(j.from, frm), to: j.to == null ? null : Math.min(j.to, to), state: j.state })),
        outputs: outs.filter(o => o.service === id && o.created_ts >= frm && o.created_ts < to && (mode !== 'empty' || o.created_ts >= emptySince))
          .sort((a, b) => a.created_ts - b.created_ts).map(o => ({ ts: o.created_ts, id: o.id, kind: o.kind })),
        events: acts.filter(a => a.service === id && (a.level === 'warn' || a.level === 'error')).map(a => ({ ts: a.ts, level: a.level, text: a.text })),
      }));
      return { from: frm, to, lanes };
    },
    async getOutputStats({ range: r = '30d', by = 'day' } = {}) {
      await net();
      const [, secs] = range(r, '30d'), to = now(), frm = to - secs;
      if (!['day', 'service', 'kind'].includes(by)) throw err(422, 'invalid_request', 'by: use day, service or kind');
      const buckets = new Map(by === 'day' ? days(frm, to).map(d => [d, { key: d, count: 0, size_bytes: 0, by_kind: {} }]) : []);
      for (const o of ctx.outputs()) {
        if (o.hidden || o.created_ts < frm || o.created_ts >= to || (mode === 'empty' && o.created_ts < emptySince)) continue;
        const key = by === 'day' ? ymd(o.created_ts) : o[by];
        if (!buckets.has(key)) buckets.set(key, { key, count: 0, size_bytes: 0, by_kind: {} });
        const b = buckets.get(key); b.count++; b.size_bytes += o.size_bytes || 0; b.by_kind[o.kind] = (b.by_kind[o.kind] || 0) + 1;
      }
      const out = [...buckets.values()];
      if (by !== 'day') out.sort((a, b) => b.count - a.count || (a.key < b.key ? -1 : 1));
      return { buckets: out };
    },
    async getActivityStats({ range: r = '14d' } = {}) {
      await net();
      const [, secs] = range(r, '14d'), to = now(), frm = to - secs, cells = new Map();
      for (const d of days(frm, to)) for (let h = 0; h < 24; h++) cells.set(`${d} ${h}`, { day: d, hour: h, count: 0, errors: 0 });
      for (const a of activityIn(frm, to)) { const c = cells.get(`${ymd(a.ts)} ${new Date(a.ts * 1000).getHours()}`); if (c) { c.count++; c.errors += a.level === 'error' ? 1 : 0; } }
      return { cells: [...cells.values()] };
    },
    async getJobStats({ range: r = '7d' } = {}) {
      await net();
      const [, secs] = range(r, '7d'), to = now(), frm = to - secs, per = new Map();
      for (const j of jobsIn(frm, to)) {
        if (j.from < frm) continue;
        const p = per.get(j.service) ?? { count: 0, failed: 0, d: [] }; per.set(j.service, p);
        p.count++; p.failed += j.state === 'failed' ? 1 : 0; if (j.state === 'done' && j.to != null) p.d.push(Math.max(0, j.to - j.from));
      }
      const order = ctx.summaries().map(x => x.id), ids = [...order.filter(id => per.has(id)), ...[...per.keys()].filter(id => !order.includes(id)).sort()];
      return { by_service: ids.map(id => { const p = per.get(id); return { service: id, count: p.count, failed: p.failed, p50_s: pct(p.d, 0.5), p90_s: pct(p.d, 0.9), max_s: p.d.length ? +Math.max(...p.d).toFixed(3) : 0 }; }) };
    },
    async listWidgets() { await net(); const s = ctx.summaries().find(x => x.id === WIDGET.service); return s && LIVE.includes(s.state) ? [{ ...WIDGET, ranges: [...WIDGET.ranges] }] : []; },
    async getWidget(service, id, { range: r } = {}) {
      await net();
      const s = ctx.summaries().find(x => x.id === service);
      if (!s) throw err(404, 'service_not_found', `No service "${service}"`);
      if (service !== WIDGET.service || id !== WIDGET.id) throw err(404, 'widget_not_found', `${s.name} has no widget '${id}'`);
      r = r || WIDGET.ranges[0];
      if (!WIDGET.ranges.includes(r)) throw err(422, 'invalid_request', `range '${r}': ${WIDGET.title} offers ${WIDGET.ranges.join(', ')}`);
      if (!LIVE.includes(s.state)) throw err(503, 'service_not_running', `${s.name} is not running`);
      const to = now(), t = axis(to - RANGES[r], to, HOUR);
      const ok = h => (mode === 'empty' ? h >= emptySince : h >= T0 - HISTORY), part = h => Math.min(1, (to - h) / HOUR);
      return { unit: 'count', t, series: [
        { name: 'Requests', values: t.map(h => (ok(h) ? Math.round(reqRate(h) * part(h)) : null)) },
        { name: 'Tokens', values: t.map(h => (ok(h) ? Math.round(tokRate(h) * part(h)) : null)), axis: 'right' },
        { name: 'p50 TTFT (ms)', values: t.map(h => (ok(h) ? ttft(h) : null)), axis: 'right' },
      ] };
    },
  };
  return {
    api, observe,
    get mode() { return mode; },
    /** 'normal' | 'empty' (a fresh install: nothing before now − 15 s) | 'gaps' (the hub was down for 2 h ending 3 h ago). */
    setMode(m) {
      if (!['normal', 'empty', 'gaps'].includes(m)) throw new Error(`history mode ${m}: use normal, empty or gaps`);
      const t = now(); mode = m; emptySince = m === 'empty' ? t - 15 : 0; gap = m === 'gaps' ? [t - 5 * HOUR, t - 3 * HOUR] : null;
    },
  };
}
