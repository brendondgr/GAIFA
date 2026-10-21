// 3D Generate (gen3d) page inside AIHub: Create and Jobs tabs (design brief Part B4). Calls
// 3DGenerate's own API through ctx.call (AIHub's proxy, so memory is managed); live progress
// comes from its /v1/events stream. Finished jobs also appear on the Outputs page.
import { chartCard, chart, charts, rh } from '/mod-charts.js';
import { requireRunning, callRoom, segmented, header, panel, columns, stat, store, fmtSecs, fmtAgo, MONO } from '/mod-kit.js';
import { mountViewer } from '/viewer3d.js';
import { ENGINE_OPTIONS, imagePanel } from './image.js';

const STAGES = ['shape', 'parts', 'rig', 'preview'];
const STAGE_LABEL = { shape: 'Shape', parts: 'Parts', rig: 'Rig', preview: 'Preview' };
const STAGE_COLOR = { shape: 'var(--s1,#58C4DD)', parts: 'var(--s2,#FFB224)', rig: 'var(--s3,#BC8CFF)', preview: 'var(--s4,#3FB950)' };
const TONE = { done: 'green', failed: 'red', canceled: 'dim', running: 'accent', queued: 'dim' };
// Plan 31.3: a job waiting for AIHub's GPU slot (another mod's work runs first).
const gpuWait = j => {
  if (j.stage !== 'waiting_gpu') return null;
  const a = (j.ahead || [])[0], eta = j.eta_s > 0 ? (j.eta_s >= 90 ? `, about ${Math.round(j.eta_s / 60)} min` : `, about ${Math.round(j.eta_s)} s`) : '';
  return `Waiting for the GPU${a ? `: ${a.service}${a.label ? ` (${a.label})` : ''}` : ''}${eta}`;
};
const errText = e => e.detail || e.message || 'Request failed';

export default {
  tabs: [{ id: 'create', label: 'Create', icon: 'plus' }, { id: 'jobs', label: 'Jobs', icon: 'layers' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, '3D Generate')) return;
    const cleanups = [];
    (ctx.tab === 'jobs' ? jobsTab : createTab)(el, ctx, cleanups);
    return () => cleanups.forEach(f => { try { f(); } catch { /* gone */ } });
  },
};

// Live job updates from /v1/events; restarted every 10 minutes so the stream's buffer stays small.
function liveJobs(ctx, onJob, onDeleted, cleanups) {
  let ctrl = null, stopped = false;
  const run = () => {
    if (stopped) return;
    ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 600000);
    ctx.call('GET', '/v1/events', { stream: true, signal: ctrl.signal, onEvent: line => {
      let d; try { d = JSON.parse(line); } catch { return; }
      if (d && d.stages && d.status) onJob(d);
      else if (d && d.id && !d.state && !d.title && Object.keys(d).length <= 3) onDeleted(d.id);
    } }).catch(() => {}).finally(() => { clearTimeout(timer); if (!stopped) setTimeout(run, 1500); });
  };
  run();
  cleanups.push(() => { stopped = true; ctrl?.abort(); });
}

