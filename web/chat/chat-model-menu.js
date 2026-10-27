// The model menu (plan llm-servers 5.1): server → model, from the agent's list (the relay's catalog, each model with
// its server, group, provider and health) and the hub's local engines (GET /api/llm/engines). Groups: This machine,
// Remote, Cloud; inside each, one header per server with its health, then its models with context, tools and vision.
// A search field filters by model, server or provider. Local models that aren't loaded are listed with Load: the
// engine starts if it's stopped, the model loads (make-room asked first), and the chat switches to it once the relay
// serves it. Cloud models carry their provider's badge. Each chat pane has its own menu; Settings → LLMs → Defaults
// uses the same one. Written by us (web/PATCHES.md); the pure parts are tested in utils/tests/web/chat-model-menu.test.mjs.

import { h, T, MONO, Popover, Badge, label11, inputSt, fmtTokens } from './chat-ui.js';
import { Control } from './chat-controls.js';   // a cycle on purpose: chat-controls re-exports ModelMenu; Control is used at render

const R = () => globalThis.React;
export const MENU_GROUPS = [
  { id: 'local', label: 'This machine' },
  { id: 'remote', label: 'Remote' },
  { id: 'cloud', label: 'Cloud' },
];
export const PROVIDER = { anthropic: 'Claude', openai: 'OpenAI', gemini: 'Gemini' };
const HEALTH = { healthy: 'green', degraded: 'accent', failed: 'red', stopped: 'dim', unknown: 'dim' };

/** A cloud model's provider badge text, else null. */
export const cloudBadge = m => (m.cloud ? PROVIDER[m.provider] || m.provider || 'cloud' : null);

/** "262K · tools · vision · thinks". */
export function modelFacts(m) {
  const x = m.meta || {};
  return [x.context_length ? fmtTokens(x.context_length) : '', x.tools ? 'tools' : '', x.vision ? 'vision' : '', x.reasoning ? 'thinks' : ''].filter(Boolean).join(' · ');
}

/** The engines' models a chat could load: not loaded, downloaded, and not already served by the relay. */
export function loadables(engines, served = []) {
  const have = new Set(served);
  return (engines || []).flatMap(e => (e.models || []).filter(m => !m.loaded && m.downloaded !== false && !have.has(m.relay_model || m.id))
    .map(m => ({ id: m.relay_model || m.id, name: m.name || m.id, group: 'local', server: e.name || e.id, health: e.running ? null : 'stopped',
      meta: { context_length: m.context || null }, size_gb: m.size_gb, load: { sid: e.id, id: m.id, engine: e.name || e.id, running: !!e.running } })))
    .concat((engines || []).filter(e => !e.running && !(e.models || []).length)      // a stopped engine lists nothing until it runs: offer Start
      .map(e => ({ id: 'start:' + e.id, name: `Start ${e.name || e.id} to list its models`, group: 'local', server: e.name || e.id, health: 'stopped', meta: {},
        start: { sid: e.id, engine: e.name || e.id } })));
}

const hit = (m, q) => [m.id, m.name, m.server, m.endpoint, PROVIDER[m.provider], m.load?.engine].some(s => s && String(s).toLowerCase().includes(q));

/** `[{id, label, servers: [{name, health, items}]}]` in MENU_GROUPS order, filtered by `query`, empty ones left out. */
export function menuGroups(models, engines, query = '') {
  const list = models?.models || [];
  const all = [...list.filter((m, i) => list.findIndex(x => x.id === m.id) === i), ...loadables(engines, list.map(m => m.id))];   // one row per id
  const q = query.trim().toLowerCase();
  const shown = q ? all.filter(m => hit(m, q)) : all;
  return MENU_GROUPS.map(g => {
    const servers = new Map();
    for (const m of shown.filter(x => (MENU_GROUPS.some(y => y.id === x.group) ? x.group : 'local') === g.id)) {
      const name = m.server || m.endpoint || (m.load ? m.load.engine : 'relay');
      if (!servers.has(name)) servers.set(name, { name, health: m.health || null, items: [] });
      servers.get(name).items.push(m);
    }
    return { ...g, servers: [...servers.values()] };
  }).filter(g => g.servers.length);
}

