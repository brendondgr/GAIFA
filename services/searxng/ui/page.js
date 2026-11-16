// The SearXNG mod's tabs (plan 26.3): Engines (health, each engine on or off, its errors) and
// Search settings (safe search, language, timeouts, JSON, backups). Every change backs up settings.yml,
// restarts SearXNG and checks a search works, so it takes a few seconds. Only ctx is used.

const CELL = 'padding:6px 10px;border-bottom:1px solid var(--bd,#1D2430);text-align:left;font-size:12.5px;vertical-align:top';

function notRunning(el, ctx) {
  import('/mod-kit.js').then(k => k.requireRunning(el, ctx, 'SearXNG and its engines'));     // capability-enablement 3.3: the shared box
}

function when(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString() : '—';
}

async function change(ctx, method, path, json, done) {
  ctx.toast('Applying: backing up settings.yml and restarting SearXNG…', 'info');
  try {
    const r = await ctx.call(method, path, { json });
    if (r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` };
    ctx.toast(r.json.changed === false ? `Already set: ${r.json.label}` : `Done: ${r.json.label}. ${r.json.detail}`, 'success');
  } catch (e) {
    ctx.toast(e.detail || 'The change failed', 'error');
  }
  done();
}

function healthCard(ctx, h, found) {
  const { ui } = ctx;
  const up = h.health.up;
  const q = h.last_query || {};
  return ui.card(
    ui.row(ui.badge(up ? 'up' : 'down', up ? 'green' : 'red'), ui.text(found.url || 'no SearXNG found', { mono: true }),
      ui.text(h.health.detail || '', { muted: true })),
    ui.text(`Container: ${found.container ? `${found.container.name} (${found.container.runtime}, ${found.container.state})` : 'none found'}` +
      ` · settings: ${found.settings_file || '—'} · found by ${found.found_by || '—'}`, { muted: true }),
    found.settings_problem ? ui.text(found.settings_problem, { mono: true }) : null,
    ui.text(`Last test search: ${q.ok ? `${q.ms} ms, ${q.results ?? '?'} results` : (q.detail || 'not run yet')} at ${when(q.ts)}` +
      (q.unresponsive && q.unresponsive.length ? ` · failed: ${q.unresponsive.join(', ')}` : ''), { muted: true }),
    ui.row(ui.button('Test search now', async () => { await ctx.call('POST', '/v1/health/query'); ctx.refresh(); }, { small: true }),
      ui.button('Look again', async () => { await ctx.call('POST', '/v1/detect'); ctx.refresh(); }, { small: true, kind: 'ghost' })));
}

// capability-enablement 5.4: which SearXNG search uses (yours, or GAIFA's own on 5200), with what changes it
export function sourceWords(s) {
  if (!s) return { title: '', body: '' };
  if (s.using === 'managed') return { title: `Search uses GAIFA's own SearXNG at ${s.url}`, body: `A container (${s.runtime || 'podman'}) GAIFA started; ${s.up ? 'it answers' : 'it doesn\'t answer right now'}.` };
  if (s.using === 'yours') return { title: `Search uses your SearXNG at ${s.url}`, body: s.json ? (s.up ? 'It answers, with JSON results.' : 'It doesn\'t answer right now.') : 'It refuses JSON results, which search needs: turn the JSON format on under Search settings.' };
  return { title: 'No SearXNG answers: web search is off', body: 'Start GAIFA\'s own (a container on 127.0.0.1:5200), or point it at yours.' };
}

function sourceCard(ctx, s) {
  const { ui } = ctx;
  const w = sourceWords(s);
  const port = ui.input({ placeholder: '8080', style: 'width:90px' });
  const act = async (fn, ok) => { try { const r = await fn(); if (r && r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` }; if (ok) ctx.toast(ok, 'success'); } catch (e) { ctx.toast(e.detail || String(e), 'error'); } ctx.refresh(); };
  const buttons = [];
  if (s.actions.includes('start_managed')) buttons.push(ui.button("Start GAIFA's own", () => act(async () => {
    if (!(await ctx.confirm({ title: "Start GAIFA's own SearXNG?", body: 'A container from SearXNG\'s image (about 0.4 GB the first time), on 127.0.0.1:5200, settings in data/state/searxng/managed/. Search then uses it instead of yours.' }))) return null;
    await ctx.call('POST', '/v1/source', { json: { source: 'managed' } });
    return ctx.call('POST', '/v1/managed', { json: {} });
  }, "GAIFA's own SearXNG is running"), { small: true }));
  if (s.actions.includes('use_port')) buttons.push(ui.row(ui.text('Use mine on port', { muted: true }), port, ui.button('Use it', () => act(async () => {
    const p = parseInt(port.value, 10);
    if (!p) throw { detail: 'Give the port your SearXNG listens on' };
    const d = await ctx.call('POST', '/v1/detect', { json: { port: p } });
    if (d.json.answer === 'none' || !d.json.url) throw { detail: `No SearXNG answers on port ${p}` };
    return ctx.call('POST', '/v1/source', { json: { source: 'yours', url: d.json.url } });
  }, 'Search uses your SearXNG'), { small: true, kind: 'ghost' })));
  if (s.actions.includes('remove_managed')) buttons.push(ui.button("Remove GAIFA's SearXNG", () => act(async () => {
    if (!(await ctx.confirm({ title: "Remove GAIFA's own SearXNG?", body: 'Its container and its image go; its settings folder stays. Search uses yours if one answers, else it\'s off.', danger: true }))) return null;
    return ctx.call('DELETE', '/v1/managed', { query: { image: true } });
  }, "Removed GAIFA's SearXNG"), { small: true, kind: 'ghost' }));
  return ui.card(ui.row(ui.badge(s.using === 'none' ? 'off' : s.up ? 'up' : 'down', s.using === 'none' ? 'dim' : s.up ? 'green' : 'red'), ui.text(w.title)),
    ui.text(w.body, { muted: true }), ui.row(...buttons));
}

