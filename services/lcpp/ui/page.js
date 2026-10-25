// LLM Launcher (lcpp) page inside GAIFA: Instances, Catalog, Playground, Relay publishing and
// Launcher settings (design brief Part B1, a port of lcpp's own UI). Calls lcppd's API through
// ctx.call; a launch asks GAIFA for memory, so "Make room" comes up when it's needed.
import { chartCard, chart, charts, rh } from '/mod-charts.js';
import { requireRunning, callRoom, segmented, header, panel, columns, stat, store, fmtBytes, fmtSecs, fmtAgo, MONO } from '/mod-kit.js';

const TONE = { ready: 'green', starting: 'accent', stopping: 'dim', failed: 'red', registered: 'green', pending: 'accent', off: 'dim', error: 'red' };
const CTX = [4096, 8192, 16384, 32768, 65536, 131072, 262144];
const errText = e => e.data?.body?.detail || e.detail || e.message || 'Request failed';
const enc = encodeURIComponent;

export default {
  tabs: [
    { id: 'instances', label: 'Instances', icon: 'cpu' }, { id: 'catalog', label: 'Catalog', icon: 'layers' },
    { id: 'playground', label: 'Playground', icon: 'chat' }, { id: 'publishing', label: 'Relay publishing', icon: 'relay' },
    { id: 'launcher', label: 'Launcher settings', icon: 'gear' },
  ],
  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the Launcher')) return;
    const cleanups = [];
    ({ catalog: catalogTab, playground: playgroundTab, publishing: publishingTab, launcher: settingsTab }[ctx.tab] || instancesTab)(el, ctx, cleanups);
    return () => cleanups.forEach(f => { try { f(); } catch { /* gone */ } });
  },
};

const every = (fn, ms, cleanups) => { const t = setInterval(() => { if (!document.hidden) fn(); }, ms); cleanups.push(() => clearInterval(t)); };
const card = (h, ...kids) => h('div', { style: 'border:1px solid var(--bd,#1D2430);border-radius:8px;padding:10px;background:var(--inset,#131926);display:flex;flex-direction:column;gap:6px;min-width:0' }, ...kids);
const colField = ui => (...a) => { const f = ui.field(...a); f.style.flex = '1 1 160px'; return f; };