/** `/model <part>`: the models whose id holds it, as command rows (Enter sends, Tab completes). */
export function modelCompletions(draft, models) {
  const m = /^\/model (\S*)$/.exec(draft || '');
  if (!m) return [];
  const q = m[1].toLowerCase();
  const list = models?.models || [];
  return list.filter((x, i) => list.findIndex(y => y.id === x.id) === i && x.id.toLowerCase().includes(q) && x.id.toLowerCase() !== q)
    .sort((a, b) => Number(!a.id.toLowerCase().startsWith(q)) - Number(!b.id.toLowerCase().startsWith(q)))
    .slice(0, 8).map(x => ({ cmd: 'model ' + x.id, hint: [x.server, MENU_GROUPS.find(g => g.id === x.group)?.label, cloudBadge(x)].filter(Boolean).join(' · ') }));
}

const rowSt = on => ({ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '5px 8px', borderRadius: 6, cursor: 'pointer',
  font: 'inherit', color: T.tx, border: '1px solid ' + (on ? T.cy : 'transparent'), background: on ? T.tcy : 'transparent' });
const sleep = ms => new Promise(r => setTimeout(r, ms));

/** Start the engine if needed, load the model, wait until it's loaded. Throws the hub's error (needs_room among them). */
export async function loadModel(api, load, { makeRoom = false, onStep = () => {}, every = 2000, limit = 600 } = {}) {
  const find = async () => (await api.getLlmEngines()).find(e => e.id === load.sid);
  if (!load.running) {
    onStep(`Starting ${load.engine}…`);
    await api.startService(load.sid);
    for (let i = 0; !(await find())?.running; i++) { if (i * every > 90000) throw new Error(`${load.engine} didn’t start`); await sleep(every); }
  }
  onStep(`Loading ${load.id}…`);
  await api.loadLlm(load.sid, load.id, makeRoom);
  for (let i = 0; i * every < limit * 1000; i++) {
    const e = await find();
    const m = (e?.models || []).find(x => x.id === load.id);
    if (m?.loaded) return m.relay_model || m.id;
    if (e?.engine?.state === 'failed') throw new Error(e.engine.error || `${load.id} didn’t load`);
    await sleep(every);
  }
  throw new Error(`${load.id} is still loading; pick it once it’s ready`);
}

/** The menu. `api` (with getLlmEngines) adds the loadable models; `onModels` refreshes the list after a load;
 *  `none` adds a "none" row (Settings' fallback). */
