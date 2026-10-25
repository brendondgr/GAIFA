// Images & Video: the Run tab. Pick a workflow, fill the form built from its input schema (presets
// fill it too), run it (making room in memory if asked), and watch the queue and results.
import { chartCard, charts, rh } from '/mod-charts.js';
import { callRoom, columns, header, panel, stat, store, fmtSecs, fmtAgo, MONO } from '/mod-kit.js';
import { schemaForm } from '/mod-form.js';
import { TASK_LABEL, comfyLink, errText } from './page.js';

const ORDER = ['prompt', 'prompt_2', 'negative', 'image', 'image_2', 'image_3', 'mask', 'aspect', 'megapixels', 'seconds',
  'strength', 'width', 'height', 'frames', 'fps', 'seed', 'steps', 'cfg'];
const ADVANCED = ['width', 'height', 'megapixels', 'frames', 'fps', 'seed', 'steps', 'cfg'];
const some = (...a) => a.filter(x => x != null && x !== false);   // replaceChildren would print null
const JOB_TONE = { done: 'green', failed: 'red', cancelled: 'dim', running: 'accent', queued: 'dim' };
// Plan 31.3: a run waiting for GAIFA's GPU slot (another mod's work runs first).
const gpuWait = j => {
  if (j.stage !== 'waiting_gpu') return null;
  const a = (j.ahead || [])[0], eta = j.eta_s > 0 ? (j.eta_s >= 90 ? `, about ${Math.round(j.eta_s / 60)} min` : `, about ${Math.round(j.eta_s)} s`) : '';
  return `Waiting for the GPU${a ? `: ${a.service}${a.label ? ` (${a.label})` : ''}` : ''}${eta}`;
};