// ------------------------------------------------------------------ Instances
function instancesTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h, field = colField(ui);
  const list = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
  const logs = h('div');
  let models = [], logCtl = null;
  cleanups.push(() => logCtl?.abort());
  const act = (label, fn, kind) => ui.button(label, async e => { const b = e.currentTarget; b.disabled = true; try { await fn(); } catch (err) { if (!err.cancelled) ctx.toast(errText(err), 'error'); } finally { b.disabled = false; load(); } }, { small: true, kind });

  async function load() {
    try {
      const ov = (await ctx.call('GET', '/api/overview')).json;
      list.replaceChildren(...(ov.instances.length ? ov.instances.map(instCard) : [ui.empty('Nothing running', 'Launch a model from the catalog on the right.')]));
    } catch (e) { list.replaceChildren(ui.badge(errText(e), 'red')); }
  }
  function instCard(i) {
    const p = i.params || {};
    return card(h,
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('strong', { style: 'font-size:13.5px' }, i.name), ui.badge(i.state, TONE[i.state]),
        i.kind === 'router' ? ui.badge('router', 'accent') : null, i.relay?.enabled !== false && i.relay?.state && i.relay.state !== 'off' ? ui.badge(`relay: ${i.relay.alias || ''} ${i.relay.state}`, TONE[i.relay.state] || 'dim') : null,
        h('span', { style: 'flex:1' }), h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` }, `${i.url} · ${fmtBytes(i.rss_bytes)} · up ${fmtSecs(Date.now() / 1000 - i.started_ts)}`)),
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, [i.model_id || `${(i.models || []).length} models`, p['ctx-size'] && `ctx ${p['ctx-size']}`, (p['cache-type-k'] || p['cache-type-v']) && `kv ${p['cache-type-k'] || 'f16'}/${p['cache-type-v'] || 'f16'}`,
        i.capabilities?.vision && 'vision', i.capabilities?.speculative && 'spec-decode'].filter(Boolean).map(t => ui.badge(t))),
      i.last_error ? ui.badge(i.last_error, 'red') : null,
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
        ['ready', 'starting'].includes(i.state) ? act('Stop', async () => { if (await ctx.confirm({ title: `Stop ${i.name}?`, body: 'Its llama-server exits and the memory is freed. Clients using it through the relay get errors until another instance serves the model.', danger: true })) await ctx.call('DELETE', `/api/instances/${enc(i.name)}`); }, 'danger') : null,
        i.state === 'failed' ? act('Dismiss', () => ctx.call('DELETE', `/api/instances/${enc(i.name)}`, { query: { dismiss: 1 } })) : null,
        act('Restart', () => ctx.call('POST', `/api/instances/${enc(i.name)}/restart`)),
        i.relay?.state === 'registered' || i.relay?.state === 'pending' ? act('Unpublish', () => ctx.call('DELETE', `/api/instances/${enc(i.name)}/relay`), 'ghost') : act('Publish to relay', () => ctx.call('POST', `/api/instances/${enc(i.name)}/relay`, { json: { alias: i.relay?.alias || null } }), 'ghost'),
        act('Logs', async () => showLogs(i.name), 'ghost'),
        i.state === 'ready' ? act('Chat', async () => { store.set('lcpp.chatTarget', i.name); ctx.navigate('#/s/lcpp/playground'); }, 'ghost') : null));
  }
  function showLogs(name) {
    logCtl?.abort();
    logCtl = new AbortController();
    const box = h('pre', { style: `margin:0;height:260px;overflow:auto;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);border-radius:8px;padding:8px 10px;font-family:${MONO};font-size:11.5px;line-height:1.5;white-space:pre-wrap` });
    logs.replaceChildren(panel(header(`Logs · ${name}`, ui.button('Close', () => { logCtl.abort(); logs.replaceChildren(); }, { small: true, kind: 'ghost' })), box));
    const add = t => { box.append(t + '\n'); while (box.childNodes.length > 1500) box.firstChild.remove(); box.scrollTop = box.scrollHeight; };
    ctx.call('GET', `/api/instances/${enc(name)}/logs`, { query: { lines: 200 } }).then(r => (r.json?.lines || r.json || []).forEach(l => add(l.text ?? l))).catch(() => {});
    ctx.call('GET', `/api/instances/${enc(name)}/logs/stream`, { stream: true, signal: logCtl.signal, onEvent: d => { try { add(JSON.parse(d).text); } catch { add(d); } } }).catch(() => {});
  }

  // Launch form
  const model = ui.select([]), name = ui.input({ placeholder: 'auto' }), port = ui.input({ type: 'number', placeholder: 'auto' }), alias = ui.input({ placeholder: 'model nickname' });
  const ctxSel = ui.select([{ value: '', label: 'model default' }, ...CTX.map(v => ({ value: String(v), label: `${v >= 1024 ? v / 1024 + 'k' : v}` }))]);
  const publish = h('input', { type: 'checkbox', checked: true });
  const pre = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });
  const go = ui.button('Launch', () => launch(), { kind: 'primary' });
  const spec = () => {
    const s = { kind: 'single', model_id: model.value, params: {}, relay: { enabled: publish.checked, alias: alias.value.trim() || undefined } };
    if (ctxSel.value) s.params['ctx-size'] = Number(ctxSel.value);
    if (name.value.trim()) s.name = name.value.trim();
    if (port.value) s.port = Number(port.value);
    return s;
  };
  let pfTimer = 0;
  async function preflight() {
    if (!model.value) return;
    try {
      const p = (await ctx.call('POST', '/api/instances/preflight', { json: spec() })).json;
      pre.replaceChildren(h('div', { style: 'display:flex;gap:16px;flex-wrap:wrap' }, stat('Name', p.name), stat('Port', String(p.port)), stat('Needs', fmtBytes(p.estimated_bytes)), stat('Available', fmtBytes(p.available_bytes))),
        ...p.errors.map(e => ui.badge(e.detail, 'red')), ...p.warnings.map(w => ui.badge(w, 'accent')));
      go.disabled = p.errors.length > 0;
    } catch (e) { pre.replaceChildren(ui.badge(errText(e), 'red')); }
  }
  const changed = () => { clearTimeout(pfTimer); pfTimer = setTimeout(preflight, 300); };
  [model, ctxSel, publish].forEach(x => x.addEventListener('change', changed));
  [name, port, alias].forEach(x => x.addEventListener('input', changed));
  cleanups.push(() => clearTimeout(pfTimer));
  async function launch() {
    go.disabled = true; go.textContent = 'Launching…';
    try {
      const r = (await callRoom(ctx, 'POST', '/api/instances', { json: spec() })).json;
      ctx.toast(`Starting ${r.instance.name}`, 'success'); (r.warnings || []).forEach(w => ctx.toast(w, 'info'));
      name.value = port.value = ''; load(); preflight();
    } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } finally { go.disabled = false; go.textContent = 'Launch'; }
  }
  const memChart = chartCard({
    title: 'Launcher memory · 1 h', height: 130, every: 15000,
    load: () => ctx.api.getMetrics({ series: ['mem.svc.lcpp'], range: '1h' }),
    draw: (d, o) => rh(charts.AreaChart, { t: d.t, series: [{ label: 'LLM instances', values: d.series['mem.svc.lcpp'] || [] }], unit: 'bytes', ...o }),
  });
  cleanups.push(memChart.unmount);
  const launchPanel = panel(header('Launch a model'), ui.field('Model', model), h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, field('Context', ctxSel), field('Port', port), field('Name', name)),
    h('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12.5px' }, publish, 'Publish to the relay as'), alias, pre, h('div', {}, go));
  const grid = columns(h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, panel(header('Instances', ui.button('Refresh', load, { small: true, kind: 'ghost' })), list), logs),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, launchPanel, memChart), 380);
  cleanups.push(grid.cleanup);
  el.append(grid);
  ctx.call('GET', '/api/models').then(r => {
    models = r.json.models.filter(m => m.ok);
    model.replaceChildren(...models.map(m => h('option', { value: m.id }, `${m.id} · ${fmtBytes(m.size_bytes)}${m.running.length ? ' · running' : ''}`)));
    preflight();
  }).catch(e => ctx.toast(errText(e), 'error'));
  load();
  every(load, 4000, cleanups);
}

// ------------------------------------------------------------------ Catalog
function catalogTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h, field = colField(ui);
  const list = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
  const disc = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });
  const dls = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });
  const tree = h('div');
  let treeEl = null;
  cleanups.push(() => treeEl?.unmount());
  async function load() {
    try {
      const [m, d] = await Promise.all([ctx.call('GET', '/api/models'), ctx.call('GET', '/api/models/discovered')]);
      const ms = m.json.models;
      list.replaceChildren(...(ms.length ? ms.map(modelCard) : [ui.empty('The catalog is empty', 'Add a discovered GGUF, or download one from Hugging Face.')]));
      disc.replaceChildren(...(d.json.length ? d.json.map(discRow) : [ui.text('No unlisted GGUFs in the scan folders.', { muted: true, small: true })]));
      const items = ms.map(x => ({ key: x.id, label: x.id, value: x.size_bytes }));
      if (treeEl) treeEl.update({ items, unit: 'bytes', height: 140, label: 'Catalog size' }); else { treeEl = chart(charts.Treemap, { items, unit: 'bytes', height: 140, label: 'Catalog size' }); tree.append(treeEl); }
    } catch (e) { list.replaceChildren(ui.badge(errText(e), 'red')); }
  }
  function modelCard(m) {
    return card(h,
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('strong', {}, m.id), ...m.nicknames.map(n => ui.badge(n)), m.ok ? null : ui.badge('files missing', 'red'),
        m.running.length ? ui.badge(`running: ${m.running.join(', ')}`, 'green') : null, h('span', { style: 'flex:1' }),
        h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` }, `${fmtBytes(m.size_bytes)} · ctx ${m.effective['ctx-size'] ?? '—'}`)),
      h('span', { style: `font-family:${MONO};font-size:11.5px;word-break:break-all` }, m.path),
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, [m.capabilities.vision && 'vision', m.capabilities.speculative && 'speculative', m.capabilities.split && 'split', m.location === 'external' && 'outside the models folder'].filter(Boolean).map(t => ui.badge(t, 'accent'))),
      ...m.problems.map(p => ui.badge(p, 'red')),
      h('div', { style: 'display:flex;gap:6px' }, ui.button('Delete from catalog', async () => {
        if (!await ctx.confirm({ title: `Delete ${m.id} from the catalog?`, body: 'The entry is removed from lcpp; the files stay on disk (and on GAIFA\'s Models page).', danger: true })) return;
        try { await ctx.call('DELETE', `/api/models/${enc(m.id)}`); ctx.toast(`Removed ${m.id}`, 'success'); load(); } catch (e) { ctx.toast(errText(e), 'error'); }
      }, { small: true, kind: 'ghost' })));
  }
  function discRow(d) {
    const id = ui.input({ value: d.suggested_id });
    return card(h, h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('span', { style: `font-family:${MONO};font-size:12px;flex:1;word-break:break-all` }, d.path), h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, fmtBytes(d.size_bytes))),
      h('div', { style: 'display:flex;gap:6px;align-items:center' }, id, ui.button('Add', async () => {
        try { await ctx.call('PUT', `/api/models/${enc(id.value.trim())}`, { json: { id: id.value.trim(), path: d.path, nicknames: [] } }); ctx.toast('Added to the catalog', 'success'); load(); } catch (e) { ctx.toast(errText(e), 'error'); }
      }, { small: true, kind: 'primary' })));
  }

  // Hugging Face downloads
  const hfIn = ui.input({ placeholder: 'owner/repo, or a huggingface.co link to a .gguf' });
  const pick = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
  async function resolve() {
    pick.replaceChildren(ui.text('Looking up the repo…', { muted: true, small: true }));
    try {
      const r = (await ctx.call('POST', '/api/downloads/resolve', { json: { input: hfIn.value.trim() } })).json;
      if (!r.choices?.length) { pick.replaceChildren(ui.badge(r.message || 'No GGUF files in that repo', 'accent')); return; }
      const choice = ui.select(r.choices.map(c => ({ value: c.id, label: `${c.label} · ${c.quant || ''} · ${fmtBytes(c.size_bytes)}${c.complete ? '' : ' (incomplete split)'}` })), { value: r.selected || r.choices[0].id });
      const mm = ui.select([{ value: '', label: 'none' }, ...(r.mmproj || []).map(f => ({ value: f.path, label: `${f.path} · ${fmtBytes(f.size_bytes)}` }))]);
      const dr = ui.select([{ value: '', label: 'none' }, ...(r.drafts || []).map(f => ({ value: f.path, label: `${f.path} · ${fmtBytes(f.size_bytes)}` }))]);
      const dir = ui.input({ value: r.suggested_dir }), mid = ui.input({ value: r.choices.find(c => c.id === (r.selected || r.choices[0].id))?.suggested_id || '' });
      choice.addEventListener('change', () => { mid.value = r.choices.find(c => c.id === choice.value)?.suggested_id || mid.value; });
      pick.replaceChildren(ui.text(`${r.repo} @ ${r.revision}${r.gated ? ' (gated: needs a token)' : ''} · ${fmtBytes(r.free_bytes)} free`, { small: true }),
        ui.field('File', choice), h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, field('Vision projector', mm), field('Draft (speculative)', dr)),
        h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, field('Folder', dir), field('Catalog id', mid)),
        h('div', {}, ui.button('Download', async () => {
          try {
            await ctx.call('POST', '/api/downloads', { json: { repo: r.repo, revision: r.revision, choice: choice.value, dir: dir.value.trim(), mmproj: mm.value || null, draft: dr.value || null, model_id: mid.value.trim() || null, add_to_catalog: true } });
            ctx.toast('Download started; it lands in data/models/llm and on the Models page', 'success'); pick.replaceChildren(); hfIn.value = ''; loadDls();
          } catch (e) { ctx.toast(errText(e), 'error'); }
        }, { kind: 'primary', small: true })));
    } catch (e) { pick.replaceChildren(ui.badge(errText(e), 'red')); }
  }
  async function loadDls() {
    try {
      const d = (await ctx.call('GET', '/api/downloads')).json;
      dls.replaceChildren(...d.map(j => card(h,
        h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('strong', { style: 'font-size:12.5px' }, j.model_id || j.label), ui.badge(j.state, j.state === 'done' ? 'green' : j.state === 'failed' ? 'red' : 'accent'),
          h('span', { style: 'flex:1' }), h('span', { style: `font-family:${MONO};font-size:11.5px` }, `${fmtBytes(j.bytes_done)} / ${fmtBytes(j.bytes_total)}${j.speed_bps ? ` · ${fmtBytes(j.speed_bps)}/s` : ''}${j.eta_s ? ` · ${fmtSecs(j.eta_s)} left` : ''}`)),
        ['queued', 'downloading'].includes(j.state) ? h('div', { style: 'height:4px;border-radius:2px;background:var(--bds,#2A3547);overflow:hidden' }, h('div', { style: `height:100%;width:${j.bytes_total ? Math.round(100 * j.bytes_done / j.bytes_total) : 0}%;background:var(--acc,#FFB224)` })) : null,
        j.error ? ui.badge(j.error, 'red') : null, j.warning ? ui.badge(j.warning, 'accent') : null,
        h('div', { style: 'display:flex;gap:6px' }, ['queued', 'downloading'].includes(j.state) ? ui.button('Cancel', () => ctx.call('POST', `/api/downloads/${j.id}/cancel`).then(loadDls), { small: true, kind: 'danger' }) : null,
          j.state === 'failed' || j.state === 'cancelled' ? ui.button('Retry', () => ctx.call('POST', `/api/downloads/${j.id}/retry`).then(loadDls), { small: true }) : null,
          ['done', 'failed', 'cancelled'].includes(j.state) ? ui.button('Dismiss', () => ctx.call('DELETE', `/api/downloads/${j.id}`).then(loadDls), { small: true, kind: 'ghost' }) : null))));
    } catch { /* optional */ }
  }
  const grid = columns(panel(header('Catalog', ui.button('Refresh', load, { small: true, kind: 'ghost' })), tree, list),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' },
      panel(header('Download from Hugging Face'), h('div', { style: 'display:flex;gap:6px' }, hfIn, ui.button('Look up', resolve, { small: true })), pick, dls),
      panel(header('Discovered GGUFs'), disc)), 400);
  cleanups.push(grid.cleanup);
  el.append(grid);
  load(); loadDls();
  every(loadDls, 3000, cleanups);
}

