// What each page remembers, kept on the hub (plan settings-that-stick 4.2–4.3): `/api/ui/store/<scope>`, a scope being
// a mod id (its page's choices: `tts.speak`, `comfy.values.<wf>`) or `hub` (the hub's own: the chat panes, folded
// Settings groups, recent copy formats, a table's sort). This browser keeps a copy for the first paint and for when the
// hub is down. Re-exported by mod-kit.js for the mods' pages. Written by us (web/PATCHES.md).

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
export function createStore({ storage = globalThis.localStorage, legacy = {} } = {}) {
  const loc = local(storage), hub = new Map(), timers = new Map();   // mod → its values from the hub; key → a save waiting
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
      const v = loc.get(k, undefined);
      return v !== undefined ? v : legacy[k] ? loc.get(legacy[k], d) : d;
    },
    /** `wait` (ms): save to the hub once the value has stopped changing for that long (a divider being dragged). */
    set(k, v, { wait = 0 } = {}) {
      loc.set(k, v);
      if (isLocal(k) || !api?.saveUiStore) return;
      const mod = scopeOf(k), m = hub.get(mod), val = JSON.parse(JSON.stringify(v));
      if (m) m[k] = val; else hub.set(mod, { [k]: val });   // not loaded yet: this page still reads it back
      const send = () => { timers.delete(k); api.saveUiStore(mod, { set: { [k]: val } }).catch(() => { /* kept in this browser */ }); };
      clearTimeout(timers.get(k));
      if (wait > 0) timers.set(k, setTimeout(send, wait)); else send();
    },
  };
  async function importLocal(mod, values) {
    const mark = `gaifa.prefs.imported.${mod}`;
    try { if (storage?.getItem(mark)) return; } catch { return; }
    const set = {}, olds = Object.entries(legacy).filter(([k]) => scopeOf(k) === mod);
    try {
      if (olds.length) {   // a scope with a map of its old keys (the hub's): only those
        for (const [k, old] of olds) { const raw = storage?.getItem(k) ?? storage?.getItem(old); if (raw != null && !(k in values)) { try { set[k] = JSON.parse(raw); } catch { /* not JSON */ } } }
      } else {
        for (let i = 0; i < (storage?.length || 0); i++) {
          const k = storage.key(i);
          if (k && k.startsWith(mod + '.') && !isLocal(k) && !(k in values)) { try { set[k] = JSON.parse(storage.getItem(k)); } catch { /* not JSON: skip */ } }
        }
      }
    } catch { return; }
    if (Object.keys(set).length) {
      try { const r = await api.saveUiStore(mod, { set }); hub.set(mod, r.values || { ...values, ...set }); } catch { return; }
    }
    try { storage?.setItem(mark, '1'); } catch { /* asked again next time */ }
  }
  return s;
}

/** The hub's own keys (scope `hub`, settings-that-stick 4.3) and where this browser kept them before. */
export const HUB_KEYS = { 'hub.chat.layout': 'gaifa.chat.layout', 'hub.settings.open': 'gaifa.settings.open', 'hub.chat.copyModes': 'gaifa.chat.copyModes', 'hub.table.sort': 'hub.tableSort' };

/** The page's one store: the mods' pages and the hub's own. */
export const store = createStore({ legacy: HUB_KEYS });