async function engines(el, ctx) {
  const { ui } = ctx;
  const state = await ctx.call('GET', '/v1/search-state').catch(() => null);
  if (state?.json) el.append(sourceCard(ctx, state.json));
  if (state?.json?.using === 'none') return;
  const [health, found, list] = await Promise.all([ctx.call('GET', '/v1/health'), ctx.call('GET', '/v1/found'), ctx.call('GET', '/v1/engines')]);
  const all = list.json.engines;
  let show = 'on';
  let needle = '';
  const body = ui.h('tbody');
  const draw = () => {
    const rows = all.filter(e => (show === 'all' || (show === 'on' ? e.enabled : e.errors.length)) && (!needle || e.name.includes(needle)));
    body.replaceChildren(...rows.map(e => ui.h('tr', null,
      ui.h('td', { style: CELL }, ui.text(e.name, { mono: true })),
      ui.h('td', { style: CELL }, ui.badge(e.enabled ? 'on' : 'off', e.enabled ? 'green' : 'dim')),
      ui.h('td', { style: CELL }, (e.categories || []).join(', ')),
      ui.h('td', { style: CELL }, e.timeout == null ? '' : `${e.timeout} s`),
      ui.h('td', { style: CELL }, e.errors.length ? e.errors.map(x => `${x.type}${x.message ? `: ${x.message}` : ''} (${x.percentage}%)`).join('; ') : ''),
      ui.h('td', { style: CELL }, ui.button(e.enabled ? 'Turn off' : 'Turn on', btn => {
        btn?.target && (btn.target.disabled = true);
        change(ctx, 'POST', `/v1/engines/${encodeURIComponent(e.name)}`, { enabled: !e.enabled }, () => ctx.refresh());
      }, { small: true, kind: e.enabled ? 'ghost' : 'secondary' })))));
  };
  const filter = ui.select([{ value: 'on', label: 'On' }, { value: 'failing', label: 'Failing' }, { value: 'all', label: 'All' }],
    { value: show, onchange: ev => { show = ev.target.value; draw(); } });
  const search = ui.input({ placeholder: 'Find an engine', oninput: ev => { needle = ev.target.value.trim().toLowerCase(); draw(); } });
  draw();
  el.append(healthCard(ctx, health.json, found.json), ui.card(
    ui.row(ui.field('Show', filter), ui.field('Name', search), ui.text(`${all.filter(e => e.enabled).length} on of ${all.length}`, { muted: true })),
    ui.h('div', { style: 'overflow:auto;max-width:100%' }, ui.h('table', { style: 'border-collapse:collapse;width:100%' },
      ui.h('thead', null, ui.h('tr', null, ['Engine', '', 'Categories', 'Timeout', 'Recent errors', ''].map(c =>
        ui.h('th', { style: CELL + ';color:var(--mut,#8A94A6);font-weight:500' }, c)))), body))));
}

