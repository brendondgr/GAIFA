// vLLM page inside GAIFA (plan 18.6): Profiles (one card per model setup: load, download, edit) and
// Engine (the running command, its log, throughput charts). Calls the vllm adapter through ctx.call;
// a load asks GAIFA for memory, so "Make room" comes up when it's needed.
import { chartCard, charts, rh } from '/mod-charts.js';
import { schemaForm } from '/mod-form.js';
import { requireRunning, callRoom, header, panel, columns, stat, fmtBytes, fmtSecs, MONO } from '/mod-kit.js';

const TONE = { ready: 'green', starting: 'accent', stopping: 'dim', failed: 'red', unloaded: 'dim',
  registered: 'green', pending: 'accent', off: 'dim', error: 'red' };
const ORDER = ['name', 'model', 'revision', 'memory_gb', 'max_model_len', 'max_num_seqs', 'served_name', 'alias',
  'tool_parser', 'reasoning_parser'];
const ADVANCED = ['attention_backend', 'enforce_eager', 'trust_remote_code', 'env', 'extra_args', 'notes'];
const errText = e => e.data?.body?.detail || e.detail || e.message || 'Request failed';
const enc = encodeURIComponent;
const every = (fn, ms, cleanups) => { const t = setInterval(() => { if (!document.hidden) fn(); }, ms); cleanups.push(() => clearInterval(t)); };
const mono = (h, text, muted) => h('span', { style: `font-family:${MONO};font-size:11.5px;${muted ? 'color:var(--mut,#8A94A6);' : ''}overflow-wrap:anywhere` }, text);
const card = (h, ...kids) => h('div', { style: 'border:1px solid var(--bd,#1D2430);border-radius:8px;padding:10px;background:var(--inset,#131926);display:flex;flex-direction:column;gap:6px;min-width:0' }, ...kids);
const bar = (h, p) => h('div', { style: 'height:4px;border-radius:2px;background:var(--bd,#1D2430);overflow:hidden' },
  h('div', { style: `height:100%;width:${Math.round(100 * (p || 0))}%;background:var(--accent,#7C9CFF);transition:width .4s` }));

export default {
  tabs: [{ id: 'profiles', label: 'Profiles', icon: 'layers' }, { id: 'engine', label: 'Engine', icon: 'cpu' }],
  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'vLLM')) return;
    const cleanups = [];
    (ctx.tab === 'engine' ? engineTab : profilesTab)(el, ctx, cleanups);
    return () => cleanups.forEach(f => { try { f(); } catch { /* gone */ } });
  },
};