export function runTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  let wf = params.get('wf') || store.get('comfy.wf', '');
  let selected = params.get('job') || null;
  let list = [], detail = null, form = null, jobs = [];

  const pick = ui.select([], { onchange: () => choose(pick.value) });
  pick.setAttribute('aria-label', 'Workflow');
  pick.style.flex = '1 1 260px';
  const about = h('div', { style: 'display:flex;flex-direction:column;gap:4px' });
  const presets = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' });
  const formBox = h('div');
  const runBtn = ui.button('Run', () => go(), { kind: 'primary' });
  const note = h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' });
  const result = h('div', { style: 'display:flex;flex-direction:column;gap:10px' });
  const queue = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });

  const main = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' },
    panel(header('Run a workflow', comfyLink(ctx, 'Edit in ComfyUI ↗')), h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, pick), about, presets, formBox,
      h('div', { style: 'display:flex;gap:10px;align-items:center' }, runBtn, note)),
    panel(header('Result'), result));
  const side = panel(header('Queue & recent', ui.button('Refresh', () => loadJobs(), { small: true, kind: 'ghost' })), queue);
  const cols = columns(main, side, 360);
  cleanups.push(cols.cleanup);
  const timeChart = chartCard({
    title: 'Time per run', ranges: ['7d', '30d', '90d'], height: 140,
    load: range => ctx.call('GET', '/v1/stats', { query: { range } }).then(r => r.json),
    draw: (d, o) => rh(charts.BarChart, { categories: d.workflows.map(w => w.name), unit: 's',
      series: [{ name: 'Median seconds', values: d.workflows.map(w => w.p50_s) }], ...o }),
  });
  const runsChart = chartCard({
    title: 'Runs per workflow', ranges: ['7d', '30d', '90d'], height: 140,
    load: range => ctx.call('GET', '/v1/stats', { query: { range } }).then(r => r.json),
    draw: (d, o) => rh(charts.BarChart, { categories: d.workflows.map(w => w.name), stacked: true, unit: 'runs',
      series: [{ name: 'Done', values: d.workflows.map(w => w.done) }, { name: 'Failed', values: d.workflows.map(w => w.failed) },
        { name: 'Cancelled', values: d.workflows.map(w => w.cancelled) }], ...o }),
  });
  cleanups.push(() => timeChart.unmount(), () => runsChart.unmount());
  el.append(h('div', { style: 'display:flex;flex-direction:column;gap:12px' }, cols,
    h('div', { style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px' }, timeChart, runsChart)));

  // ---- workflows and the form ---------------------------------------------------------------
  async function loadList() {
    try {
      const r = (await ctx.call('GET', '/v1/workflows')).json;
      list = r.workflows.filter(w => w.state === 'ready');
      const groups = {};
      list.forEach(w => (groups[w.task] ||= []).push(w));
      pick.replaceChildren(...Object.entries(groups).map(([t, ws]) => h('optgroup', { label: TASK_LABEL[t] || t },
        ...ws.map(w => h('option', { value: w.id }, w.name + (r.defaults[w.task] === w.id ? '  ★' : ''))))));
      if (!list.length) {
        formBox.replaceChildren(ui.empty('No ready workflows', 'Import one, or fix one on the Workflows tab.',
          ui.button('Workflows', () => ctx.navigate('#/s/comfy/workflows'), { kind: 'primary' })));
        runBtn.disabled = true;
        return;
      }
      if (!list.some(w => w.id === wf)) wf = list[0].id;
      pick.value = wf;
      await choose(wf);
    } catch (e) { formBox.replaceChildren(ui.empty('Could not list workflows', errText(e))); }
  }

  async function choose(id) {
    wf = id;
    store.set('comfy.wf', id);
    setHash();
    try { detail = (await ctx.call('GET', `/v1/workflows/${id}`)).json; } catch (e) { formBox.replaceChildren(ui.text(errText(e))); return; }
    about.replaceChildren(...some(
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, ui.badge(TASK_LABEL[detail.task] || detail.task, 'dim'),
        h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` }, detail.id),
        detail.memory_gb ? h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, `~${detail.memory_gb} GB`) : null),
      detail.description && detail.description !== detail.name ? ui.text(detail.description, { small: true, muted: true }) : null));
    const saved = store.get(`comfy.values.${id}`, {});
    form = schemaForm(ctx, detail.schema, {
      values: saved, order: ORDER, advanced: ADVANCED.filter(k => detail.schema.properties[k] && !(detail.schema.required || []).includes(k)),
      kinds: ['image'], upload: async f => {
        const fd = new FormData();
        fd.append('file', f, f.name);
        return (await ctx.call('POST', '/v1/uploads', { form: fd })).json.value;
      },
    });
    form.onchange = v => store.set(`comfy.values.${id}`, Object.fromEntries(Object.entries(v).filter(([k]) => k !== 'seed')));
    formBox.replaceChildren(form);
    presets.replaceChildren(...(Object.keys(detail.presets || {}).length ? [h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' }, 'Presets'),
      ...Object.entries(detail.presets).map(([name, vals]) => ui.button(name, () => { form.set(vals); ctx.toast(`Preset ${name}`, 'info'); }, { small: true }))] : []));
    runBtn.disabled = false;
  }

  async function go() {
    if (!form) return;
    const inputs = form.values();
    const missing = (detail.schema.required || []).filter(k => inputs[k] == null || inputs[k] === '');
    if (missing.length) { ctx.toast(`Fill in: ${missing.join(', ')}`, 'error'); return; }
    runBtn.disabled = true;
    note.textContent = ctx.service.load === 'loaded' ? 'Queuing…' : 'Starting ComfyUI (about 15 s), then queuing…';
    try {
      const job = (await callRoom(ctx, 'POST', '/v1/run', { json: { workflow: wf, inputs } })).json;
      selected = job.id;
      setHash();
      note.textContent = '';
      await loadJobs();
    } catch (e) {
      note.textContent = '';
      if (!e.cancelled) {
        const errs = e.data?.body?.data?.errors || e.data?.errors;
        ctx.toast(errs ? errs.join('; ') : errText(e), 'error');
      }
    } finally { runBtn.disabled = false; }
  }

  // ---- jobs ----------------------------------------------------------------------------------
  async function loadJobs() {
    try { jobs = (await ctx.call('GET', '/v1/jobs', { query: { limit: 30 } })).json.jobs; } catch { return; }
    drawQueue();
    drawResult();
  }

  function drawQueue() {
    if (!jobs.length) { queue.replaceChildren(ui.text('No runs yet.', { muted: true, small: true })); return; }
    queue.replaceChildren(...jobs.map(j => {
      const active = j.state === 'queued' || j.state === 'running';
      const bar = active ? h('div', { style: 'height:3px;border-radius:2px;background:var(--inset,#131926);overflow:hidden' },
        h('div', { style: `height:100%;width:${Math.round((j.progress || 0) * 100)}%;background:var(--acc,#FFB224);transition:width .4s` })) : null;
      return h('button', {
        type: 'button', onclick: () => { selected = j.id; setHash(); drawQueue(); drawResult(); },
        style: `text-align:left;border:1px solid ${j.id === selected ? 'var(--acct,#FFB224)' : 'var(--bd,#1D2430)'};background:var(--inset,#131926);border-radius:7px;padding:7px 9px;cursor:pointer;color:inherit;font:inherit;display:flex;flex-direction:column;gap:4px`,
      }, h('div', { style: 'display:flex;gap:6px;align-items:center' },
        h('span', { style: 'flex:1;min-width:0;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, j.label || j.workflow),
        ui.badge(j.state === 'running' && j.progress != null ? `${Math.round(j.progress * 100)}%` : j.stage === 'waiting_gpu' ? 'waiting for GPU' : j.state, JOB_TONE[j.state])),
      h('div', { style: `font-size:11px;color:var(--mut,#8A94A6);font-family:${MONO}` }, `${j.workflow} · ${fmtAgo(j.created)}` +
        (j.finished && j.started ? ` · ${fmtSecs(j.finished - j.started)}` : '')), bar);
    }));
  }

  async function drawResult() {
    const j = jobs.find(x => x.id === selected) || jobs[0];
    if (!j) { result.replaceChildren(ui.text('Run a workflow to see its result here.', { muted: true, small: true })); return; }
    const key = `${j.id}:${j.state}:${(j.outputs || []).length}:${gpuWait(j) || ''}`;
    if (result.dataset.key === key && j.state !== 'running') return;
    result.dataset.key = key;
    const active = j.state === 'queued' || j.state === 'running';
    const stats = h('div', { style: 'display:flex;gap:18px;flex-wrap:wrap' },
      stat('Workflow', j.workflow), stat('State', j.state), stat('Seed', j.inputs?.seed ?? '—'),
      stat('Time', j.finished && j.started ? fmtSecs(j.finished - j.started) : active ? '…' : '—'), stat('Peak memory', j.peak_gb ? `${j.peak_gb} GB` : '—'));
    const actions = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
      active ? ui.button('Cancel', async () => { try { await ctx.call('POST', `/v1/queue/${j.id}/cancel`); loadJobs(); } catch (e) { ctx.toast(errText(e), 'error'); } }, { small: true, kind: 'danger' }) : null,
      !active ? ui.button('Run again (new seed)', () => again(j), { small: true }) : null,
      j.state === 'done' ? ui.button('Open Outputs', () => ctx.navigate('#/outputs'), { small: true, kind: 'ghost' }) : null);
    const media = h('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px' });
    result.replaceChildren(...some(stats, j.error && j.state !== 'cancelled' ? h('div', { style: `font-family:${MONO};font-size:12px;color:var(--rd,#F85149);white-space:pre-wrap` }, j.error) : null,
      active ? ui.text(gpuWait(j) ? `${gpuWait(j)}…` : j.state === 'queued' ? 'Waiting in the queue…' : `Running… ${Math.round((j.progress || 0) * 100)}%`, { muted: true }) : null,
      media, j.inputs?.prompt ? ui.text(j.inputs.prompt, { small: true, muted: true }) : null, actions));
    for (const o of j.outputs || []) {
      let url = null;
      try { url = (await ctx.call('GET', `/v1/files/${o.path}`)).url; } catch { /* gone */ }
      const view = o.kind === 'video' ? h('video', { src: url, controls: true, loop: true, muted: true, autoplay: true, style: 'width:100%;border-radius:7px;background:#000' })
        : h('img', { src: url, alt: j.label || o.name, style: 'width:100%;border-radius:7px;display:block' });
      media.append(h('figure', { style: 'margin:0;display:flex;flex-direction:column;gap:6px' }, view,
        h('div', { style: 'display:flex;gap:6px;align-items:center' },
          h('span', { style: `flex:1;min-width:0;font-family:${MONO};font-size:11px;color:var(--mut,#8A94A6);overflow:hidden;text-overflow:ellipsis;white-space:nowrap`, title: o.path }, o.name),
          o.kind === 'image' ? ui.button('Use as input', () => useAsInput(o), { small: true }) : null)));
    }
  }

  function again(j) {
    if (j.workflow !== wf) { pick.value = j.workflow; choose(j.workflow).then(() => { form.set({ ...j.inputs, seed: undefined }); go(); }); return; }
    form.set({ ...j.inputs, seed: undefined });
    go();
  }

  function useAsInput(o) {
    const take = list.filter(w => w.task === 'image-edit' || w.task === 'image-to-video' || w.task === 'upscale' || w.task === 'remove-background');
    const field = detail?.schema?.properties?.image ? 'image' : null;
    if (field) { form.set({ image: o.path }); ctx.toast('Set as the input image', 'info'); return; }
    if (!take.length) { ctx.toast('No ready workflow takes an image yet', 'error'); return; }
    store.set(`comfy.values.${take[0].id}`, { ...store.get(`comfy.values.${take[0].id}`, {}), image: o.path });
    pick.value = take[0].id;
    choose(take[0].id).then(() => ctx.toast(`Opened ${take[0].name} with this image`, 'info'));
  }

  function setHash() {
    const q = new URLSearchParams({ wf, ...(selected ? { job: selected } : {}) });
    history.replaceState(null, '', `#/s/comfy/run?${q}`);   // no remount: only the selection changed
  }

  loadList();
  loadJobs();
  const t = setInterval(() => { if (jobs.some(j => j.state === 'queued' || j.state === 'running')) loadJobs(); }, 1500);
  const off = ctx.on('job', () => loadJobs());
  cleanups.push(() => clearInterval(t), () => off?.());
}