// ------------------------------------------------------------------ Create
function createTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const field = (...a) => { const f = ui.field(...a); f.style.flex = '1 1 160px'; return f; };
  const saved = store.get('gen3d.create', {});
  const st = { preset: saved.preset || 'lowpoly', stages: saved.stages || ['shape', 'parts', 'rig', 'preview'], template: saved.template || 'Character',
    engine: saved.engine || 'cube3d', images: saved.images || {} };
  let opts = null, templates = {}, img = null;
  const engine = ui.select(ENGINE_OPTIONS.map(o => ({ value: o.value, label: o.pick })), { onchange: () => { st.engine = engine.value; renderEngine(); changed(); } });
  engine.value = st.engine;
  engine.setAttribute('aria-label', 'Engine');
  const imgBox = h('div');

  const prompt = ui.textarea({ rows: 3, placeholder: 'e.g. low-poly cartoon fox sitting', value: saved.prompt || '' });
  prompt.setAttribute('aria-label', 'Prompt');
  const preset = segmented([{ value: 'lowpoly', label: 'Low-poly' }, { value: 'fast', label: 'Fast' }, { value: 'balanced', label: 'Balanced' }, { value: 'quality', label: 'Quality' }],
    st.preset, v => { st.preset = v; presetHelp(); changed(); }, 'Preset');
  const presetNote = ui.text('', { muted: true, small: true });
  const stageBoxes = STAGES.map(s => {
    const cb = h('input', { type: 'checkbox', checked: st.stages.includes(s), onchange: () => { st.stages = STAGES.filter((x, i) => stageBoxes[i].cb.checked); partsRow.style.display = st.stages.includes('parts') ? 'flex' : 'none'; changed(); } });
    const lab = h('label', { style: 'display:inline-flex;gap:6px;align-items:center;font-size:12.5px;padding:4px 10px;border:1px solid var(--bd,#1D2430);border-radius:6px' }, cb, STAGE_LABEL[s]);
    return { s, cb, lab };
  });
  const template = ui.select([], { onchange: () => { st.template = template.value; if (templates[st.template]) parts.value = templates[st.template].join(', '); changed(); } });
  const parts = ui.input({ placeholder: 'head, body, tail, legs', value: saved.parts || '' });
  parts.addEventListener('input', changed);
  const partsRow = h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, field('Part template', template), field('Part names (comma separated, up to 8)', parts));
  const num = (ph) => { const i = ui.input({ type: 'number', placeholder: ph }); i.min = '0'; i.addEventListener('input', changed); return i; };
  const fShape = num('preset'), fParts = num('preset'), fRig = num('preset'), seed = num('0');
  const eta = h('div', { style: 'display:flex;gap:16px;flex-wrap:wrap;align-items:center;min-height:30px' });
  const submit = ui.button('Generate', () => go(), { kind: 'primary' });
  const upFile = h('input', { type: 'file', accept: '.glb,.gltf,.obj,.ply,.stl,.off', style: 'font-size:12px' });
  const upBtn = ui.button('Split / rig this mesh', () => upload(), { small: true });

  function presetHelp() {
    const p = opts?.presets?.[st.preset];
    presetNote.textContent = p?.help || '';
    for (const [inp, g] of [[fShape, 'shape'], [fParts, 'parts'], [fRig, 'rig']]) {
      const v = p?.[g]?.target_faces;
      inp.placeholder = v ? `${v.toLocaleString()} (preset)` : 'full detail';
    }
  }

  function body() {
    const n = i => (i.value === '' ? undefined : Number(i.value));
    if (img) {
      const b = { ...img.body(), stages: st.stages, chat_id: 'new' };
      if (st.stages.includes('parts')) b.parts = { parts: parts.value.split(',').map(x => x.trim()).filter(Boolean) };
      if (n(fRig) !== undefined) b.rig = { target_faces: n(fRig) };
      return b;
    }
    const b = { prompt: prompt.value.trim(), stages: st.stages, preset: st.preset, chat_id: 'new' };
    b.shape = { target_faces: n(fShape), seed: n(seed) };
    b.parts = { parts: parts.value.split(',').map(x => x.trim()).filter(Boolean), target_faces: n(fParts), seed: n(seed) };
    b.rig = { target_faces: n(fRig) };
    for (const g of ['shape', 'parts', 'rig']) for (const k of Object.keys(b[g])) if (b[g][k] === undefined) delete b[g][k];
    return b;
  }

  let etaTimer = 0;
  function changed() {
    if (img) st.images[st.engine] = img.state();
    store.set('gen3d.create', { preset: st.preset, stages: st.stages, template: st.template, prompt: prompt.value, parts: parts.value,
      engine: st.engine, images: st.images });
    clearTimeout(etaTimer);
    etaTimer = setTimeout(estimate, 350);
  }
  prompt.addEventListener('input', changed);
  cleanups.push(() => clearTimeout(etaTimer));

  async function estimate() {
    const b = body();
    if (img && !b.image) b.image = 'upload';                  // the time doesn't depend on which picture
    if (!img && st.stages.includes('shape') && !b.prompt) { eta.replaceChildren(ui.text('Describe what to make.', { muted: true, small: true })); return; }
    try {
      const r = (await ctx.call('POST', '/v1/estimate', { json: b })).json;
      eta.replaceChildren(stat('ETA', fmtSecs(r.eta_s)), stat('Its own time', fmtSecs(r.own_s)), stat('Queue wait', fmtSecs(r.wait_s)),
        stat('Done at', new Date(r.done_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
        h('div', { style: 'display:flex;gap:2px;flex:1 1 200px;height:10px;border-radius:3px;overflow:hidden;min-width:120px', title: 'Time per step' },
          r.plan.map(p => h('span', { title: `${p.sub || p.stage}: ${fmtSecs(p.seconds)}`, style: `flex:${Math.max(p.seconds, 1)};background:${STAGE_COLOR[p.stage] || 'var(--other,#46526A)'}` }))));
    } catch (e) {
      eta.replaceChildren(ui.badge(Array.isArray(e.data?.body?.detail) ? e.data.body.detail.map(d => d.msg || d).join('; ') : errText(e), 'red'));
    }
  }

  async function go() {
    const b = body();
    if (img && st.stages.includes('shape') && !b.image) return ctx.toast('Choose a picture first: upload one or pick a recent output', 'info');
    if (!img && st.stages.includes('shape') && !b.prompt) return ctx.toast('Describe what to make first', 'info');
    if (st.stages.includes('parts') && !b.parts.parts.length) return ctx.toast('Name at least one part, or untick Parts', 'info');
    submit.disabled = true; submit.textContent = 'Queueing…';
    try {
      const job = (await callRoom(ctx, 'POST', '/v1/jobs', { json: b })).json;
      ctx.toast(`Queued “${job.title}”`, 'success');
      ctx.navigate(`#/s/gen3d/jobs?id=${job.id}`);
    } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } finally { submit.disabled = false; submit.textContent = 'Generate'; }
  }

  async function upload() {
    const f = upFile.files[0];
    if (!f) return ctx.toast('Choose a mesh file first', 'info');
    const stages = st.stages.filter(s => s !== 'shape');
    if (!stages.length) return ctx.toast('Tick Parts, Rig or Preview for an uploaded mesh', 'info');
    const b = body();
    upBtn.disabled = true;
    try {
      const job = (await callRoom(ctx, 'POST', '/v1/jobs/upload', { form: { mesh: f, job: JSON.stringify({ ...b, stages, prompt: '', chat_id: 'new' }) } })).json;
      ctx.toast(`Queued “${job.title}”`, 'success');
      ctx.navigate(`#/s/gen3d/jobs?id=${job.id}`);
    } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } finally { upBtn.disabled = false; }
  }

  const cubeOnly = h('div', { style: 'display:flex;flex-direction:column;gap:10px' },
    h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, preset, presetNote), prompt);
  const faceRow = h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;margin-top:8px' }, field('Shape faces', fShape), field('Parts faces (all together)', fParts), field('Rigged asset faces', fRig), field('Seed', seed));
  function renderEngine() {
    const e = opts?.engines?.find(x => x.id === st.engine);
    const isImage = e ? e.input === 'image' : st.engine !== 'cube3d';   // what the engine takes, from /v1/options (plan 20.2)
    cubeOnly.style.display = isImage ? 'none' : 'flex';
    imgBox.style.display = isImage ? 'block' : 'none';
    for (const i of [fShape, seed]) i.parentElement.style.display = isImage ? 'none' : '';
    stageBoxes[0].lab.lastChild.textContent = isImage ? 'Mesh from the picture' : 'Shape';
    if (isImage && e && !st.images[st.engine]) {             // first use of an engine: the mesh and its preview
      st.stages = ['shape', 'preview'];
      stageBoxes.forEach(x => { x.cb.checked = st.stages.includes(x.s); });
      partsRow.style.display = 'none';
    }
    img = isImage && e ? imagePanel(ctx, e, st.images[st.engine] || {}, changed) : null;
    imgBox.replaceChildren(...(img ? [img.el] : isImage ? [ui.text('Loading the engines…', { muted: true, small: true })] : []));
  }
  const form = panel(
    header('Make a 3D asset'),
    h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' }, 'Engine'), engine),
    cubeOnly,
    imgBox,
    h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' }, h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6);margin-right:4px' }, 'Stages'), stageBoxes.map(x => x.lab)),
    partsRow,
    h('details', {}, h('summary', { style: 'cursor:pointer;font-size:12px;color:var(--mut,#8A94A6)' }, 'Face budgets and seed'), faceRow),
    eta,
    h('div', { style: 'display:flex;gap:8px;justify-content:flex-end' }, submit));
  const up = panel(header('Or start from a mesh'), ui.text('Upload a .glb, .obj, .ply or .stl to split it into parts and rig it (the shape stage is skipped).', { muted: true, small: true }),
    h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' }, upFile, upBtn));
  const previews = previewPanel(ctx);
  const durations = jobDurationsCard(ctx);
  const stagesCard = chartCard({
    title: 'Job time per stage', ranges: ['7d', '30d'], height: 150,
    load: range => ctx.call('GET', '/v1/hub/widgets/stages', { query: { range } }).then(r => r.json),
    draw: (d, o) => rh(charts.BarChart, { categories: d.categories, series: d.series.map(s => ({ label: STAGE_LABEL[s.name] || s.name, values: s.values, color: STAGE_COLOR[s.name] })), stacked: true, unit: 'seconds', ...o }),
  });
  cleanups.push(durations.unmount, stagesCard.unmount);
  const grid = columns(h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, form, up, previews),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, stagesCard, durations), 380);
  cleanups.push(grid.cleanup);
  el.append(grid);
  partsRow.style.display = st.stages.includes('parts') ? 'flex' : 'none';
  renderEngine();

  ctx.call('GET', '/v1/options').then(r => {
    opts = r.json; templates = opts.part_templates || {};
    if (opts.engines?.length) {                              // the engine list as gen3d declares it: what each takes and is good for
      engine.replaceChildren(...opts.engines.map(x => h('option', { value: x.id }, `${x.label}: ${x.input === 'image' ? 'picture' : 'text'} → mesh (${x.help})`)));
      engine.value = opts.engines.some(x => x.id === st.engine) ? st.engine : opts.engines[0].id;
      st.engine = engine.value;
    }
    template.replaceChildren(...Object.keys(templates).map(k => h('option', { value: k }, k)), h('option', { value: '' }, 'Custom'));
    template.value = templates[st.template] ? st.template : '';
    if (!parts.value && templates[st.template]) parts.value = templates[st.template].join(', ');
    presetHelp(); renderEngine(); estimate();
  }).catch(e => ctx.toast(errText(e), 'error'));
}

