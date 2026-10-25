// Images & Video (comfy) page inside GAIFA (design brief Part B5, plan 11.11): Workflows, Run and
// Import tabs. Workflows are packs (services/comfy/workflows/<id>/); see docs/workflows.md.
// Everything goes through ctx.call (GAIFA's proxy), so it also works under ?mock.
import { chartCard, charts, rh } from '/mod-charts.js';
import { requireRunning, header, panel, segmented, store } from '/mod-kit.js';
import { runTab } from './run.js';
import { importTab } from './import.js';

export const STATE_TONE = { ready: 'green', broken: 'red', draft: 'accent' };
export const TASK_LABEL = {
  'text-to-image': 'Text to image', 'image-edit': 'Image edit', 'image-to-video': 'Image to video',
  'text-to-video': 'Text to video', upscale: 'Upscale', 'remove-background': 'Remove background', custom: 'Custom',
};
export const errText = e => e?.detail || e?.message || 'Request failed';
export const NATIVE = 'http://127.0.0.1:8199/';

export default {
  tabs: [
    { id: 'workflows', label: 'Workflows', icon: 'layers' },
    { id: 'run', label: 'Run', icon: 'play' },
    { id: 'import', label: 'Import', icon: 'plus' },
  ],
  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'Images & Video')) return;
    const cleanups = [];
    ({ run: runTab, import: importTab }[ctx.tab] || workflowsTab)(el, ctx, cleanups);
    return () => cleanups.forEach(f => { try { f(); } catch { /* gone */ } });
  },
};

/** "Open ComfyUI ↗": ComfyUI's own editor (each pack is <id>.json in its workflow browser). */
export function comfyLink(ctx, text = 'Open ComfyUI ↗') {
  const url = ctx.service.native_ui || NATIVE;
  return ctx.ui.h('a', { href: url, target: '_blank', rel: 'noopener', style: 'font-size:12px;color:var(--acct,#FFB224);text-decoration:none;white-space:nowrap' }, text);
}

/** The pack's preview image as a blob URL (or null). */
export async function previewUrl(ctx, w) {
  if (!w.preview) return null;
  try { return (await ctx.call('GET', `/v1/workflows/${w.id}/preview`)).url; } catch { return null; }
}

