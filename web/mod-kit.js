// Shared pieces for the built-in mods' page modules (Part B): the "not running" state, calls that
// may need memory (make room and retry), a segmented control, tabs-within-a-tab, and formatting.
// Written by us, not Claude Design. Import from a page module as '/mod-kit.js'.

import { h } from './mod-ui.js';

export const GB = 1e9;
export const MONO = "'JetBrains Mono',ui-monospace,monospace";

export function fmtBytes(b) {
  if (b == null) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1000 && i < u.length - 1) { b /= 1000; i++; }
  return `${b >= 100 || i === 0 ? Math.round(b) : b.toFixed(1)} ${u[i]}`;
}
export function fmtSecs(s) {
  if (s == null || !isFinite(s)) return '—';
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}
export function fmtAgo(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** True when the mod can take calls; otherwise fills `el` with a Start button and returns false. */
export function requireRunning(el, ctx, what = 'this page') {
  const svc = ctx.service;
  if (svc.state === 'ready' || svc.state === 'degraded') return true;
  const { ui } = ctx;
  const starting = svc.state === 'starting';
  el.append(ui.empty(starting ? `${svc.name} is starting…` : `${svc.name} is not running`,
    starting ? 'This page opens as soon as it is ready.' : `Start it to use ${what}.`,
    starting ? null : ui.button(`Start ${svc.name}`, () => ctx.api.startService(svc.id).catch(e => ctx.toast(e.detail || 'Start failed', 'error')), { kind: 'primary' })));
  return false;
}

/** ctx.call that answers the hub's `needs_room` (409) by asking, then retrying with makeRoom. */
export async function callRoom(ctx, method, path, opts = {}) {
  try {
    return await ctx.call(method, path, opts);
  } catch (e) {
    // From the hub (a memory trigger) the plan is in e.data; from a mod that asked the hub itself
    // (lcpp's launch), the mod's own error body carries it: { code: 'needs_room', data: { plan } }.
    const body = e.data?.body;
    const p = e.code === 'needs_room' ? e.data?.plan : body?.code === 'needs_room' ? body.data?.plan : null;
    if (!p) throw e;
    const names = (p.unload || []).map(u => `${u.id} (${fmtBytes(u.frees_bytes)})`).join(', ');
    const go = await ctx.confirm({
      title: p.enough ? 'Make room?' : 'Not enough memory',
      body: p.enough
        ? `${ctx.service.name} needs about ${fmtBytes(p.needs_bytes)}; ${fmtBytes(p.available_bytes)} is free. Unload ${names || 'nothing'} and continue?`
        : `${ctx.service.name} needs about ${fmtBytes(p.needs_bytes)}, and unloading ${names || 'everything idle'} still isn't enough. Try anyway?`,
      danger: !p.enough,
    });
    if (!go) { const err = new Error('Cancelled'); err.cancelled = true; throw err; }
    return ctx.call(method, path, { ...opts, makeRoom: true });
  }
}

/** segmented([{value,label}], value, onChange) → a button group (aria-pressed); .set(value) updates it. */
export function segmented(options, value, onChange, label = '') {
  const wrap = h('div', { role: 'group', 'aria-label': label, style: 'display:inline-flex;padding:2px;border-radius:7px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);gap:2px' });
  const btns = options.map(o => h('button', {
    type: 'button', onclick: () => { wrap.set(o.value); onChange(o.value); },
    style: 'height:26px;padding:0 12px;border:0;border-radius:5px;font:inherit;font-size:12px;cursor:pointer;color:var(--mut,#8A94A6);background:transparent',
  }, o.label));
  wrap.append(...btns);
  wrap.set = v => btns.forEach((b, i) => {
    const on = options[i].value === v;
    b.setAttribute('aria-pressed', String(on));
    b.style.background = on ? 'var(--card,#11151D)' : 'transparent';
    b.style.color = on ? 'var(--tx,#E6EAF2)' : 'var(--mut,#8A94A6)';
    b.style.fontWeight = on ? '600' : '400';
  });
  wrap.set(value);
  return wrap;
}

/** A card header: uppercase title on the left, optional controls on the right. */
export const header = (title, ...right) => h('div', { style: 'display:flex;align-items:center;gap:8px;min-height:24px' },
  h('h2', { style: 'margin:0;flex:1;min-width:0;font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--mut,#8A94A6)' }, title), ...right);

/** A compact panel (the revision 2 card: 9 px radius, 12 px padding). */
export const panel = (...kids) => h('section', { style: 'background:var(--card,#11151D);border:1px solid var(--bd,#1D2430);border-radius:9px;padding:12px;display:flex;flex-direction:column;gap:10px;min-width:0' }, ...kids);

/** Two columns on wide screens (main + side), one column under 980 px. */
export function columns(main, side, sideW = 340) {
  const el = h('div', { style: `display:grid;gap:12px;grid-template-columns:minmax(0,1fr) ${sideW}px;align-items:start` }, main, side);
  const mq = window.matchMedia('(max-width: 980px)');
  const fit = () => { el.style.gridTemplateColumns = mq.matches ? 'minmax(0,1fr)' : `minmax(0,1fr) ${sideW}px`; };
  fit(); mq.addEventListener('change', fit);
  el.cleanup = () => mq.removeEventListener('change', fit);
  return el;
}

/** A labelled stat: small uppercase label over a mono value. */
export const stat = (label, value) => h('div', { style: 'display:flex;flex-direction:column;gap:2px;min-width:0' },
  h('span', { style: 'font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut,#8A94A6)' }, label),
  h('span', { style: `font-family:${MONO};font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis` }, value));

/** localStorage that never throws (private windows, blocked storage). */
function local(storage) {
  return {
    get(k, d = null) { try { const v = storage?.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { storage?.setItem(k, JSON.stringify(v)); } catch { /* not kept */ } },
  };
}

/** What a page remembers (settings-that-stick 4.2). Keys start with the mod's id (`tts.speak`, `comfy.values.<wf>`);
 *  each mod's values are kept on the hub (`/api/ui/store/<mod>`), loaded before its page mounts, so a choice is the
 *  same in every browser. This browser keeps a copy for when the hub is down. `store.local` (and any key ending in
 *  `.draft`, text being typed) stays in this browser only. A mod's values saved here before are copied up once. */
export function createStore({ storage = globalThis.localStorage } = {}) {
  const loc = local(storage), hub = new Map();   // mod → its values from the hub
  let api = null;
  const scopeOf = k => String(k).split('.')[0];
  const isLocal = k => /\.draft$/.test(String(k));
  const s = {
    local: loc,
    attach(a) { api = a; },
    /** The mod's values from the hub (the shell calls it before mounting the page); quietly local-only without it. */
    async load(a, mod) {
      if (a) api = a;
      if (!api?.getUiStore || !mod) return;
      try {
        const values = (await api.getUiStore(mod)).values || {};
        hub.set(mod, values);
        await importLocal(mod, values);
      } catch { /* the hub's down or the store isn't live: this browser's copy */ }
    },
    get(k, d = null) {
      const m = hub.get(scopeOf(k));
      if (!isLocal(k) && m && Object.prototype.hasOwnProperty.call(m, k)) return JSON.parse(JSON.stringify(m[k]));
      return loc.get(k, d);
    },
    set(k, v) {
      loc.set(k, v);
      if (isLocal(k) || !api?.saveUiStore) return;
      const mod = scopeOf(k), m = hub.get(mod);
      if (m) m[k] = JSON.parse(JSON.stringify(v));
      api.saveUiStore(mod, { set: { [k]: v } }).catch(() => { /* kept in this browser */ });
    },
  };
  async function importLocal(mod, values) {
    const mark = `gaifa.prefs.imported.${mod}`;
    try { if (storage?.getItem(mark)) return; } catch { return; }
    const set = {};
    try {
      for (let i = 0; i < (storage?.length || 0); i++) {
        const k = storage.key(i);
        if (k && k.startsWith(mod + '.') && !isLocal(k) && !(k in values)) { try { set[k] = JSON.parse(storage.getItem(k)); } catch { /* not JSON: skip */ } }
      }
    } catch { return; }
    if (Object.keys(set).length) {
      try { const r = await api.saveUiStore(mod, { set }); hub.set(mod, r.values || { ...values, ...set }); } catch { return; }
    }
    try { storage?.setItem(mark, '1'); } catch { /* asked again next time */ }
  }
  return s;
}

/** The pages' one store. */
export const store = createStore();