// ------------------------------------------------------------------ Playground
function playgroundTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const target = ui.select([]), sys = ui.input({ placeholder: 'System prompt (optional)' });
  const log = h('div', { style: 'display:flex;flex-direction:column;gap:10px;min-height:200px;max-height:calc(100vh - 360px);overflow:auto' });
  const input = ui.textarea({ rows: 3, placeholder: 'Message… (Ctrl+Enter to send)' });
  const send = ui.button('Send', () => go(), { kind: 'primary' });
  const stopBtn = ui.button('Stop', () => ctrl?.abort(), { kind: 'ghost' });
  stopBtn.style.display = 'none';
  const temp = ui.input({ type: 'number', value: '0.7' }); temp.step = '0.1';
  const maxTok = ui.input({ type: 'number', value: '1024' });
  const msgs = [], replies = [];
  let ctrl = null, tpsEl = null;
  cleanups.push(() => ctrl?.abort());
  const bubble = (role, text) => h('div', { style: `align-self:${role === 'user' ? 'flex-end' : 'flex-start'};max-width:85%;padding:8px 12px;border-radius:10px;white-space:pre-wrap;font-size:13px;line-height:1.55;background:${role === 'user' ? 'var(--tacc,rgba(255,178,36,.13))' : 'var(--inset,#131926)'};border:1px solid var(--bd,#1D2430)` }, text);
  async function go() {
    const t = input.value.trim();
    if (!t || !target.value) return;
    input.value = '';
    msgs.push({ role: 'user', content: t });
    log.append(bubble('user', t));
    const out = bubble('assistant', ''), think = h('div', { style: 'font-size:11.5px;color:var(--mut,#8A94A6);white-space:pre-wrap' });
    const wrap = h('div', { style: 'display:flex;flex-direction:column;gap:4px;align-self:flex-start;max-width:85%' }, think, out);
    log.append(wrap); log.scrollTop = log.scrollHeight;
    let text = '', reasoning = '', metrics = null;
    ctrl = new AbortController(); send.disabled = true; stopBtn.style.display = '';
    try {
      const request = { messages: [...(sys.value.trim() ? [{ role: 'system', content: sys.value.trim() }] : []), ...msgs], temperature: Number(temp.value), max_tokens: Number(maxTok.value), stream: true };
      const [iname, imodel] = target.value.split('/');
      if (imodel) request.model = imodel;  // a router serves the model named in the request
      await ctx.call('POST', '/api/chat', { json: { target: { name: iname }, request }, stream: true, signal: ctrl.signal, onEvent: d => {
        if (!d || d === '[DONE]') return;
        let j; try { j = JSON.parse(d); } catch { return; }
        if (j.lcpp_metrics) { metrics = j.lcpp_metrics; return; }
        if (j.error) { out.textContent = `Error: ${j.error.message || j.error}`; return; }
        const delta = j.choices?.[0]?.delta || {};
        if (delta.reasoning_content || delta.reasoning) { reasoning += delta.reasoning_content || delta.reasoning; think.textContent = reasoning; }
        if (delta.content) { text += delta.content; out.textContent = text; }
        log.scrollTop = log.scrollHeight;
      } });
    } catch (e) { if (e.name !== 'AbortError') out.textContent = `Error: ${errText(e)}`; }
    finally { send.disabled = false; stopBtn.style.display = 'none'; ctrl = null; }
    msgs.push({ role: 'assistant', content: text });
    if (metrics) {
      wrap.append(h('span', { style: `font-family:${MONO};font-size:11px;color:var(--mut,#8A94A6)` }, `${metrics.tokens_per_s} tok/s · TTFT ${metrics.ttft_ms} ms · ${metrics.prompt_tokens} → ${metrics.completion_tokens} tokens · ${fmtSecs(metrics.total_ms / 1000)}`));
      replies.push(metrics);
      const props = { categories: replies.map((_, i) => `#${i + 1}`), series: [{ label: 'tok/s', values: replies.map(r => r.tokens_per_s) }], unit: 'count', height: 110, label: 'Tokens per second, per reply' };
      if (tpsEl) tpsEl.update(props); else { tpsEl = chart(charts.BarChart, props); tpsBox.replaceChildren(tpsEl); cleanups.push(() => tpsEl.unmount()); }
    }
  }
  input.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') go(); });
  const tpsBox = h('div', {}, ui.text('Each reply\'s speed appears here.', { muted: true, small: true }));
  const grid = columns(panel(header('Chat', target, ui.button('Clear', () => { msgs.length = 0; log.replaceChildren(); }, { small: true, kind: 'ghost' })), sys, log, input, h('div', { style: 'display:flex;gap:8px' }, send, stopBtn)),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, panel(header('Sampling'), ui.field('Temperature', temp), ui.field('Max tokens', maxTok)), panel(header('Tokens / s per reply'), tpsBox)), 320);
  cleanups.push(grid.cleanup);
  el.append(grid);
  ctx.call('GET', '/api/instances').then(r => {
    const ready = r.json.filter(i => i.state === 'ready');
    if (!ready.length) { log.replaceChildren(ui.empty('No instance is ready', 'Launch one on the Instances tab.', ui.button('Instances', () => ctx.navigate('#/s/lcpp/instances'), { kind: 'primary' }))); return; }
    target.replaceChildren(...ready.flatMap(i => i.kind === 'router' ? (i.models || []).map(m => h('option', { value: `${i.name}/${m.id}` }, `${i.name} · ${m.id}`)) : [h('option', { value: i.name }, `${i.name} · ${i.model_id}`)]));
    const want = store.get('lcpp.chatTarget');
    if (want && ready.some(i => i.name === want)) target.value = want;
  }).catch(e => ctx.toast(errText(e), 'error'));
}

