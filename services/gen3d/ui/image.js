// The image engines on the Create tab (plan 17.9): the picture, the engine's presets and every setting,
// built from GET /v1/options' `engines`. A picture is a GAIFA output (`output:<id>`): an upload becomes
// one first (POST /api/outputs/upload), so gen3d always fetches it from the hub.
import { segmented } from '/mod-kit.js';
import { schemaForm } from '/mod-form.js';

export const ENGINE_OPTIONS = [
  { value: 'cube3d', label: 'Cube3D', pick: 'Cube3D: text → mesh, parts, rig' },
  { value: 'hunyuan21', label: 'Hunyuan3D 2.1', pick: 'Hunyuan3D 2.1: picture → mesh (characters)' },
  { value: 'trellis2', label: 'TRELLIS.2', pick: 'TRELLIS.2: picture → mesh (detailed objects)' },
  { value: 'sam3d_objects', label: 'SAM 3D Objects', pick: 'SAM 3D Objects: picture → mesh (quickest)' },
  { value: 'sam3d_body', label: 'SAM 3D Body', pick: 'SAM 3D Body: picture of a person → rigged body' },
];
const FACES = [[0, 'Raw'], [200000, '200k'], [100000, '100k'], [50000, '50k']];

/** A catalogue entry → the JSON Schema schemaForm renders: the picture first, then the engine's settings. */
export function engineSchema(engine) {
  const props = { image: { type: 'string', format: 'gaifa-file', 'x-kind': 'image', title: 'Picture',
    description: 'One object or person; a transparent or plain white background works best' } };
  for (const f of engine.fields || []) {
    const p = { title: f.label, description: f.help, default: f.default };
    if (f.type === 'choice') { p.type = typeof f.choices[0] === 'number' ? 'integer' : 'string'; p.enum = f.choices; }
    else p.type = f.type;
    if (f.min != null) p.minimum = f.min;
    if (f.max != null) p.maximum = f.max;
    if (f.step) p['x-step'] = f.step;
    props[f.key] = p;
  }
  return { properties: props, required: ['image'] };
}

/** The image panel for one engine. Returns { el, body(), ready() }: body() is the JobRequest part. */
export function imagePanel(ctx, engine, saved, onChange) {
  const { ui } = ctx, h = ui.h;
  const presets = engine.presets || {};
  let preset = saved.preset && presets[saved.preset] ? saved.preset : engine.default_preset || 'fast';
  const note = ui.text('', { muted: true, small: true });
  const fields = engine.fields || [];
  const advanced = fields.map(f => f.key).filter(k => !['target_faces', 'resolution', 'octree'].includes(k));
  const form = schemaForm(ctx, engineSchema(engine), {
    values: saved.values || {}, order: ['image', 'target_faces', 'resolution', 'octree'], advanced,
    upload: async file => `output:${(await ctx.api.uploadOutput(file)).id}`,
  });
  form.onchange = () => onChange();
  const presetBar = segmented(Object.entries(presets).map(([k, v]) => ({ value: k, label: v.label })), preset, v => {
    preset = v; applyPreset(); onChange();
  }, 'Preset');

  function applyPreset() {
    const vals = presets[preset]?.values || {};
    note.textContent = presets[preset]?.help || '';
    form.set(Object.fromEntries(fields.map(f => [f.key, vals[f.key] ?? f.default])));
  }
  const hasFaces = fields.some(f => f.key === 'target_faces');
  const faces = hasFaces ? h('div', { style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap' },
    h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' }, 'Face budget'),
    FACES.map(([n, label]) => ui.button(label, () => { form.set({ target_faces: n }); }, { small: true })),
    ui.text(engine.id === 'trellis2' ? 'TRELLIS.2 remeshes, then decimates (clean down to 50k); the raw mesh is kept too.'
      : 'Decimated after the mesh is made; the raw mesh is kept too.', { muted: true, small: true })) : null;
  const where = engine.runs_in === 'comfy' ? ' Runs in Images & Video (ComfyUI).' : '';
  const el = h('div', { style: 'display:flex;flex-direction:column;gap:10px' },
    h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, presetBar, note),
    ui.text(`${engine.help}.${where} Licence: ${engine.license}.`, { muted: true, small: true }),
    engine.missing?.length ? ui.badge(`Not installed: ${engine.missing.join(', ')}`, 'red') : null,
    form, faces);
  applyPreset();
  if (saved.values) form.set(saved.values);

  return {
    el,
    state: () => ({ preset, values: Object.fromEntries(Object.entries(form.values()).filter(([k]) => k !== 'image')) }),
    ready: () => !!form.values().image,
    body: () => {
      const v = form.values();
      const { image, ...opts } = v;
      return { engine: engine.id, image: image || null, preset, [engine.id]: opts };
    },
  };
}
