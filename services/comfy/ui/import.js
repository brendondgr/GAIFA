// Images & Video: the Import tab. Add a workflow (a file, or a past run from ComfyUI's history),
// then review it: the detected inputs (rename, drop, or expose another node's field), the task,
// the problems with their fixes (missing model downloads), and save it as a pack.
import { columns, header, panel, MONO, fmtBytes } from '/mod-kit.js';
import { TASK_LABEL, STATE_TONE, comfyLink, errText } from './page.js';

const LEVEL_TONE = { error: 'red', warning: 'accent', info: 'dim' };

export function importTab(el, ctx, cleanups) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const review = params.get('review');
  (review ? reviewView : addView)(el, ctx, cleanups, review);
}

// ------------------------------------------------------------------ add
function addView(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const file = h('input', { type: 'file', accept: '.json,.png,.webp,.mp4,.webm,.mkv,.zip', style: 'display:none', onchange: () => upload(file.files?.[0]) });
  const id = ui.input({ placeholder: 'optional: the new id (e.g. my-portraits)' });
  const status = h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' });
  const drop = h('div', {
    style: 'border:1px dashed var(--bds,#2A3547);border-radius:10px;padding:28px 16px;display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;cursor:pointer',
    onclick: () => file.click(),
    ondragover: e => { e.preventDefault(); drop.style.borderColor = 'var(--acct,#FFB224)'; },
    ondragleave: () => { drop.style.borderColor = ''; },
    ondrop: e => { e.preventDefault(); drop.style.borderColor = ''; upload(e.dataTransfer.files?.[0]); },
  }, h('strong', { style: 'font-size:13px' }, 'Drop a workflow here, or click to choose'),
  ui.text('A workflow JSON (from ComfyUI, either format), a PNG / WebP / MP4 that ComfyUI made, or a zip from Civitai with its extra files.', { small: true, muted: true }));
  const hist = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });
  const drafts = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });

  const left = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' },
    panel(header('Add a workflow', comfyLink(ctx)), drop, file, ui.field('Id', id, 'Lowercase letters, digits and -. Left empty, it comes from the file name.'), status),
    panel(header('From ComfyUI’s history', ui.button('Refresh', () => loadHistory(), { small: true, kind: 'ghost' })),
      ui.text('Ran something in ComfyUI’s own editor? Pick it here: the exact graph it ran is imported.', { small: true, muted: true }), hist));
  const right = panel(header('Drafts to review'), ui.text('Workflows saved in ComfyUI under a new name, and imports not saved yet.', { small: true, muted: true }), drafts);
  const cols = columns(left, right, 380);
  cleanups.push(cols.cleanup);
  el.append(cols);

  async function upload(f) {
    if (!f) return;
    status.textContent = `Importing ${f.name}…`;
    const fd = new FormData();
    fd.append('file', f, f.name);
    if (id.value.trim()) fd.append('id', id.value.trim());
    try {
      const r = (await ctx.call('POST', '/v1/import', { form: fd })).json;
      ctx.toast(`Imported as ${r.id}`, 'success');
      ctx.navigate(`#/s/comfy/import?review=${r.id}`);
    } catch (e) { status.textContent = errText(e); }
    file.value = '';
  }

  async function loadHistory() {
    hist.replaceChildren(ui.text('Loading…', { small: true, muted: true }));
    try {
      const items = (await ctx.call('GET', '/v1/import/history')).json.items;
      hist.replaceChildren(...(items.length ? items.slice(0, 15).map(it => h('div', { style: 'display:flex;gap:8px;align-items:center;border:1px solid var(--bd,#1D2430);border-radius:7px;padding:7px 9px' },
        h('div', { style: 'flex:1;min-width:0' },
          h('div', { style: 'font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, it.files[0] || `${it.nodes} nodes`),
          h('div', { style: `font-size:11px;color:var(--mut,#8A94A6);font-family:${MONO};overflow:hidden;text-overflow:ellipsis;white-space:nowrap`, title: it.types.join(', ') },
            `#${it.number} · ${it.nodes} nodes${it.from_aihub ? ` · from ${it.from_aihub}` : ''}${it.status && it.status !== 'success' ? ` · ${it.status}` : ''}`)),
        ui.button('Import', async () => {
          try {
            const r = (await ctx.call('POST', `/v1/import/history/${it.prompt_id}`, { json: {} })).json;
            ctx.navigate(`#/s/comfy/import?review=${r.id}`);
          } catch (e) { ctx.toast(errText(e), 'error'); }
        }, { small: true }))) : [ui.text('Nothing in ComfyUI’s history.', { small: true, muted: true })]));
    } catch (e) { hist.replaceChildren(ui.text(errText(e), { small: true, muted: true })); }
  }

  async function loadDrafts() {
    try {
      const ws = (await ctx.call('GET', '/v1/workflows')).json.workflows.filter(w => w.state !== 'ready');
      drafts.replaceChildren(...(ws.length ? ws.map(w => h('div', { style: 'display:flex;gap:8px;align-items:center' },
        ui.badge(w.state, STATE_TONE[w.state]),
        h('span', { style: 'flex:1;min-width:0;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap', title: w.id }, w.name),
        ui.button(w.state === 'draft' ? 'Review' : 'Fix', () => ctx.navigate(`#/s/comfy/import?review=${w.id}`), { small: true }))) : [ui.text('None.', { small: true, muted: true })]));
    } catch (e) { drafts.replaceChildren(ui.text(errText(e), { small: true })); }
  }

  loadHistory();
  loadDrafts();
}

// ------------------------------------------------------------------ review
function reviewView(el, ctx, cleanups, id) {
  const { ui } = ctx, h = ui.h;
  let detail = null, tasks = {}, rows = [], outputs = {}, extra = {};
  const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px' }, ui.text('Loading…', { muted: true }));
  el.append(body);

  async function load() {
    try {
      [detail, tasks] = await Promise.all([ctx.call('GET', `/v1/workflows/${id}`).then(r => r.json), ctx.call('GET', '/v1/tasks').then(r => r.json.tasks)]);
    } catch (e) { body.replaceChildren(ui.empty(`No workflow ${id}`, errText(e), ui.button('Back', () => ctx.navigate('#/s/comfy/import')))); return; }
    let manifest;
    if (detail.state === 'draft' || !Object.keys(detail.inputs || {}).length) {
      try { manifest = (await ctx.call('GET', `/v1/workflows/${id}/suggest`)).json.manifest; } catch { manifest = { name: detail.name, task: 'custom', inputs: {}, outputs: {} }; }
    } else {
      manifest = { name: detail.name, task: detail.task, description: detail.description, inputs: detail.inputs, outputs: detail.outputs, presets: detail.presets, memory_gb: detail.memory_gb, set: detail.set, tags: detail.tags };
    }
    rows = Object.entries(manifest.inputs || {}).map(([name, m]) => ({ keep: true, name, ...m }));
    outputs = manifest.outputs || {};
    extra = { presets: manifest.presets, memory_gb: manifest.memory_gb, tags: manifest.tags, set: manifest.set };
    draw(manifest);
  }

  function draw(m) {
    const name = ui.input({ value: m.name || '' });
    const desc = ui.input({ value: m.description || '', placeholder: 'One line: what it makes (the agent reads this)' });
    const task = ui.select(Object.keys(tasks).map(k => ({ value: k, label: tasks[k].name })), { value: m.task });
    const taskNote = h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' });
    const needs = () => { const t = tasks[task.value]; taskNote.textContent = t?.required?.length ? `needs inputs named: ${t.required.join(', ')}` : ''; };
    task.onchange = needs;
    needs();
    const tbody = h('tbody');
    const nodeById = Object.fromEntries((detail.nodes || []).map(n => [n.id, n]));
    const cell = 'padding:5px 8px;border-bottom:1px solid var(--bd,#1D2430);font-size:12px;text-align:left;vertical-align:middle';
    const drawRows = () => tbody.replaceChildren(...rows.map((r, i) => {
      const n = nodeById[r.node] || (detail.nodes || []).find(x => x.title === r.title);
      const keep = h('input', { type: 'checkbox', checked: r.keep, onchange: () => { r.keep = keep.checked; } });
      const nm = ui.input({ value: r.name });
      nm.style.height = '28px';
      nm.oninput = () => { r.name = nm.value.trim(); };
      const val = n?.fields?.[r.field];
      return h('tr', {}, h('td', { style: cell }, keep), h('td', { style: cell }, nm),
        h('td', { style: cell }, h('div', {}, n ? n.title : `node ${r.node || r.title}`),
          h('div', { style: `font-family:${MONO};font-size:11px;color:var(--mut,#8A94A6)` }, `${r.node || r.title}.${r.field}${r.also?.length ? ` +${r.also.length}` : ''}`)),
        h('td', { style: cell + `;font-family:${MONO};font-size:11px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`, title: String(val ?? '') }, val == null ? '' : String(val)),
        h('td', { style: cell }, ui.button('×', () => { rows.splice(i, 1); drawRows(); }, { small: true, kind: 'ghost' })));
    }));
    drawRows();

    // expose another node's field
    const nodeSel = ui.select([{ value: '', label: 'Expose another field…' }, ...(detail.nodes || []).filter(n => Object.keys(n.fields).length)
      .map(n => ({ value: n.id, label: `${n.title} (${n.id})` }))]);
    const fieldSel = ui.select([]);
    const newName = ui.input({ placeholder: 'input name' });
    nodeSel.onchange = () => { const n = nodeById[nodeSel.value]; fieldSel.replaceChildren(...Object.keys(n?.fields || {}).map(f => h('option', { value: f }, f))); };
    const add = ui.button('Add', () => {
      const nm = newName.value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_');
      if (!nodeSel.value || !fieldSel.value || !nm) { ctx.toast('Pick a node, a field and a name', 'error'); return; }
      rows.push({ keep: true, name: nm, node: nodeSel.value, field: fieldSel.value });
      newName.value = '';
      drawRows();
    }, { small: true });

    // problems
    const issues = (detail.issues_list || []).map(i => h('div', { style: 'display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--bd,#1D2430)' },
      ui.badge(i.level, LEVEL_TONE[i.level]),
      h('div', { style: 'flex:1;min-width:0;display:flex;flex-direction:column;gap:3px' },
        h('span', { style: 'font-size:12.5px' }, i.detail + (i.node ? ` (node ${i.node})` : '')),
        i.fix ? h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, i.fix) : null),
      i.code === 'missing_model' && i.data?.url ? downloadButton(ctx, i.data) : null));

    const toml = ui.textarea({ rows: 16 });
    toml.style.fontFamily = MONO;
    toml.style.fontSize = '12px';
    const tomlBox = h('details', {}, h('summary', { style: 'cursor:pointer;font-size:12px;color:var(--mut,#8A94A6)' }, 'Edit as TOML instead (saved as written, comments kept; saving the form above rewrites the file without comments)'), toml);
    tomlBox.ontoggle = async () => {
      if (tomlBox.open && !toml.value) {
        try { toml.value = (await ctx.call('GET', `/v1/workflows/${id}/suggest`)).json.toml; } catch { /* empty */ }
      }
    };
    const save = ui.button(detail.state === 'draft' ? 'Save as a workflow' : 'Save', async () => {
      const inputs = {};
      for (const r of rows.filter(r => r.keep && r.name)) {
        const { keep, name: n, ...rest } = r;
        inputs[n] = Object.fromEntries(Object.entries(rest).filter(([, v]) => v != null && !(Array.isArray(v) && !v.length)));
      }
      const manifest = { name: name.value.trim(), task: task.value, description: desc.value.trim(), inputs, outputs,
        ...(extra.presets && Object.keys(extra.presets).length ? { presets: extra.presets } : {}), ...(extra.set ? { set: extra.set } : {}),
        ...(extra.tags?.length ? { tags: extra.tags } : {}), ...(extra.memory_gb && detail.state !== 'draft' ? { memory_gb: extra.memory_gb } : {}) };
      const bodyJson = tomlBox.open && toml.value.trim() ? { toml: toml.value } : { manifest };
      try {
        const r = (await ctx.call('PUT', `/v1/workflows/${id}`, { json: bodyJson })).json;
        ctx.toast(r.state === 'ready' ? `${r.name} is ready` : `Saved; ${r.issues.errors} problem(s) left`, r.state === 'ready' ? 'success' : 'info');
        if (r.state === 'ready') ctx.navigate(`#/s/comfy/run?wf=${r.id}`);
        else { detail = r; load(); }
      } catch (e) { ctx.toast(errText(e), 'error'); }
    }, { kind: 'primary' });
    const del = ui.button('Remove', async () => {
      if (!await ctx.confirm({ title: `Remove ${detail.name}?`, body: 'Its folder moves to services/comfy/workflows/.trash/.', danger: true })) return;
      try { await ctx.call('DELETE', `/v1/workflows/${id}`); ctx.navigate('#/s/comfy/workflows'); } catch (e) { ctx.toast(errText(e), 'error'); }
    }, { kind: 'danger', small: true });

    body.replaceChildren(
      panel(header(`Review: ${detail.name}`, ui.badge(detail.state, STATE_TONE[detail.state]), comfyLink(ctx, 'Open in ComfyUI ↗'),
        ui.button('Back', () => ctx.navigate('#/s/comfy/import'), { small: true, kind: 'ghost' })),
      ui.text(`In ComfyUI’s workflow browser this is ${id}.json once saved. Edits saved there come back here by themselves.`, { small: true, muted: true }),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, ui.field('Name', name), ui.field('Task', task, null), ui.field('Description', desc)), taskNote),
      panel(header('Inputs', ui.text('Unticked rows are left out. Names from the shared list (prompt, image, seed, width…) let it stand in for other workflows of its task.', { small: true, muted: true })),
        h('div', { style: 'overflow:auto' }, h('table', { style: 'border-collapse:collapse;width:100%' },
          h('thead', h('tr', ['', 'Name', 'Node and field', 'Current value', ''].map(c => h('th', { style: cell + ';color:var(--mut,#8A94A6);font-weight:500' }, c)))), tbody)),
        h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' }, nodeSel, fieldSel, newName, add),
        h('div', { style: 'font-size:12px;color:var(--mut,#8A94A6)' }, 'Outputs: ' + (Object.entries(outputs).map(([k, o]) => `${k} (node ${o.node || o.title}, ${o.kind || 'file'})`).join(', ') || 'none found'))),
      panel(header(`Problems (${(detail.issues_list || []).filter(i => i.level !== 'info').length})`), ...(issues.length ? issues : [ui.text('None.', { small: true, muted: true })])),
      panel(tomlBox, h('div', { style: 'display:flex;gap:8px;align-items:center' }, save, h('span', { style: 'flex:1' }), del)));
  }

  load();
}