// ------------------------------------------------------------------ Relay publishing
function publishingTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const out = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' });
  async function load() {
    try {
      const r = (await ctx.call('GET', '/api/relay')).json, s = r.status;
      out.replaceChildren(
        panel(header('Relay', ui.button('Test', async () => { try { const t = (await ctx.call('POST', '/api/relay/test')).json; ctx.toast(t.reachable ? `Reachable in ${t.latency_ms} ms` : `Unreachable: ${t.error}`, t.reachable ? 'success' : 'error'); load(); } catch (e) { ctx.toast(errText(e), 'error'); } }, { small: true }),
          ui.button('Open the Relay page', () => ctx.navigate('#/s/relay/endpoints'), { small: true, kind: 'ghost' })),
          h('div', { style: 'display:flex;gap:16px;flex-wrap:wrap' }, stat('URL', s.url), stat('State', s.reachable ? `reachable · ${s.latency_ms} ms` : 'unreachable'), stat('Published', String(r.owned.length))), s.error ? ui.badge(s.error, 'red') : null),
        panel(header('Published by the Launcher', r.owned.some(o => o.orphan) ? ui.button('Remove orphans', async () => { await ctx.call('POST', '/api/relay/cleanup'); load(); }, { small: true, kind: 'danger' }) : null),
          ...(r.owned.length ? r.owned.map(o => card(h, h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('strong', {}, o.alias || o.key), ui.badge(o.health, o.health === 'healthy' ? 'green' : 'red'), o.orphan ? ui.badge('orphan: no instance', 'red') : null,
            h('span', { style: 'flex:1' }), h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` }, `${o.instance || '—'} · ${fmtAgo(o.registered_ts)}`)),
            h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, `models: ${o.models.join(', ')}`),
            h('div', {}, ui.button('Unregister', async () => { await ctx.call('DELETE', `/api/relay/registrations/${enc(o.key)}`); load(); }, { small: true, kind: 'ghost' }))))
            : [ui.text('Nothing is published. Launch with "Publish to the relay", or publish a running instance from the Instances tab.', { muted: true, small: true })])),
        panel(header('Other relay endpoints'), ...(r.others || []).map(o => h('div', { style: 'display:flex;gap:8px;align-items:center;font-size:12.5px' }, h('span', { style: 'flex:1' }, o.name), ui.badge(o.health, o.health === 'healthy' ? 'green' : 'red'), h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` }, o.base_url)))));
    } catch (e) { out.replaceChildren(ui.badge(errText(e), 'red')); }
  }
  el.append(out);
  load();
  every(load, 10000, cleanups);
}

