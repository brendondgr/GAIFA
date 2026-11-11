// The UI's choices, kept in config.toml (plan settings-that-stick 3.2): `ui.chat`, `ui.overview`, … as GET /api/settings
// gives them. The hub's value always wins; this browser keeps a copy (`gaifa.ui.cache`) only so the first paint
// doesn't wait for the hub. `set` shows the change at once and saves `{ui: {<table>: …}}` with its `base`
// (settings-merge), so two tabs changing different keys keep both. A save that fails keeps the value for this page.
// The shell attaches its api and passes every reload (`gaifa:settings`, Hub.dc.html applySettings). Written by us
// (web/PATCHES.md).

export const CACHE_KEY = 'gaifa.ui.cache';
const clone = v => (v === undefined ? v : JSON.parse(JSON.stringify(v)));
const getPath = (o, p) => String(p).split('.').reduce((x, k) => (x == null ? undefined : x[k]), o);
function setPath(o, p, v) {
  const ks = String(p).split('.'), last = ks.pop();
  let x = o;
  for (const k of ks) { if (x[k] == null || typeof x[k] !== 'object') x[k] = {}; x = x[k]; }
  x[last] = v;
}

export function createUiPrefs({ storage = globalThis.localStorage } = {}) {
  let ui = null, api = null, loaded = false;
  const subs = new Set(), pending = new Map();   // table → saves in flight (a reload doesn't undo a change still saving)
  const read = () => { try { return JSON.parse(storage?.getItem(CACHE_KEY) || 'null') || {}; } catch { return {}; } };
  const write = () => { try { storage?.setItem(CACHE_KEY, JSON.stringify(ui)); } catch { /* private window: the hub still has it */ } };
  const now = () => (ui ??= read());
  const emit = () => subs.forEach(f => { try { f(ui); } catch { /* a listener */ } });

  const prefs = {
    onError: null,
    get loaded() { return loaded; },
    /** The value at `path` under `ui` (`chat.steps`), else `d`. */
    get(path, d) { const v = getPath(now(), path); return v === undefined ? d : v; },
    /** The shell's api: saves go through it. */
    attach(a) { api = a; },
    /** Read the hub's settings once (the shell does this at start). */
    async load(a = api) { if (a) api = a; const st = await api.getSettings(); prefs.apply(st); return ui; },
    /** Fresh settings from the hub: its `ui` replaces the copy, except tables with a save still in flight. */
    apply(st) {
      const fresh = clone(st?.ui || {}), cur = now();
      for (const t of pending.keys()) if (cur[t] !== undefined) fresh[t] = cur[t];
      ui = fresh; loaded = true; write(); emit();
    },
    async set(path, v) {
      const table = String(path).split('.')[0], was = clone(now()[table]);
      const next = clone(now()); setPath(next, path, clone(v)); ui = next; write(); emit();
      if (!api?.saveSettings) return;
      pending.set(table, (pending.get(table) || 0) + 1);
      try {
        const body = { ui: { [table]: clone(ui[table]) } };
        const r = await api.saveSettings(body, was !== undefined && typeof was === 'object' ? { base: { ui: { [table]: was } } } : {});
        const n = pending.get(table) - 1; n ? pending.set(table, n) : pending.delete(table);
        if (!pending.has(table) && r?.settings?.ui) { ui = { ...ui, [table]: clone(r.settings.ui[table]) }; write(); emit(); }
      } catch (e) {
        const n = pending.get(table) - 1; n ? pending.set(table, n) : pending.delete(table);
        prefs.onError?.(e, path);   // the value stays for this page
      }
    },
    subscribe(f) { subs.add(f); return () => subs.delete(f); },
  };
  return prefs;
}

/** The page's one copy. */
export const uiPrefs = createUiPrefs();

/** `[value, set]` for `path` under `ui`, redrawn when it changes (here, in another tab, or by a reload). */
export function useUiPref(path, d, prefs = uiPrefs) {
  const React = globalThis.React, [, setN] = React.useState(0);
  React.useEffect(() => prefs.subscribe(() => setN(n => n + 1)), [prefs]);
  return [prefs.get(path, d), v => prefs.set(path, v)];
}

