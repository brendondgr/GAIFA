// A form built from a JSON Schema, for mod page modules: strings (a text area when x-multiline),
// numbers with their range, booleans, enums, and files (format "aihub-file": upload one, or pick a
// recent AIHub output; `x-kind: "video"` on a property offers videos). Written by us, not Claude Design.
// Import as '/mod-form.js'.
//
//   const form = schemaForm(ctx, schema, { values, upload: file => ctx.call('POST', '/v1/uploads', …) });
//   el.append(form);  form.values() → {name: value}  form.set({name: value})  form.onchange = fn

import { h } from './mod-ui.js';

const MONO = "'JetBrains Mono',ui-monospace,monospace";
const isFile = p => p && (p.format === 'aihub-file' || (p.type === 'array' && p.items?.format === 'aihub-file'));

/** ctx: the page ctx. schema: {properties, required}. o: { values, upload(file) → Promise<value>,
 *  kinds: output kinds offered for files (default ['image']), order: property names first in this order,
 *  advanced: names shown under "More settings" }. */
export function schemaForm(ctx, schema, o = {}) {
  const { ui } = ctx;
  const props = schema.properties || {};
  const required = new Set(schema.required || []);
  const fields = {};
  const names = Object.keys(props).sort((a, b) => rank(a, o.order) - rank(b, o.order));
  const main = h('div', { style: 'display:flex;flex-wrap:wrap;gap:10px 12px' });
  const more = h('div', { style: 'display:flex;flex-wrap:wrap;gap:10px 12px' });
  const moreBox = h('details', { style: 'border-top:1px solid var(--bd,#1D2430);padding-top:8px' },
    h('summary', { style: 'cursor:pointer;font-size:12px;color:var(--mut,#8A94A6)' }, 'More settings'), more);
  const el = h('div', { style: 'display:flex;flex-direction:column;gap:10px;min-width:0' }, main);
  const changed = () => el.onchange?.(el.values());

  for (const name of names) {
    const p = props[name];
    const label = (p.title || name) + (required.has(name) ? ' *' : '');
    const f = isFile(p) ? fileField(ctx, name, p, o, changed) : control(ui, p, changed);
    fields[name] = f;
    const wide = isFile(p) || p['x-multiline'];
    const wrap = ui.field(label, f.el, p.description && !wide ? p.description : null);
    wrap.style.flex = wide ? '1 1 100%' : '1 1 150px';
    if (wide && p.description) wrap.title = p.description;
    ((o.advanced || []).includes(name) ? more : main).append(wrap);
  }
  if (more.children.length) el.append(moreBox);

  el.values = () => {
    const out = {};
    for (const [k, f] of Object.entries(fields)) {
      const v = f.get();
      if (v !== undefined && v !== '' && v !== null) out[k] = v;
    }
    return out;
  };
  el.set = vals => { for (const [k, v] of Object.entries(vals || {})) fields[k]?.set(v); changed(); };
  el.set(o.values || {});
  el.focusFirst = () => { const f = Object.values(fields)[0]; f?.el.querySelector?.('textarea,input,select')?.focus?.() ?? f?.el.focus?.(); };
  return el;
}

function rank(name, order = []) {
  const i = order.indexOf(name);
  return i < 0 ? 1000 : i;
}

function control(ui, p, changed) {
  const t = p.type;
  if (p.enum) {
    const s = ui.select([{ value: '', label: p.default != null ? `default (${p.default})` : '—' }, ...p.enum.map(v => ({ value: String(v), label: String(v) }))],
      { onchange: changed });
    return { el: s, get: () => s.value === '' ? undefined : cast(p, s.value), set: v => { s.value = v == null ? '' : String(v); } };
  }
  if (t === 'boolean') {
    const c = h('input', { type: 'checkbox', onchange: changed });
    const el = h('span', { style: 'display:flex;align-items:center;height:32px' }, c);
    return { el, get: () => c.checked, set: v => { c.checked = !!v; } };
  }
  if (t === 'string' && p['x-multiline']) {
    const a = ui.textarea({ rows: 3, oninput: changed, placeholder: p.default ? String(p.default).slice(0, 120) : '' });
    return { el: a, get: () => a.value || undefined, set: v => { a.value = v ?? ''; } };
  }
  const i = ui.input({ type: t === 'integer' || t === 'number' ? 'number' : 'text', oninput: changed,
    placeholder: p.default != null ? String(p.default) : '' });
  if (p.minimum != null) i.min = p.minimum;
  if (p.maximum != null) i.max = p.maximum;
  if (p['x-step']) i.step = p['x-step'];
  else if (t === 'number') i.step = 'any';
  if (t === 'integer' || t === 'number') i.style.fontFamily = MONO;
  return { el: i, get: () => (i.value === '' ? undefined : cast(p, i.value)), set: v => { i.value = v ?? ''; } };
}

