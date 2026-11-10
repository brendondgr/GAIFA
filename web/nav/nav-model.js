// The sidebar's model (plan 33): its groups, which services it lists and how, each service's state
// as active / inactive / failed, and the monogram a mod without a logo gets. Pure, so
// utils/tests/web/nav.test.mjs tests it without a page. The sidebar is web/nav/sidebar.js, the
// Services page web/nav/services-page.js; the choices are Settings.ui.nav (config.toml [ui.nav]).

export const DEFAULT_NAV = { collapsed: false, services: 'list', hidden: [], folded: false };
export const MODES = [['list', 'List'], ['button', 'Button'], ['counts', 'Button with counts']];
export const CACHE_KEY = 'hub.nav';

/** Settings.ui.nav as sent, or anything stored: always a whole, valid nav. */
export function normNav(x) {
  const n = x && typeof x === 'object' ? x : {};
  return {
    collapsed: n.collapsed === true,
    services: MODES.some(([k]) => k === n.services) ? n.services : 'list',
    hidden: Array.isArray(n.hidden) ? [...new Set(n.hidden.filter(id => typeof id === 'string'))] : [],
    folded: n.folded === true,
  };
}

export function readCache(storage = globalThis.localStorage) {
  try { return normNav(JSON.parse(storage?.getItem(CACHE_KEY) || 'null')); } catch { return normNav(null); }
}
export function writeCache(nav, storage = globalThis.localStorage) {
  try { storage?.setItem(CACHE_KEY, JSON.stringify(normNav(nav))); } catch { /* private window: the settings still have it */ }
}

/** active: ready, degraded, starting · inactive: stopped, stopping · failed: failed, or a manifest error. */
export function bucket(sv) {
  if (!sv || sv.manifest_errors?.length || sv.state === 'failed') return 'failed';
  return ['ready', 'degraded', 'starting'].includes(sv.state) ? 'active' : 'inactive';
}
export const BUCKETS = {
  active: { label: 'Active', color: 'var(--gr,#3FB950)', tint: 'var(--tgr,rgba(63,185,80,.13))' },
  inactive: { label: 'Inactive', color: 'var(--dim,#737D90)', tint: 'var(--hov,#161C28)' },
  failed: { label: 'Failed', color: 'var(--rd,#F85149)', tint: 'var(--trd,rgba(248,81,73,.13))' },
};
/** Starting and stopping pulse. */
export const pulses = sv => sv?.state === 'starting' || sv?.state === 'stopping';

export function counts(services) {
  const c = { active: 0, inactive: 0, failed: 0, total: 0 };
  for (const sv of services || []) { c[bucket(sv)]++; c.total++; }
  return c;
}
export function countsText(c) {
  const parts = ['active', 'inactive', 'failed'].filter(k => c[k]).map(k => `${c[k]} ${k}`);
  return parts.length ? parts.join(' · ') : 'No services';
}

/** The services the sidebar lists: all but the hidden ones, in the hub's order (new mods show). */
export function visible(services, nav) {
  const hidden = new Set(normNav(nav).hidden);
  return (services || []).filter(sv => !hidden.has(sv.id));
}

/** Hide or show one mod; ids of removed mods are dropped as the list is written again. */
export function setHidden(nav, services, id, hide) {
  const n = normNav(nav), known = new Set((services || []).map(s => s.id));
  const hidden = n.hidden.filter(x => x !== id && known.has(x));
  return { ...n, hidden: hide ? [...hidden, id] : hidden };
}
export function setAllHidden(nav, services, hide) {
  return { ...normNav(nav), hidden: hide ? (services || []).map(s => s.id) : [] };
}

/** The agent page's tabs that the sidebar's Memory entry stands for (memory-auto-learning 4.2). */
export const MEMORY_TABS = ['memory', 'review', 'learning'];

/** The fixed items: Overview, Chat and Outputs on top, each followed by the mods whose page is a main view there
 *  (`main.after`, calendar 3.1: the Calendar after Chat, with its manifest icon in the items' muted colour, and its badge); Memory (with the agent mod),
 *  Models and Settings at the bottom. */
export function groups(route, services) {
  const r = route || { page: 'overview', parts: [] }, has = id => (services || []).some(s => s.id === id);
  const memory = r.page === 'service' && r.parts[1] === 'agent' && MEMORY_TABS.includes(r.parts[2]);
  const item = (key, label, href, icon, on) => ({ key, label, href, icon, on: !!on, hint: HINTS[key] });
  const mains = after => (services || []).filter(s => s.main && s.main.after === after)
    .map(s => ({ key: 'main:' + s.id, label: s.main.label, href: '#/' + s.id, icon: s.icon || 'puzzle', on: r.page === s.id, hint: s.description || '', badge: s.badge || 0 }));   // the manifest's icon, drawn like the hub's own items
  return {
    top: [item('overview', 'Overview', '#/overview', 'grid', r.page === 'overview'), ...mains('overview'), item('chat', 'Chat', '#/chat', 'chat', r.page === 'chat'),
      ...mains('chat'), item('outputs', 'Outputs', '#/outputs', 'folder', r.page === 'outputs'), ...mains('outputs')],
    bottom: [...(has('agent') ? [item('memory', 'Memory', '#/s/agent/memory', 'bulb', memory)] : []),
      item('models', 'Models', '#/models', 'layers', r.page === 'models'), item('settings', 'Settings', '#/settings', 'gear', r.page === 'settings')],
  };
}
/** A badge's text (calendar 2.2): '' for none, the count up to 9, then '9+'. */
export function badgeText(n) {
  const v = Number(n) || 0;
  return v <= 0 ? '' : v > 9 ? '9+' : String(v);
}

/** What each fixed item is, for its tooltip. */
export const HINTS = {
  overview: 'The dashboard: memory, services and activity', chat: 'Talk to the agent', outputs: 'Everything the services made',
  memory: 'What the agent knows and has learned about you, and what waits for your review', models: 'The models on this machine', settings: "GAIFA's settings",
};
/** A service's state in words, for its tooltip ("Ready · Active"). */
export function stateWords(sv) {
  const st = sv?.manifest_errors?.length ? 'manifest error' : sv?.state || 'unknown';
  return `${st[0].toUpperCase()}${st.slice(1)} · ${BUCKETS[bucket(sv)].label}`;
}

/** Whether a service's item is the current page (the agent's Learning tab belongs to Learning). */
export function serviceOn(route, id) {
  return route?.page === 'service' && route.parts[1] === id && !(id === 'agent' && MEMORY_TABS.includes(route.parts[2]));
}

/** The Services page's list: a bucket ('all' or one) and words matched against name, id and description. */
export function filterServices(services, { filter = 'all', q = '' } = {}) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return (services || []).filter(sv => (filter === 'all' || bucket(sv) === filter)
    && words.every(w => `${sv.name} ${sv.id} ${sv.description || ''}`.toLowerCase().includes(w)));
}

/** A mod without a logo: its initials on a colour taken from its id (the same every time). */
export function monogram(id, name) {
  let h = 2166136261;
  for (const ch of String(id)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  const hue = (h >>> 0) % 360;
  const words = String(name || id).replace(/[^\p{L}\p{N}]+/gu, ' ').trim().split(' ').filter(Boolean);
  const text = (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2)).toUpperCase();
  return { text, bg: `hsl(${hue} 52% 40%)` };
}