async function settingsTab(el, ctx) {
  const { ui } = ctx;
  const r = await ctx.call('GET', '/v1/settings');
  if (r.status >= 400) {
    const bad = r.json.code === 'settings_invalid';
    el.append(ui.empty(bad ? 'settings.yml needs a fix' : 'No settings file', bad ? `${r.json.detail}. ${r.json.fix}.` : r.json.detail, null));
    return;
  }
  const s = r.json.settings;
  const safe = ui.select([{ value: '', label: 'SearXNG default' }, { value: '0', label: 'Off' }, { value: '1', label: 'Moderate' }, { value: '2', label: 'Strict' }],
    { value: s.safe_search == null ? '' : String(s.safe_search) });
  const lang = ui.input({ value: s.default_lang || '', placeholder: 'auto' });
  const timeout = ui.input({ value: s.request_timeout ?? '', placeholder: '3.0', type: 'number' });
  const apply = () => {
    const json = {};
    if (safe.value !== '' && Number(safe.value) !== s.safe_search) json.safe_search = Number(safe.value);
    if (lang.value.trim() && lang.value.trim() !== s.default_lang) json.default_lang = lang.value.trim();
    if (timeout.value !== '' && Number(timeout.value) !== s.request_timeout) json.request_timeout = Number(timeout.value);
    if (!Object.keys(json).length) { ctx.toast('Nothing changed', 'info'); return; }
    change(ctx, 'POST', '/v1/settings', json, () => ctx.refresh());
  };
  el.append(
    ui.card(ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Search'),
      ui.text(`File: ${r.json.file}`, { muted: true, mono: true }),
      ui.row(ui.field('Safe search', safe), ui.field('Default language', lang, 'auto, all, en, de-DE…'), ui.field('Engine timeout (s)', timeout, 'outgoing.request_timeout')),
      ui.row(ui.button('Apply', apply, { kind: 'primary' }),
        s.json ? ui.badge('JSON format on', 'green')
          : ui.button('Turn on the JSON format', () => change(ctx, 'POST', '/v1/settings', { json_format: true }, () => ctx.refresh()), { kind: 'secondary' })),
      ui.text('Each change backs up settings.yml, restarts SearXNG and checks a search works; if it doesn’t, the backup goes back.', { muted: true })),
    ui.card(ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Recent changes'),
      r.json.changes.length ? ui.table(r.json.changes.map(c => ({ when: when(c.ts), change: c.label, result: c.rolled_back ? 'rolled back' : (c.changed ? 'done' : 'no change'), detail: c.detail, backup: c.backup || '' })))
        : ui.text('None since the mod started.', { muted: true })),
    ui.card(ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Backups'),
      r.json.backups.length ? ui.table(r.json.backups.slice(0, 20).map(b => ({ file: b }))) : ui.text('None yet.', { muted: true })));
}

export default {
  tabs: [{ id: 'engines', label: 'Engines', icon: 'search' }, { id: 'config', label: 'Search settings', icon: 'gear' }],

  mount(el, ctx) {
    if (ctx.service.state !== 'ready' && ctx.service.state !== 'degraded') { notRunning(el, ctx); return; }
    const run = ctx.tab === 'config' ? settingsTab : engines;
    let alive = true;
    const view = { ...ctx, refresh: () => { if (alive) { el.replaceChildren(); load(); } } };
    const load = () => run(el, view).catch(e => el.append(ctx.ui.empty('Couldn’t load', e.detail || String(e), null)));
    load();
    return () => { alive = false; };
  },
};