// ------------------------------------------------------------------ Workflows
function workflowsTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  let filter = store.get('comfy.filter', 'all');
  let data = { workflows: [], defaults: {} };
  const grid = h('div', { style: 'display:flex;flex-direction:column;gap:16px' });
  const counts = h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' });
  const seg = segmented([{ value: 'all', label: 'All' }, { value: 'ready', label: 'Ready' }, { value: 'attention', label: 'Needs attention' }, { value: 'draft', label: 'Drafts' }],
    filter, v => { filter = v; store.set('comfy.filter', v); draw(); }, 'Filter');
  const top = panel(
    header('Workflows', counts, seg, ui.button('Import…', () => ctx.navigate('#/s/comfy/import'), { small: true }), comfyLink(ctx)),
    ui.text('Each workflow is a pack: a folder in services/comfy/workflows/ with the ComfyUI graph and a workflow.toml naming its task and inputs. Adding, editing or removing a folder shows up here by itself.', { muted: true, small: true }),
  );
  const chart = chartCard({
    title: 'Images & videos per day', ranges: ['7d', '30d'], height: 130,
    load: range => ctx.call('GET', '/v1/hub/widgets/made', { query: { range } }).then(r => r.json),
    draw: (d, o) => rh(charts.BarChart, { categories: d.categories, series: d.series, stacked: true, unit: 'files', ...o }),
  });
  cleanups.push(() => chart.unmount());
  el.append(h('div', { style: 'display:flex;flex-direction:column;gap:12px' }, top, grid, chart));

  async function load() {
    try { data = (await ctx.call('GET', '/v1/workflows')).json; draw(); }
    catch (e) { grid.replaceChildren(ui.empty('Could not list workflows', errText(e))); }
  }

  function draw() {
    const ws = data.workflows.filter(w => filter === 'all' || (filter === 'attention' ? w.state === 'broken' : w.state === filter));
    const n = s => data.workflows.filter(w => w.state === s).length;
    counts.textContent = `${n('ready')} ready · ${n('broken')} need attention · ${n('draft')} drafts`;
    if (!data.workflows.length) {
      grid.replaceChildren(ui.empty('No workflows yet', 'Import one (a workflow JSON, an image or video ComfyUI made, or a zip), or save one in ComfyUI.',
        ui.button('Import a workflow', () => ctx.navigate('#/s/comfy/import'), { kind: 'primary' })));
      return;
    }
    const byTask = {};
    ws.forEach(w => (byTask[w.task] ||= []).push(w));
    grid.replaceChildren(...Object.keys(TASK_LABEL).filter(t => byTask[t]).map(t => h('section', { style: 'display:flex;flex-direction:column;gap:8px' },
      h('h3', { style: 'margin:0;font-size:12px;font-weight:600;color:var(--mut,#8A94A6);text-transform:uppercase;letter-spacing:.06em' }, TASK_LABEL[t] || t),
      h('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px' }, ...byTask[t].map(card)))));
    if (!ws.length) grid.replaceChildren(ui.text('Nothing in this filter.', { muted: true }));
  }

  function card(w) {
    const isDefault = data.defaults[w.task] === w.id;
    const img = h('div', { style: 'height:120px;border-radius:7px;background:var(--inset,#131926) center/cover no-repeat;display:flex;align-items:center;justify-content:center;color:var(--mut,#8A94A6);font-size:11px' },
      w.preview ? '' : (w.task.includes('video') ? 'video' : 'image'));
    previewUrl(ctx, w).then(u => { if (u) { img.style.backgroundImage = `url("${u}")`; img.textContent = ''; } });
    const star = h('button', {
      type: 'button', title: isDefault ? `Default for ${TASK_LABEL[w.task] || w.task}` : 'Make this the default for its task',
      disabled: w.state !== 'ready' || w.task === 'custom', 'aria-pressed': String(isDefault),
      style: `border:0;background:transparent;cursor:pointer;font-size:16px;line-height:1;color:${isDefault ? 'var(--acct,#FFB224)' : 'var(--mut,#8A94A6)'}`,
      onclick: async () => {
        try { data.defaults = (await ctx.call('PUT', '/v1/defaults', { json: { defaults: { [w.task]: isDefault ? null : w.id } } })).json.defaults; draw(); }
        catch (e) { ctx.toast(errText(e), 'error'); }
      },
    }, isDefault ? '★' : '☆');
    const issues = w.issues.errors || w.issues.warnings
      ? `${w.issues.errors ? `${w.issues.errors} problem${w.issues.errors > 1 ? 's' : ''}` : ''}${w.issues.errors && w.issues.warnings ? ' · ' : ''}${w.issues.warnings ? `${w.issues.warnings} warning${w.issues.warnings > 1 ? 's' : ''}` : ''}` : '';
    const go = w.state === 'ready' ? ui.button('Run', () => ctx.navigate(`#/s/comfy/run?wf=${w.id}`), { small: true, kind: 'primary' })
      : ui.button(w.state === 'draft' ? 'Review' : 'Fix', () => ctx.navigate(`#/s/comfy/import?review=${w.id}`), { small: true });
    return h('article', { style: 'background:var(--card,#11151D);border:1px solid var(--bd,#1D2430);border-radius:9px;padding:10px;display:flex;flex-direction:column;gap:8px;min-width:0' },
      img,
      h('div', { style: 'display:flex;gap:6px;align-items:flex-start' },
        h('div', { style: 'flex:1;min-width:0' },
          h('div', { style: 'font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap', title: w.name }, w.name),
          h('div', { style: "font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;color:var(--mut,#8A94A6)" }, w.id + (w.loose ? ' · saved in ComfyUI' : ''))),
        star),
      w.description && w.description !== w.name ? ui.text(w.description, { small: true, muted: true }) : null,
      h('div', { style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap' }, ui.badge(w.state, STATE_TONE[w.state]),
        issues ? h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, issues) : null,
        h('span', { style: 'flex:1' }), w.state === 'ready' ? ui.button('Edit', () => ctx.navigate(`#/s/comfy/import?review=${w.id}`), { small: true, kind: 'ghost' }) : null, go));
  }

  load();
  const t = setInterval(load, 5000);
  cleanups.push(() => clearInterval(t));
}