// ------------------------------------------------------------------ Profiles
function profilesTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const list = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
  const enginePanel = h('div');
  const editor = h('div');
  let data = { profiles: [], problems: {} }, eng = {}, schema = null, editing = null;

  const act = (label, fn, kind) => ui.button(label, async e => {
    const b = e.currentTarget; b.disabled = true;
    try { await fn(); } catch (err) { if (!err.cancelled) ctx.toast(errText(err), 'error'); } finally { b.disabled = false; load(); }
  }, { small: true, kind });

  async function load() {
    try {
      [data, eng] = await Promise.all([ctx.call('GET', '/v1/profiles').then(r => r.json), ctx.call('GET', '/v1/engine').then(r => r.json)]);
      draw();
    } catch (e) { list.replaceChildren(ui.badge(errText(e), 'red')); }
  }

  function draw() {
    const probs = Object.entries(data.problems || {}).map(([f, why]) => ui.badge(`${f}: ${why}`, 'red'));
    list.replaceChildren(...probs, ...(data.profiles.length ? data.profiles.map(profileCard)
      : [ui.empty('No profiles', 'Add one with New profile, or put a TOML file in services/vllm/profiles/.')]));
    enginePanel.replaceChildren(engineSummary());
  }

  function engineSummary() {
    const st = eng.state || 'unloaded', rel = eng.relay;
    const up = eng.started_at && st !== 'unloaded' ? fmtSecs((eng.ready_at || Date.now() / 1000) - eng.started_at) : null;
    return panel(header('Engine', ui.badge(st === 'starting' ? `starting: ${eng.stage || ''}` : st, TONE[st])),
      h('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' },
        stat('Profile', eng.name || '—'), stat(st === 'ready' ? 'Started in' : 'Starting for', up || '—'),
        stat('Endpoint', eng.endpoint || '—'), stat('Relay', rel ? `${rel.alias || rel.key} · ${rel.state}` : 'off')),
      rel?.error ? ui.badge(`relay: ${rel.error}`, 'red') : null,
      st === 'failed' && eng.last_error ? h('pre', { style: `margin:0;max-height:160px;overflow:auto;font-family:${MONO};font-size:11px;white-space:pre-wrap;color:var(--rd,#F85149)` }, eng.last_error) : null,
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
        st === 'ready' || st === 'starting' ? act('Unload', async () => {
          if (await ctx.confirm({ title: `Unload ${eng.name}?`, body: 'vLLM stops and its memory is freed. Clients using it through the relay get errors until it is loaded again.', danger: true }))
            await ctx.call('POST', '/v1/unload');
        }, 'danger') : null,
        st === 'failed' ? act('Dismiss', () => ctx.call('POST', '/v1/unload')) : null,
        act('Engine log', async () => ctx.navigate('#/s/vllm/engine'), 'ghost')));
  }

  function profileCard(p) {
    const loaded = eng.profile === p.id && eng.state !== 'unloaded';
    const dl = p.download && p.download.state === 'running' ? p.download : null;
    const tags = [`${p.memory_gb} GB`, `ctx ${p.max_model_len.toLocaleString()}`, `${p.max_num_seqs} at once`,
      p.tool_parser && `tools: ${p.tool_parser}`, p.reasoning_parser && `thinking: ${p.reasoning_parser}`,
      p.enforce_eager && 'eager', p.attention_backend].filter(Boolean);
    return card(h,
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('strong', { style: 'font-size:13.5px' }, p.name),
        loaded ? ui.badge(eng.state === 'starting' ? `starting: ${eng.stage || ''}` : eng.state, TONE[eng.state]) : null,
        p.downloaded ? ui.badge(`downloaded · ${fmtBytes(p.local_bytes)}`, 'green') : dl ? null : ui.badge('not downloaded', 'dim'),
        h('span', { style: 'flex:1' }), mono(h, p.id, true)),
      mono(h, `${p.model}${p.revision !== 'main' ? `@${p.revision}` : ''} → ${p.served_name || p.model}${p.alias ? ` (relay: ${p.alias})` : ''}`),
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, ...tags.map(t => ui.badge(t))),
      dl ? h('div', { style: 'display:flex;flex-direction:column;gap:4px' }, bar(h, dl.progress),
        mono(h, `downloading ${fmtBytes(dl.bytes)}${dl.total ? ` of ${fmtBytes(dl.total)}` : ''}`, true)) : null,
      p.download?.state === 'failed' ? ui.badge(`download failed: ${p.download.error}`, 'red') : null,
      p.notes ? ui.text(p.notes, { small: true, muted: true }) : null,
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
        loaded ? null : act('Load', async () => {
          await callRoom(ctx, 'POST', '/v1/load', { query: { wait: false }, json: { profile: p.id } });
          ctx.toast(`Starting ${p.name}${p.downloaded ? '' : ' (downloading first)'}`, 'success');
        }, 'primary'),
        p.downloaded || dl ? null : act('Download', () => ctx.call('POST', '/v1/downloads', { json: { profile: p.id } }), 'ghost'),
        act('Edit', async () => openEditor(p), 'ghost'),
        act('Duplicate', async () => openEditor({ ...p, id: `${p.id}-copy`, name: `${p.name} (copy)` }, true), 'ghost'),
        loaded ? null : act('Delete', async () => {
          if (await ctx.confirm({ title: `Delete the profile ${p.name}?`, body: `Removes profiles/${p.id}.toml. The downloaded model stays (it's on the Models page).`, danger: true }))
            await ctx.call('DELETE', `/v1/profiles/${enc(p.id)}`);
        }, 'danger')));
  }

  async function openEditor(p, isNew = !p) {
    schema = schema || (await ctx.call('GET', '/v1/profiles/schema')).json;
    editing = { id: p?.id || '', isNew };
    const values = p ? { ...p, env: Object.entries(p.env || {}).map(([k, v]) => `${k}=${v}`).join('\n'), extra_args: (p.extra_args || []).join(' ') } : { revision: 'main', max_num_seqs: 4, memory_gb: 16, max_model_len: 32768 };
    const form = schemaForm(ctx, schema, { values, order: ORDER, advanced: ADVANCED });
    const id = ui.input({ value: editing.id, placeholder: 'e.g. gemma-4-26b', disabled: !isNew });
    id.style.fontFamily = MONO;
    const save = ui.button('Save', async () => {
      const v = form.values();
      const body = { ...v, env: Object.fromEntries((v.env || '').split('\n').map(l => l.trim()).filter(Boolean).map(l => [l.split('=')[0], l.slice(l.indexOf('=') + 1)])),
        extra_args: (v.extra_args || '').trim() ? v.extra_args.trim().split(/\s+/) : [] };
      try {
        const r = (await ctx.call('PUT', `/v1/profiles/${enc(id.value.trim())}`, { json: body })).json;
        ctx.toast(r.note ? `Saved; ${r.note}` : 'Saved', 'success');
        editor.replaceChildren(); load();
      } catch (e) { ctx.toast(errText(e), 'error'); }
    }, { kind: 'primary' });
    editor.replaceChildren(panel(header(isNew ? 'New profile' : `Edit ${p.name}`, ui.button('Cancel', () => editor.replaceChildren(), { small: true, kind: 'ghost' })),
      ui.field('Profile id (the file name)', id), form,
      ui.text('memory_gb is everything vLLM may use: weights, KV cache and graphs. The page asks GAIFA for that plus the processes\' overhead.', { small: true, muted: true }),
      h('div', {}, save)));
    editor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  const grid = columns(panel(header('Profiles', ui.button('New profile', () => openEditor(null, true), { small: true }),
    ui.button('Refresh', load, { small: true, kind: 'ghost' })), list),
  h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, enginePanel, editor), 400);
  cleanups.push(grid.cleanup);
  el.append(grid);
  load();
  every(load, 2000, cleanups);
  ctx.on('service', load);
}