// Where Blender draws previews, saved by gen3d (PUT /v1/settings) and used from the next preview on.
const PREVIEW_NOTE = {
  cpu: 'CPU: software rendering, never touches the GPU; a huge mesh can take a minute. Applies to the next preview.',
  gpu: 'GPU: faster, but a broken giant mesh can hang the GPU (the 2026-10-21 crash). Applies to the next preview.',
};
function previewPanel(ctx) {
  const { ui } = ctx;
  const note = ui.text('', { muted: true, small: true });
  let cur = null;
  const show = v => { cur = v; seg.set(v); note.textContent = PREVIEW_NOTE[v] || ''; };
  const seg = segmented([{ value: 'cpu', label: 'CPU (safer)' }, { value: 'gpu', label: 'GPU (faster)' }], 'cpu', async v => {
    if (v === cur) return;
    try { show((await ctx.call('PUT', '/v1/settings', { json: { preview_device: v } })).json.preview_device); }
    catch (e) { if (cur) seg.set(cur); ctx.toast(errText(e), 'error'); }
  }, 'Preview renders');
  ctx.call('GET', '/v1/settings').then(r => show(r.json.preview_device)).catch(e => { note.textContent = errText(e); });
  return panel(header('Preview renders', seg), note);
}

function jobDurationsCard(ctx) {
  return chartCard({
    title: 'Job durations · 30 days', height: 140, every: 60000,
    load: () => ctx.call('GET', '/v1/jobs', { query: { status: 'done', limit: 200 } }).then(r => r.json.jobs),
    draw: (jobs, o) => {
      const cut = Date.now() / 1000 - 30 * 86400;
      const js = jobs.filter(j => j.finished && j.started && j.finished >= cut).sort((a, b) => a.finished - b.finished).slice(-30);
      return rh(charts.BarChart, { categories: js.map(j => new Date(j.finished * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })),
        series: [{ label: 'Duration', values: js.map(j => Math.round(j.finished - j.started)) }], unit: 'seconds', ...o });
    },
  });
}