function cast(p, v) {
  if (p.type === 'integer') return parseInt(v, 10);
  if (p.type === 'number') return parseFloat(v);
  return v;
}

/** A file input: shows the chosen file, with Upload and "Recent outputs". Values: "upload:<name>",
 *  "output:<id>", or a name already known to the mod. */
function fileField(ctx, name, p, o, changed) {
  const { ui } = ctx;
  o = p['x-kind'] ? { ...o, kinds: [p['x-kind']] } : o;          // a video input offers videos
  let value = null;
  const thumb = h('div', { style: 'width:72px;height:72px;border-radius:7px;background:var(--inset,#131926) center/cover no-repeat;border:1px solid var(--bd,#1D2430);flex:none' });
  const label = h('span', { style: `font-size:12px;font-family:${MONO};color:var(--mut,#8A94A6);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px` }, 'none');
  const picker = h('input', { type: 'file', accept: (o.kinds || ['image']).map(k => `${k}/*`).join(','), style: 'display:none',
    onchange: async () => {
      const f = picker.files?.[0];
      if (!f || !o.upload) return;
      label.textContent = `uploading ${f.name}…`;
      try {
        const v = await o.upload(f);
        set(v, URL.createObjectURL(f), f.name);
        changed();
      } catch (e) { label.textContent = e.detail || e.message || 'upload failed'; }
      picker.value = '';
    } });
  const grid = h('div', { style: 'display:none;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:6px;max-height:220px;overflow:auto;padding:6px;border:1px solid var(--bd,#1D2430);border-radius:8px;background:var(--inset,#131926)' });
  const recent = ui.button('Recent outputs', async () => {
    if (grid.style.display === 'grid') { grid.style.display = 'none'; return; }
    grid.replaceChildren(ui.text('Loading…', { small: true, muted: true }));
    grid.style.display = 'grid';
    try {
      const kinds = o.kinds || ['image'];
      const pages = await Promise.all(kinds.map(k => ctx.api.listOutputs({ kind: k, limit: 30 })));
      const items = pages.flatMap(pg => pg.items || []).sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0)).slice(0, 40);
      grid.replaceChildren(...(items.length ? items.map(it => h('button', {
        type: 'button', title: it.title, onclick: () => { set(`output:${it.id}`, it.preview || it.url, it.title); grid.style.display = 'none'; changed(); },
        style: `aspect-ratio:1;border-radius:6px;border:1px solid var(--bd,#1D2430);cursor:pointer;background:var(--card,#11151D) url("${it.preview || it.url || ''}") center/cover no-repeat`,
      })) : [ui.text('No outputs yet.', { small: true, muted: true })]));
    } catch (e) { grid.replaceChildren(ui.text(e.detail || 'Could not list outputs', { small: true, muted: true })); }
  }, { small: true });
  const clear = ui.button('Clear', () => { set(null); changed(); }, { small: true, kind: 'ghost' });
  function set(v, img, text) {
    value = v || null;
    thumb.style.backgroundImage = img ? `url("${img}")` : '';
    label.textContent = value ? (text || value) : 'none';
    label.title = value || '';
  }
  const el = h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
    h('div', { style: 'display:flex;gap:10px;align-items:center;min-width:0' }, thumb,
      h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' }, label,
        h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, o.upload ? ui.button('Upload…', () => picker.click(), { small: true }) : null, recent, clear))),
    grid, picker);
  return {
    el, get: () => (p.type === 'array' ? (value ? [value] : undefined) : value || undefined),
    set: v => {
      const one = Array.isArray(v) ? v[0] : v;
      if (!one) return set(null);
      const id = String(one).startsWith('output:') ? String(one).slice(7) : null;
      set(one, id ? `/api/outputs/${id}/preview` : null, id ? null : String(one));
    },
  };
}