// ---------- 3.3: this browser's old choices, saved to config.toml once ----------
export const IMPORTED_KEY = 'gaifa.prefs.imported';
const OVERVIEW = { view: ['dashboard', 'table', 'timeline'],   // no Services view since overview-bento 3.1
  range: ['1h', '6h', '24h', '7d'] };
const LIST = { group: ['environment', 'date', 'none'], envOrder: ['activity', 'name', 'created'], chatOrder: ['updated', 'title', 'created'] };

/** What to save from this browser: each choice it made (not the default) that config.toml doesn't set yet.
 *  `ui` is GET /api/settings's `ui`. Old `aihub.*` copies count too. Returns a `ui` patch (maybe empty). */
export function browserChoices(ui, storage) {
  const raw = k => { try { return storage?.getItem(k) ?? (k.startsWith('gaifa.') ? storage?.getItem('aihub.' + k.slice(6)) : null); } catch { return null; } };
  const json = k => { try { const v = raw(k); return v == null ? null : JSON.parse(v); } catch { return null; } };
  const out = {}, chat = ui?.chat || {}, ov = ui?.overview || {}, put = (t, k, v) => { (out[t] ||= {})[k] = v; };
  const steps = json('gaifa.chat.steps');
  if (steps === 'split' && (chat.steps ?? 'fold') === 'fold') put('chat', 'steps', 'split');
  const env = json('gaifa.chat.environment');
  if (typeof env === 'string' && env && chat.environment == null) put('chat', 'environment', env);
  const lv = json('gaifa.chat.list'), cl = chat.list || {};
  const listDefault = (cl.group ?? 'environment') === 'environment' && (cl.env_order ?? 'activity') === 'activity' && (cl.chat_order ?? 'updated') === 'updated' && !(cl.collapsed || []).length;
  if (lv && typeof lv === 'object' && listDefault) {
    const l = {};
    if (LIST.group.includes(lv.group) && lv.group !== 'environment') l.group = lv.group;
    if (LIST.envOrder.includes(lv.envOrder) && lv.envOrder !== 'activity') l.env_order = lv.envOrder;
    if (LIST.chatOrder.includes(lv.chatOrder) && lv.chatOrder !== 'updated') l.chat_order = lv.chatOrder;
    if (Array.isArray(lv.collapsed) && lv.collapsed.length) l.collapsed = lv.collapsed.map(String);
    if (Object.keys(l).length) put('chat', 'list', l);
  }
  const view = raw('hub.ovView'), tl = raw('hub.tlRange'), sv = raw('hub.svcRange');
  if (OVERVIEW.view.includes(view) && view !== 'dashboard' && (ov.view ?? 'dashboard') === 'dashboard') put('overview', 'view', view);
  if (OVERVIEW.range.includes(tl) && tl !== '24h' && (ov.timeline_range ?? '24h') === '24h') put('overview', 'timeline_range', tl);
  if (OVERVIEW.range.includes(sv) && sv !== '24h' && (ov.services_range ?? '24h') === '24h') put('overview', 'services_range', sv);
  const theme = raw('hub.theme'), density = raw('hub.density');
  if (['light', 'dark'].includes(theme) && (ui?.theme ?? 'system') === 'system') out.theme = theme;
  if (density === 'comfortable' && (ui?.density ?? 'compact') === 'compact') out.density = density;
  return out;
}

/** Once per browser: save `browserChoices` (one PUT), then mark it done. */
export async function importBrowser(api, st, storage = globalThis.localStorage) {
  try { if (storage?.getItem(IMPORTED_KEY)) return null; } catch { return null; }
  const patch = browserChoices(st?.ui, storage);
  if (Object.keys(patch).length) {
    const r = await api.saveSettings({ ui: patch });
    if (r?.settings) uiPrefs.apply(r.settings);
  }
  try { storage?.setItem(IMPORTED_KEY, '1'); } catch { /* private window: asked again next time, harmless */ }
  return patch;
}