// ------------------------------------------------------------------ Jobs
function jobsTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const jobs = new Map();
  let selected = ctx.params.id || null, detailFor = null, viewer = null;
  const list = h('div', { style: 'display:flex;flex-direction:column;gap:4px;max-height:calc(100vh - 220px);overflow:auto;min-width:0' });
  const detail = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' });
  let filt = 'all';
  const filter = segmented([{ value: 'all', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'done', label: 'Done' }, { value: 'failed', label: 'Failed' }], 'all', v => { filt = v; renderList(); }, 'Filter');
  const grid = columns(detail, panel(header('Jobs', filter), list), 360);
  cleanups.push(grid.cleanup, () => viewer?.dispose());
  el.append(grid);

  function progressOf(j) {
    const vals = Object.values(j.stages || {});
    if (!vals.length) return 0;
    return vals.reduce((a, v) => a + (['done', 'skipped', 'failed', 'canceled'].includes(v.state) ? 1 : v.state === 'running' && v.total ? Math.min(1, (v.step || 0) / v.total) * 0.95 : 0), 0) / vals.length;
  }

  function renderList() {
    const all = [...jobs.values()].sort((a, b) => b.created - a.created).filter(j =>
      filt === 'all' || (filt === 'active' ? ['queued', 'running'].includes(j.status) : filt === 'failed' ? ['failed', 'canceled'].includes(j.status) : j.status === filt));
    if (!all.length) { list.replaceChildren(ui.text('No jobs here yet.', { muted: true })); return; }
    list.replaceChildren(...all.map(j => {
      const p = progressOf(j), on = j.id === selected;
      const row = h('button', { type: 'button', onclick: () => select(j.id), style: `display:flex;flex-direction:column;gap:4px;text-align:left;padding:8px 10px;border-radius:7px;cursor:pointer;font:inherit;color:var(--tx,#E6EAF2);border:1px solid ${on ? 'var(--acc,#FFB224)' : 'var(--bd,#1D2430)'};background:${on ? 'var(--hov,#161C28)' : 'var(--inset,#131926)'}` },
        h('div', { style: 'display:flex;gap:8px;align-items:center;min-width:0' },
          h('span', { style: 'flex:1;min-width:0;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis' }, j.title || j.id),
          ui.badge(gpuWait(j) ? 'waiting for GPU' : j.status, TONE[j.status])),
        h('div', { style: 'display:flex;gap:8px;align-items:center;font-size:11px;color:var(--mut,#8A94A6)' },
          h('span', { style: `font-family:${MONO}` }, j.status === 'running' && j.eta ? `${Math.round(p * 100)}% · ${fmtSecs(j.eta.eta_s)} left` : gpuWait(j) ? gpuWait(j) : j.status === 'queued' && j.eta ? `#${j.eta.queue_position} · starts in ${fmtSecs(j.eta.starts_in_s)}` : fmtAgo(j.created)),
          h('span', { style: 'flex:1' }), Object.keys(j.stages || {}).map(s => h('span', { title: `${s}: ${j.stages[s].state}`, style: `width:8px;height:8px;border-radius:2px;background:${j.stages[s].state === 'done' ? STAGE_COLOR[s] : j.stages[s].state === 'running' ? 'var(--acc,#FFB224)' : 'var(--bds,#2A3547)'}` }))),
        ['running', 'queued'].includes(j.status) ? h('div', { style: 'height:3px;border-radius:2px;background:var(--bds,#2A3547);overflow:hidden' }, h('div', { style: `height:100%;width:${Math.round(p * 100)}%;background:var(--acc,#FFB224)` })) : null);
      return row;
    }));
  }

  function select(id) {
    selected = id;
    try { history.replaceState(null, '', `#/s/gen3d/jobs?id=${encodeURIComponent(id)}`); } catch { /* not kept */ }
    renderList(); renderDetail(true);
  }

  function renderDetail(force) {
    const j = selected && jobs.get(selected);
    if (!j) { viewer?.dispose(); viewer = null; detailFor = null; detail.replaceChildren(panel(ui.empty('Pick a job', 'Its stages, the 3D viewer, parts and follow-ups show here.', ui.button('New job', () => ctx.navigate('#/s/gen3d/create'), { kind: 'primary' })))); return; }
    const sig = `${j.id}|${j.status}|${(j.files || []).length}`;
    if (!force && detailFor === sig) { gantt.update?.(j); return; }
    detailFor = sig;
    viewer?.dispose(); viewer = null;
    const head = panel(
      header(j.title || j.id, ui.badge(j.status, TONE[j.status])),
      h('div', { style: 'display:flex;gap:16px;flex-wrap:wrap' }, stat('Job', j.id), stat('Started', j.started ? new Date(j.started * 1000).toLocaleString() : '—'),
        stat('Took', j.started && j.finished ? fmtSecs(j.finished - j.started) : j.eta ? `${fmtSecs(j.eta.eta_s)} left` : '—'),
        stat('Engine', ENGINE_OPTIONS.find(o => o.value === (j.request?.engine || 'cube3d'))?.label || j.request?.engine),
        stat('Preset', j.request?.preset || 'custom'),
        j.result?.shape?.faces != null ? stat('Faces', j.result.shape.faces.toLocaleString() + (j.result.shape.raw_faces && j.result.shape.raw ? ` (raw ${j.result.shape.raw_faces.toLocaleString()})` : '')) : null),
      j.error ? ui.badge(j.error, 'red') : null,
      actions(j));
    gantt = ganttPanel(j);
    const view = h('div');
    const out = [head, gantt.el];
    const glbs = ['rigged.glb', 'parts.glb', 'mesh.glb', 'mesh_raw.glb', ...(j.input_mesh ? [j.input_mesh] : [])].filter(f => (j.files || []).includes(f));
    if ((j.files || []).includes('input.png')) {
      const pic = h('img', { alt: 'The picture this mesh was made from', style: 'max-width:100%;max-height:220px;object-fit:contain;border-radius:8px;background:var(--inset,#131926)' });
      ctx.call('GET', `/v1/jobs/${j.id}/files/input.png`).then(r => { pic.src = r.url; cleanups.push(() => URL.revokeObjectURL(r.url)); }).catch(() => {});
      out.push(panel(header('Picture'), pic));
    }
    if (glbs.length) {
      out.push(panel(header('Viewer'), view));
      mountViewer(view, {
        files: glbs, height: 380,
        url: f => ctx.call('GET', `/v1/jobs/${j.id}/files/${f}`).then(r => { cleanups.push(() => URL.revokeObjectURL(r.url)); return r.url; }),
        rig: (j.files || []).includes('rig.json') ? () => ctx.call('GET', `/v1/jobs/${j.id}/files/rig.json`).then(r => r.json ?? JSON.parse(r.text || 'null')) : null,
      }).then(v => { viewer = v; }).catch(e => view.replaceChildren(ui.text(String(e.message || e), { muted: true })));
    } else if ((j.files || []).includes('preview.png')) {
      const img = h('img', { alt: 'Preview render', style: 'width:100%;border-radius:8px;background:var(--inset,#131926)' });
      ctx.call('GET', `/v1/jobs/${j.id}/files/preview.png`).then(r => { img.src = r.url; cleanups.push(() => URL.revokeObjectURL(r.url)); });
      out.push(panel(header('Preview'), img));
    }
    const plist = j.result?.parts?.parts;
    if (plist?.length) out.push(partsPanel(j, plist));
    const peaks = STAGES.filter(s => j.result?.[s]?.peak_gpu_gb != null);
    if (peaks.length) {
      const c = document.createElement('div');
      out.push(panel(header('Peak GPU memory per stage'), c));
      const ch = chart(charts.HBarChart, { categories: peaks.map(s => STAGE_LABEL[s]), series: [{ label: 'Peak GPU', values: peaks.map(s => j.result[s].peak_gpu_gb * 1e9) }], unit: 'bytes', height: 24 * peaks.length + 20 });
      c.append(ch); cleanups.push(ch.unmount);
    }
    detail.replaceChildren(...out);
  }
  let gantt = { el: null };

  function partsPanel(j, plist) {
    const rows = plist.map(p => {
      const cb = h('input', { type: 'checkbox', checked: true, onchange: () => viewer?.setPartVisible(p.index, cb.checked), 'aria-label': `Show ${p.name}` });
      return h('label', { style: 'display:flex;gap:8px;align-items:center;font-size:12.5px;padding:4px 0' }, cb,
        h('span', { style: `width:12px;height:12px;border-radius:3px;background:rgb(${(p.color || [128, 128, 128]).join(',')})` }),
        h('span', { style: 'flex:1' }, p.name), h('span', { style: `font-family:${MONO};font-size:11px;color:var(--mut,#8A94A6)` }, `${(p.faces || 0).toLocaleString()} faces`));
    });
    return panel(header(`Parts · ${plist.length}`, ui.text('Visibility applies to the Parts tab of the viewer', { muted: true, small: true })), ...rows);
  }

  function ganttPanel(j) {
    const box = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });
    const update = job => {
      const stages = Object.entries(job.stages || {});
      // A requeued job (hub or mod restart) keeps its earlier stages' times: start at the earliest.
      const t0 = Math.min(job.started || job.created, ...stages.map(([, v]) => v.started || Infinity));
      const est = job.eta?.by_stage || {};
      const end = Math.max(Date.now() / 1000, ...stages.map(([, v]) => v.finished || 0), t0 + 1);
      const span = Math.max(1, (job.finished || end) - t0 + (job.status === 'running' ? job.eta?.own_s || 0 : 0));
      box.replaceChildren(...stages.map(([s, v]) => {
        const a = v.started ? (v.started - t0) / span : 0, b = v.finished ? (v.finished - t0) / span : v.started ? (Date.now() / 1000 - t0) / span : 0;
        const e = est[s] != null && v.started ? Math.min(1 - a, est[s] / span) : 0;
        return h('div', { style: 'display:grid;grid-template-columns:64px 1fr 70px;gap:8px;align-items:center;font-size:11.5px' },
          h('span', { style: 'color:var(--mut,#8A94A6)' }, STAGE_LABEL[s] || s),
          h('div', { style: 'position:relative;height:14px;border-radius:3px;background:var(--inset,#131926)' },
            e ? h('div', { title: `ETA ${fmtSecs(est[s])}`, style: `position:absolute;top:0;bottom:0;left:${a * 100}%;width:${e * 100}%;border:1px dashed var(--bds,#2A3547);border-radius:3px` }) : null,
            h('div', { title: v.note || v.sub || '', style: `position:absolute;top:2px;bottom:2px;left:${a * 100}%;width:${Math.max(0.4, (b - a) * 100)}%;border-radius:2px;background:${v.state === 'failed' ? 'var(--rd,#F85149)' : STAGE_COLOR[s]};opacity:${v.state === 'done' ? 1 : 0.7}` })),
          h('span', { style: `font-family:${MONO};text-align:right` }, v.seconds != null ? fmtSecs(v.seconds) : v.state === 'running' ? (v.total ? `${v.step || 0}/${v.total}` : v.sub || 'running') : v.state));
      }));
    };
    update(j);
    return { el: panel(header('Stages', ui.text('bars: actual · dashed: estimate', { muted: true, small: true })), box), update };
  }

  function actions(j) {
    const act = (label, fn, kind) => ui.button(label, async () => { try { await fn(); } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } }, { small: true, kind });
    const follow = async (stages, extra = {}) => {
      const parts = j.request?.parts?.parts?.length ? j.request.parts.parts : ['body'];
      const job = (await callRoom(ctx, 'POST', '/v1/jobs', { json: { parent_id: j.id, chat_id: j.chat_id, stages, parts: { ...(j.request?.parts || {}), parts }, rig: j.request?.rig || {}, ...extra } })).json;
      ctx.toast(`Queued “${job.title}”`, 'success'); jobs.set(job.id, job); select(job.id);
    };
    const btns = [];
    if (['queued', 'running'].includes(j.status)) btns.push(act('Cancel', async () => { if (await ctx.confirm({ title: 'Cancel this job?', body: 'A running job stops its GPU worker.', danger: true })) await ctx.call('POST', `/v1/jobs/${j.id}/cancel`); }, 'danger'));
    else {
      const files = j.files || [];
      if (files.includes('mesh.glb') && !files.includes('parts.glb')) btns.push(act('Split into parts', () => follow(['parts', 'preview'])));
      if (files.includes('parts.glb') && !files.includes('rigged.glb')) btns.push(act('Rig', () => follow(['rig', 'preview'])));
      if (files.includes('parts.glb')) btns.push(act('Re-split', () => follow(['parts', 'preview'], { parts: { ...(j.request?.parts || {}), seed: (j.request?.parts?.seed || 0) + 1 } })));
      btns.push(act('New seed', async () => { const r = (await callRoom(ctx, 'POST', `/v1/jobs/${j.id}/retry`, { json: { new_seed: true } })).json; jobs.set(r.id, r); select(r.id); }));
      if (files.length) btns.push(act('Download .zip', async () => {
        const r = await ctx.call('GET', `/v1/jobs/${j.id}/download`);
        const a = h('a', { href: r.url, download: `${(j.title || j.id).replace(/[^a-z0-9]+/gi, '-').slice(0, 40)}-${j.id}.zip` });
        document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(r.url), 60000);
      }));
      btns.push(act('Delete', async () => {
        if (!await ctx.confirm({ title: `Delete “${j.title}”?`, body: 'The job and all its files are deleted for good (the Outputs page copy goes too).', danger: true })) return;
        await ctx.call('DELETE', `/v1/jobs/${j.id}`); jobs.delete(j.id); selected = null; renderList(); renderDetail(true);
      }, 'danger'));
    }
    return h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, btns);
  }

  liveJobs(ctx, j => { jobs.set(j.id, j); renderList(); if (j.id === selected) renderDetail(false); },
    id => { jobs.delete(id); if (id === selected) selected = null; renderList(); renderDetail(true); }, cleanups);
  ctx.call('GET', '/v1/jobs', { query: { limit: 200 } }).then(r => {
    for (const j of r.json.jobs) jobs.set(j.id, j);
    if (!selected && r.json.jobs[0]) selected = r.json.jobs[0].id;
    renderList(); renderDetail(true);
  }).catch(e => list.replaceChildren(ui.badge(errText(e), 'red')));
}