// ------------------------------------------------------------------ Launcher settings
function settingsTab(el, ctx) {
  const { ui } = ctx, h = ui.h;
  const out = h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:820px' });
  ctx.call('GET', '/api/settings').then(r => {
    const s = r.json;
    const binary = ui.input({ value: s.llama.binary }), pStart = ui.input({ type: 'number', value: s.ports.start }), pEnd = ui.input({ type: 'number', value: s.ports.end });
    const relayUrl = ui.input({ value: s.relay.url }), auto = h('input', { type: 'checkbox', checked: s.relay.auto_register });
    const scan = ui.textarea({ rows: 3, value: s.scan_dirs.join('\n') });
    const params = ui.textarea({ rows: 6, value: JSON.stringify(s.llama.server_params, null, 2) }), env = ui.textarea({ rows: 4, value: JSON.stringify(s.llama.environment, null, 2) });
    params.style.fontFamily = env.style.fontFamily = MONO;
    const save = ui.button('Save', async () => {
      let sp, en;
      try { sp = JSON.parse(params.value || '{}'); en = JSON.parse(env.value || '{}'); } catch { return ctx.toast('Server params and environment must be JSON objects', 'error'); }
      try {
        await ctx.call('PUT', '/api/settings', { json: { ...s, llama: { ...s.llama, binary: binary.value.trim(), server_params: sp, environment: en }, ports: { start: Number(pStart.value), end: Number(pEnd.value) },
          relay: { ...s.relay, url: relayUrl.value.trim(), auto_register: auto.checked }, scan_dirs: scan.value.split('\n').map(x => x.trim()).filter(Boolean) } });
        ctx.toast('Launcher settings saved (new instances use them)', 'success');
      } catch (e) { ctx.toast(errText(e), 'error'); }
    }, { kind: 'primary' });
    out.replaceChildren(panel(header('Launcher settings'), ui.text('lcpp\'s own settings (services/lcpp/data/lcpp.json). GAIFA\'s port, autostart and env for this mod are on the generic Settings tab.', { muted: true, small: true }),
      ui.field('llama-server binary', binary, 'Relative to services/lcpp'), h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, ui.field('Instance ports from', pStart), ui.field('to', pEnd)),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end' }, ui.field('Relay URL', relayUrl), h('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12.5px' }, auto, 'Publish new instances by default')),
      ui.field('Scan folders', scan, 'One per line; "models" is GAIFA\'s data/models/llm'), ui.field('Server params (every instance)', params), ui.field('Environment', env), h('div', {}, save)));
  }).catch(e => out.replaceChildren(ui.badge(errText(e), 'red')));
  el.append(out);
}