// ------------------------------------------------------------------ Engine
function engineTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const info = h('div');
  const box = h('pre', { style: `margin:0;height:420px;overflow:auto;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);border-radius:8px;padding:8px 10px;font-family:${MONO};font-size:11.5px;line-height:1.5;white-space:pre-wrap` });
  let follow = true;
  box.addEventListener('scroll', () => { follow = box.scrollTop + box.clientHeight >= box.scrollHeight - 20; });

  async function load() {
    try {
      const [eng, logs] = await Promise.all([ctx.call('GET', '/v1/engine').then(r => r.json), ctx.call('GET', '/v1/engine/logs', { query: { tail: 400 } }).then(r => r.json)]);
      const st = eng.state;
      info.replaceChildren(panel(header(eng.name || 'No engine', ui.badge(st === 'starting' ? `starting: ${eng.stage || ''}` : st, TONE[st])),
        eng.command?.length ? mono(h, eng.command.slice(eng.command.indexOf('vllm')).join(' ')) : ui.text('Load a profile on the Profiles tab.', { small: true, muted: true }),
        eng.memory_gb ? ui.text(`Asks GAIFA for ${eng.memory_gb} GB · served on ${eng.endpoint || '127.0.0.1 (not ready)'}`, { small: true, muted: true }) : null));
      box.textContent = logs.lines.length ? logs.lines.join('\n') : 'No engine log yet.';
      if (follow) box.scrollTop = box.scrollHeight;
    } catch (e) { info.replaceChildren(ui.badge(errText(e), 'red')); }
  }

  const series = (names, range) => ctx.api.getMetrics({ series: names, range });
  const tps = chartCard({
    title: 'Tokens per second', ranges: ['1h', '6h', '24h'], height: 130, every: 15000,
    load: r => series(['svc.vllm.stat.tokens_s'], r),
    draw: (d, o) => rh(charts.AreaChart, { t: d.t, series: [{ label: 'Generated', values: d.series['svc.vllm.stat.tokens_s'] || [] }], unit: 'tok/s', ...o }),
  });
  const kv = chartCard({
    title: 'KV cache', ranges: ['1h', '6h', '24h'], height: 130, every: 15000,
    load: r => series(['svc.vllm.stat.kv_cache'], r),
    draw: (d, o) => rh(charts.LineChart, { t: d.t, series: [{ label: 'KV cache %', values: d.series['svc.vllm.stat.kv_cache'] || [] }], unit: '%', ...o }),
  });
  const mem = chartCard({
    title: 'vLLM memory', ranges: ['1h', '6h', '24h'], height: 130, every: 15000,
    load: r => series(['mem.svc.vllm'], r),
    draw: (d, o) => rh(charts.AreaChart, { t: d.t, series: [{ label: 'vLLM', values: d.series['mem.svc.vllm'] || [] }], unit: 'bytes', ...o }),
  });
  cleanups.push(tps.unmount, kv.unmount, mem.unmount);
  const grid = columns(h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, info, panel(header('Engine log'), box)),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, tps, kv, mem), 380);
  cleanups.push(grid.cleanup);
  el.append(grid);
  load();
  every(load, 2000, cleanups);
}
