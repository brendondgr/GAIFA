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