function downloadButton(ctx, data) {
  const { ui } = ctx;
  const host = (() => { try { return new URL(data.url).host; } catch { return 'the web'; } })();
  const b = ui.button('Download', async () => {
    const ok = await ctx.confirm({ title: `Download ${data.file}?`, body: `From ${host} into data/models/comfyui/${data.directory}/. It's registered on the Models page when done.` });
    if (!ok) return;
    try {
      const d = (await ctx.call('POST', '/v1/downloads', { json: { url: data.url, folder: data.directory, name: data.file.split('/').pop() } })).json;
      b.disabled = true;
      const t = setInterval(async () => {
        try {
          const all = (await ctx.call('GET', '/v1/downloads')).json.downloads;
          const x = all.find(y => y.id === d.id);
          if (!x) return;
          b.textContent = x.state === 'running' ? (x.total ? `${Math.round(100 * x.bytes / x.total)}%` : fmtBytes(x.bytes)) : x.state;
          if (x.state === 'done' || x.state === 'failed') { clearInterval(t); if (x.state === 'failed') ctx.toast(x.error || 'Download failed', 'error'); }
        } catch { clearInterval(t); }
      }, 1500);
    } catch (e) { ctx.toast(errText(e), 'error'); }
  }, { small: true });
  return b;
}