export function ModelMenu({ models, value, onChange, api = null, onModels = null, toast = null, place = 'up-right', none = null, label: ctlLabel = 'Model' }) {
  const React = R(), [open, setOpen] = React.useState(false), [q, setQ] = React.useState('');
  const [engines, setEngines] = React.useState(null), [busy, setBusy] = React.useState(null), [room, setRoom] = React.useState(null);
  const canLoad = !!api?.getLlmEngines;
  React.useEffect(() => { if (open && canLoad) api.getLlmEngines().then(setEngines, () => setEngines([])); if (open) onModels?.(); }, [open]);
  const cur = value || models?.default || '';
  const groups = menuGroups(models, canLoad ? engines : null, q);
  const pick = id => { setOpen(false); setQ(''); if (id !== cur) onChange(id); };
  const load = async (m, makeRoom = false) => {
    setRoom(null); setBusy(`Loading ${m.id}…`); setOpen(false);
    try {
      const id = await loadModel(api, m.load, { makeRoom, onStep: setBusy });
      for (let i = 0; onModels && i < 15; i++) {          // the agent caches the relay's list for a few seconds
        const ms = await onModels();
        if (!ms || (ms.models || []).some(x => x.id === id)) break;
        await sleep(2000);
      }
      onChange(id); toast?.(`${id} is loaded: this chat uses it now`, 'success');
    } catch (e) {
      if (e?.code === 'needs_room') { setRoom({ m, plan: e.data?.plan || {} }); setOpen(true); }
      else toast?.(String(e?.detail || e?.message || e), 'error');
    } finally { setBusy(null); }
  };
  const start = async s => {
    setBusy(`Starting ${s.engine}…`);
    try {
      await api.startService(s.sid);
      for (let i = 0; i < 45; i++) {          // until it lists its catalog ('starting' answers none yet)
        const e = await api.getLlmEngines(); setEngines(e);
        const x = e.find(y => y.id === s.sid);
        if (x?.running && (x.models.length || x.state === 'ready')) break;
        await sleep(2000);
      }
    } catch (e) { toast?.(String(e?.detail || e?.message || e), 'error'); } finally { setBusy(null); }
  };
  const item = m => {
    if (m.start) return h('button', { key: m.id, type: 'button', onClick: () => start(m.start), disabled: !!busy, title: `Starts ${m.start.engine}; its models appear here`,
      style: { ...rowSt(false), color: T.mut, fontSize: 12 } }, busy || m.name);
    const badge = cloudBadge(m), facts = modelFacts(m);
    return h('button', { key: m.id + (m.load ? ':load' : ''), type: 'button', role: 'menuitemradio', 'aria-checked': m.id === cur ? 'true' : 'false',
      title: m.load ? `Load ${m.name} in ${m.load.engine}${m.load.running ? '' : ' (starts it)'}` : m.id,
      onClick: () => (m.load ? load(m) : pick(m.id)), disabled: !!busy, style: rowSt(m.id === cur) },
      h('span', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 } },
        h('span', { style: { fontSize: 12.5, fontWeight: 500, fontFamily: MONO, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
          m.id + (m.id === models?.default ? ' (default)' : '')),
        facts || m.size_gb ? h('span', { style: { fontSize: 11, color: T.mut } }, [facts, m.size_gb ? `${m.size_gb >= 10 ? Math.round(m.size_gb) : m.size_gb} GB` : ''].filter(Boolean).join(' · ')) : null),
      badge ? h(Badge, { tone: 'purple', title: `${badge}: a paid cloud model, for chats only` }, badge) : null,
      m.load ? h(Badge, { tone: 'cyan', title: 'Not loaded yet' }, 'Load') : null);
  };
  const unloads = (room?.plan?.unload || []).map(u => u.name || u.id).join(', ');
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'chat', label: busy || cur || none || 'No model', title: busy || 'Model: by server (this machine, remote, cloud)', ariaLabel: `${ctlLabel}: ${cur || 'none'}`, open,
      onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => { setOpen(false); setRoom(null); }, place, width: 340, label: ctlLabel, style: { gap: 2, padding: 6, maxHeight: '60vh', overflowY: 'auto' } },
      h('input', { value: q, onChange: e => setQ(e.target.value), placeholder: 'Search models and servers', 'aria-label': 'Search models', autoFocus: true,
        style: { ...inputSt, height: 28, width: '100%', marginBottom: 4 } }),
      room ? h('div', { role: 'alert', style: { display: 'flex', flexDirection: 'column', gap: 6, padding: 8, borderRadius: 7, background: T.tacc, fontSize: 12 } },
        `Not enough free memory for ${room.m.id}${unloads ? `: GAIFA can unload ${unloads}` : ''}.`,
        h('span', { style: { display: 'flex', gap: 6 } },
          h('button', { type: 'button', onClick: () => load(room.m, true), style: { ...rowSt(true), width: 'auto' } }, 'Unload & load'),
          h('button', { type: 'button', onClick: () => setRoom(null), style: { ...rowSt(false), width: 'auto' } }, 'Cancel'))) : null,
      none ? h('button', { type: 'button', role: 'menuitemradio', 'aria-checked': !value ? 'true' : 'false', onClick: () => pick(''), style: rowSt(!value) },
        h('span', { style: { fontSize: 12.5 } }, none)) : null,
      !groups.length ? h('span', { style: { fontSize: 12, color: T.mut, padding: 6 } }, q ? `No model matches “${q}”.` : 'No models from the relay yet.') : null,
      ...groups.map(g => h('div', { key: g.id, role: 'group', 'aria-label': g.label, style: { display: 'flex', flexDirection: 'column', gap: 1, marginTop: 4 } },
        h('span', { style: { ...label11, padding: '2px 6px' } }, g.label),
        ...g.servers.map(s => h('div', { key: s.name, style: { display: 'flex', flexDirection: 'column', gap: 1 } },
          h('span', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '3px 6px 1px', fontSize: 11.5, color: T.mut } }, s.name,
            s.health && s.health !== 'healthy' ? h(Badge, { tone: HEALTH[s.health] || 'dim' }, s.health) : null),
          ...s.items.map(item)))))));
}
