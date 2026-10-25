// The comfy mod's API on the mock (plan 11.11): workflow packs (ready, needing attention, a draft),
// runs with progress and rendered results, imports and the review screen, downloads, charts.
// Written by us, not Claude Design. `m` is mock.js's toolbox.

const TXT = {
  prompt: { type: 'string', title: 'Prompt', 'x-multiline': true, description: 'What to make, in plain words' },
  negative: { type: 'string', title: 'Negative', 'x-multiline': true, description: 'What to avoid', default: 'low quality, blurry' },
  seed: { type: 'integer', title: 'Seed', minimum: -1, default: -1, description: 'Random seed; -1 picks one' },
  steps: { type: 'integer', title: 'Steps', minimum: 1, maximum: 100, default: 8, description: 'Sampling steps' },
  cfg: { type: 'number', title: 'Cfg', minimum: 0, maximum: 100, default: 1, description: 'Prompt guidance (CFG)' },
  width: { type: 'integer', title: 'Width', minimum: 16, maximum: 4096, default: 1024, description: 'Width in pixels' },
  height: { type: 'integer', title: 'Height', minimum: 16, maximum: 4096, default: 1024, description: 'Height in pixels' },
  aspect: { type: 'string', title: 'Aspect', enum: ['1:1', '4:3', '3:4', '3:2', '2:3', '16:9', '9:16', '21:9'], description: 'Aspect ratio (sets width and height)' },
  megapixels: { type: 'number', title: 'Megapixels', minimum: 0.1, maximum: 4, default: 1, description: 'Image size, used with aspect' },
  image: { type: 'string', format: 'gaifa-file', title: 'Image', description: 'A GAIFA output id, an upload, or a file path' },
  frames: { type: 'integer', title: 'Frames', minimum: 1, maximum: 161, default: 81, description: 'Number of video frames' },
  fps: { type: 'integer', title: 'Fps', minimum: 1, maximum: 60, default: 16, description: 'Frames per second' },
  seconds: { type: 'number', title: 'Seconds', minimum: 0.5, maximum: 30, description: 'Video length in seconds (sets frames)' },
};
const pick = (...k) => Object.fromEntries(k.map(n => [n, TXT[n]]));
const TASKS = {
  'text-to-image': { name: 'Text to image', tool: 'generate_image', required: ['prompt'], output: 'image', description: 'Make an image from a text description.' },
  'image-edit': { name: 'Image edit', tool: 'edit_image', required: ['image', 'prompt'], output: 'image', description: 'Change an existing image as the prompt instructs.' },
  'image-to-video': { name: 'Image to video', tool: 'animate_image', required: ['image', 'prompt'], output: 'video', description: 'Animate a still image into a short video.' },
  'text-to-video': { name: 'Text to video', tool: 'generate_video', required: ['prompt'], output: 'video', description: 'Make a short video from a text description.' },
  upscale: { name: 'Upscale', tool: 'upscale_image', required: ['image'], output: 'image', description: 'Make an image larger and sharper.' },
  custom: { name: 'Custom', tool: null, required: [], output: null, description: 'Anything else.' },
};
const NODES_ZIT = [
  { id: '62', type: 'CLIPLoader', title: 'Load CLIP', installed: true, output: false, fields: { clip_name: 'qwen_3_4b.safetensors', type: 'lumina2' } },
  { id: '66', type: 'UNETLoader', title: 'Load Diffusion Model', installed: true, output: false, fields: { unet_name: 'z_image_turbo_fp8_e4m3fn.safetensors' } },
  { id: '67', type: 'CLIPTextEncode', title: 'Positive', installed: true, output: false, fields: { text: 'young woman sitting on the beach' } },
  { id: '68', type: 'EmptySD3LatentImage', title: 'EmptySD3LatentImage', installed: true, output: false, fields: { width: 1024, height: 1024, batch_size: 1 } },
  { id: '70', type: 'KSampler', title: 'KSampler', installed: true, output: false, fields: { seed: 42, steps: 8, cfg: 1, sampler_name: 'euler', scheduler: 'simple', denoise: 1 } },
  { id: '71', type: 'CLIPTextEncode', title: 'Negative', installed: true, output: false, fields: { text: 'low quality, blurry' } },
  { id: '72', type: 'LoraLoaderModelOnly', title: 'LoraLoaderModelOnly', installed: true, output: false, fields: { lora_name: 'zit_watercolor.safetensors', strength_model: 0.8 } },
  { id: '9', type: 'SaveImage', title: 'Save Image', installed: true, output: true, fields: { filename_prefix: 'ComfyUI' } },
];
const ZIT_INPUTS = { prompt: { node: '67', field: 'text' }, negative: { node: '71', field: 'text' }, seed: { node: '70', field: 'seed' }, steps: { node: '70', field: 'steps' }, cfg: { node: '70', field: 'cfg' }, width: { node: '68', field: 'width' }, height: { node: '68', field: 'height' } };

function packs() {
  const zitSchema = { type: 'object', properties: pick('prompt', 'negative', 'seed', 'steps', 'cfg', 'width', 'height', 'aspect', 'megapixels'), required: ['prompt'] };
  const p = (o) => ({ description: '', tags: [], loose: false, preview: null, issues: { ok: true, errors: 0, warnings: 0 }, presets: {}, set: {}, memory_gb: null, files: { editor: true, api: false, manifest: true }, nodes: NODES_ZIT, issues_list: [], outputs: { image: { node: '9', kind: 'image' } }, ...o });
  const missing = (file, folder, url) => ({ level: 'error', code: 'missing_model', detail: `UNETLoader.unet_name: '${file}' isn't in ComfyUI's model folders`, node: '2',
    fix: `Download it${url ? ` from ${url}` : ''} into data/models/comfyui/${folder}/, or pick a file you have.`, data: { file, input: 'unet_name', url, directory: folder } });
  return [
    p({ id: 'zimage-turbo', name: 'Z-Image Turbo', task: 'text-to-image', state: 'ready', description: 'Fast photoreal text to image (Z-Image Turbo, 8 steps)', tags: ['photo', 'fast'], preview: '/v1/workflows/zimage-turbo/preview',
      schema: zitSchema, inputs: ZIT_INPUTS, presets: { portrait: { width: 832, height: 1216 }, landscape: { width: 1216, height: 832 } }, set: { '66.unet_name': 'z_image_turbo_fp8_e4m3fn.safetensors' } }),
    p({ id: 'zimage-intorealism', name: 'Z-Image IntoRealism + watercolor', task: 'text-to-image', state: 'ready', description: 'Painterly images with a watercolor LoRA',
      schema: { ...zitSchema, properties: { ...zitSchema.properties, lora_strength: { type: 'number', title: 'Watercolor strength', minimum: 0, maximum: 1.5, default: 0.8 } } },
      inputs: { ...ZIT_INPUTS, lora_strength: { node: '72', field: 'strength_model', label: 'Watercolor strength', min: 0, max: 1.5 } }, presets: { subtle: { lora_strength: 0.4 } } }),
    p({ id: 'wan21-i2v', name: 'Wan 2.1 — image to video', task: 'image-to-video', state: 'ready', description: 'Animate a still image into a ~5 s 480p clip', preview: '/v1/workflows/wan21-i2v/preview',
      schema: { type: 'object', properties: pick('prompt', 'image', 'seed', 'steps', 'cfg', 'width', 'height', 'frames', 'fps', 'aspect', 'megapixels', 'seconds'), required: ['prompt', 'image'] },
      inputs: { prompt: { node: '7', field: 'text' }, image: { node: '10', field: 'image' }, frames: { node: '14', field: 'length' }, fps: { node: '17', field: 'fps' } }, outputs: { video: { node: '18', kind: 'video' } }, presets: { short: { frames: 33 } } }),
    p({ id: 'wan21-t2v', name: 'Wan 2.1 — text to video', task: 'text-to-video', state: 'ready', description: 'A ~5 s 480p clip from text',
      schema: { type: 'object', properties: pick('prompt', 'seed', 'steps', 'width', 'height', 'frames', 'fps', 'seconds'), required: ['prompt'] }, outputs: { video: { node: '14', kind: 'video' } } }),
    p({ id: 'krea2-txt2img', name: 'Krea 2 Turbo — text to image', task: 'text-to-image', state: 'broken', issues: { ok: false, errors: 1, warnings: 0 },
      schema: zitSchema, inputs: ZIT_INPUTS, issues_list: [missing('krea2TurboFP8_krea2TURBO.safetensors', 'diffusion_models', null)] }),
    p({ id: 'flux2-klein-edit', name: 'FLUX.2 Klein 9B — instruction edit', task: 'image-edit', state: 'broken', issues: { ok: false, errors: 1, warnings: 0 },
      schema: { type: 'object', properties: pick('prompt', 'image', 'seed'), required: ['prompt', 'image'] }, inputs: { prompt: { node: '9', field: 'text' }, image: { node: '5', field: 'image' } },
      issues_list: [missing('flux-2-klein-9b-fp8.safetensors', 'diffusion_models', 'https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/resolve/main/flux-2-klein-9b-fp8.safetensors')] }),
    p({ id: 'my-portrait', name: 'my-portrait', task: 'custom', state: 'draft', loose: true, files: { editor: true, api: false, manifest: false }, schema: { type: 'object', properties: {} }, inputs: {}, outputs: {} }),
  ];
}

export function comfyMock(m) {
  const { ok, media, upstream, svcById, pushSvc, clone, now, renderImageBlob, later, act } = m;
  const ws = packs(), runs = [], downloads = [];
  const defaults = { 'text-to-image': 'zimage-turbo', 'image-to-video': 'wan21-i2v', 'text-to-video': 'wan21-t2v' };
  const brief = w => ({ id: w.id, name: w.name, task: w.task, state: w.state, description: w.description, tags: w.tags, loose: w.loose, preview: w.preview, issues: w.issues });
  const get = id => { const w = ws.find(x => x.id === id); if (!w) throw upstream(404, `no workflow '${id}'`); return w; };
  const svcStats = () => { const s = svcById('comfy'); if (!s) return; const made = runs.filter(r => r.state === 'done' && r.finished > now() - 86400).reduce((a, r) => a + r.outputs.length, 0);
    s.stats = [{ label: 'Workflows', value: ws.filter(w => w.state === 'ready').length }, { label: 'Drafts', value: ws.filter(w => w.state === 'draft').length },
      { label: 'Queue', value: runs.filter(r => r.state === 'queued' || r.state === 'running').length }, { label: 'Made today', value: made, reset: 'daily' }]; pushSvc(s); };
  const day = () => new Date().toISOString().slice(0, 10);
  const mkRun = (wf, inputs, t0, state = 'queued') => {
    const w = get(wf), r = { id: 'r-' + Math.random().toString(16).slice(2, 12), workflow: wf, label: String(inputs.prompt || w.name).slice(0, 80), state, progress: null,
      inputs: { ...inputs, seed: inputs.seed == null || inputs.seed === -1 ? Math.floor(Math.random() * 2 ** 32) : inputs.seed }, outputs: [], error: null, created: t0, started: null, finished: null, peak_gb: null, prompt_id: null };
    runs.unshift(r); return r;
  };
  const finish = (r, w) => { const kind = w.task.includes('video') ? 'video' : 'image', ext = kind === 'video' ? 'mp4' : 'png';
    const name = `${new Date(r.created * 1000).toTimeString().slice(0, 8).replace(/:/g, '')}-${r.label.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)}_00001_.${ext}`;
    Object.assign(r, { state: 'done', progress: 1, finished: r.started + (kind === 'video' ? 320 : 38), peak_gb: kind === 'video' ? 60.2 : 35.1, outputs: [{ path: `comfy/${day()}/${name}`, kind, name }] }); };
  // history to browse
  [['zimage-turbo', 'a red fox sitting in a snowy pine forest at dawn'], ['wan21-i2v', 'the fox turns its head and looks at the camera'], ['zimage-intorealism', 'a cozy cabin by a mountain lake at sunset']]
    .forEach(([wf, prompt], i) => { const r = mkRun(wf, { prompt }, now() - 3600 * (3 - i)); r.started = r.created; finish(r, get(wf)); });
  const run = r => {
    const w = get(r.workflow), s = svcById('comfy');
    if (s && s.load === 'unloaded') { s.load = 'loaded'; s.used = 2 * m.GB; pushSvc(s); }
    let p = 0;
    const tick = () => {
      if (r.state === 'cancelled') return;
      if (r.state === 'queued') { r.state = 'running'; r.started = now(); }
      p += w.task.includes('video') ? 0.05 : 0.12; r.progress = Math.min(0.99, +p.toFixed(3));
      if (p >= 1) { finish(r, w); r.finished = now(); act(`Images & Video finished "${r.label}"`, 'comfy', 'info', '#/s/comfy/run'); svcStats(); return; }
      later(400, tick);
    };
    later(500, tick); svcStats();
  };
  const fileFor = async (seed, kind) => (kind === 'video' ? media(new Blob([new Uint8Array(16)], { type: 'video/mp4' }), 'video/mp4') : media(await renderImageBlob(seed), 'image/png'));
  const seedOf = s => [...s].reduce((a, c) => a + c.charCodeAt(0), 0);
  svcStats();

  return {
    'GET /health': () => ok({ status: 'ok' }),
    'GET /v1/status': () => ok({ loaded: svcById('comfy')?.load === 'loaded', busy: runs.some(r => r.state === 'running'), idle_s: 30, stats: svcById('comfy')?.stats || [], jobs: [] }),
    'GET /v1/workflows': () => ok({ workflows: ws.map(brief), defaults: clone(defaults) }),
    'GET /v1/workflows/{id}': ({ pp }) => ok(clone(get(pp.id))),
    'GET /v1/workflows/{id}/check': ({ pp }) => { const w = get(pp.id); return ok({ id: w.id, state: w.state, issues: clone(w.issues_list) }); },
    'GET /v1/workflows/{id}/preview': async ({ pp }) => media(await renderImageBlob(seedOf(pp.id)), 'image/png'),
    'GET /v1/workflows/{id}/suggest': ({ pp }) => { const w = get(pp.id);
      const manifest = { name: w.id === 'my-portrait' ? 'My portrait' : w.name, task: 'text-to-image', inputs: clone(ZIT_INPUTS), outputs: { image: { node: '9', kind: 'image' } } };
      return ok({ id: w.id, manifest, toml: `name = "${manifest.name}"\ntask = "text-to-image"\n\n[inputs.prompt]          # CLIPTextEncode "Positive"\nnode = "67"\nfield = "text"\n`, notes: [], why: {} }); },
    'PUT /v1/workflows/{id}': ({ pp, json }) => { const w = get(pp.id); const mf = json?.manifest;
      if (!mf && !json?.toml) throw upstream(422, 'send either toml or manifest');
      if (mf) { if (!TASKS[mf.task]) throw upstream(422, `task: '${mf.task}' isn't a task`); Object.assign(w, { name: mf.name || w.id, task: mf.task, description: mf.description || '', inputs: mf.inputs || {}, presets: mf.presets || {}, set: mf.set || {} }); }
      if (w.state === 'draft') { w.state = 'ready'; w.loose = false; w.files.manifest = true; w.schema = { type: 'object', properties: pick('prompt', 'negative', 'seed', 'width', 'height'), required: ['prompt'] }; }
      svcStats(); return ok(clone(w)); },
    'DELETE /v1/workflows/{id}': ({ pp }) => { const i = ws.findIndex(w => w.id === pp.id); if (i < 0) throw upstream(404, `no workflow '${pp.id}'`); ws.splice(i, 1); svcStats(); return ok({ removed: pp.id }); },
    'GET /v1/tasks': () => ok({ tasks: clone(TASKS), inputs: {} }),
    'GET /v1/defaults': () => ok({ defaults: clone(defaults) }),
    'PUT /v1/defaults': ({ json }) => { for (const [t, id] of Object.entries(json?.defaults || {})) { if (id) defaults[t] = id; else delete defaults[t]; } return ok({ defaults: clone(defaults) }); },
    'POST /v1/run': ({ json }) => { const w = get(json?.workflow); if (w.state !== 'ready') throw upstream(422, `${w.id} has problems: ${w.issues_list.map(i => i.detail).join('; ')}`);
      const req = (w.schema.required || []).filter(k => !json.inputs?.[k]); if (req.length) throw upstream(422, req.map(k => `${k}: required`).join('; '));
      const r = mkRun(w.id, json.inputs || {}, now()); run(r); return ok(clone(r), 202); },
    'GET /v1/jobs': () => ok({ jobs: clone(runs.slice(0, 30)) }),
    'GET /v1/jobs/{id}': ({ pp }) => { const r = runs.find(x => x.id === pp.id); if (!r) throw upstream(404, `no job '${pp.id}'`); return ok(clone(r)); },
    'POST /v1/queue/{id}/cancel': ({ pp }) => { const r = runs.find(x => x.id === pp.id); if (!r) throw upstream(404, `no job '${pp.id}'`);
      if (r.state === 'queued' || r.state === 'running') Object.assign(r, { state: 'cancelled', finished: now(), error: 'cancelled' }); svcStats(); return ok(clone(r)); },
    'GET /v1/files/{a}/{b}/{c}': ({ pp }) => fileFor(seedOf(pp.c), pp.c.endsWith('.mp4') ? 'video' : 'image'),
    'POST /v1/uploads': ({ form }) => { const f = form?.get?.('file'); const name = `20261006-${Math.random().toString(16).slice(2, 8)}-${f?.name || 'upload.png'}`; return ok({ value: `upload:${name}`, name }); },
    'POST /v1/import': ({ form }) => { const f = form?.get?.('file'); if (!f) throw upstream(422, 'file: required');
      if (!/\.(json|png|webp|mp4|webm|zip)$/i.test(f.name)) throw upstream(422, `${f.name}: not a workflow file (JSON, PNG, WebP, MP4/WebM, or a zip of those)`);
      const id = (form.get('id') || f.name.replace(/\.[^.]+$/, '')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workflow';
      const w = { ...packs().find(x => x.id === 'my-portrait'), id, name: id, loose: false }; ws.push(w); svcStats();
      return ok({ id, workflow: clone(w), suggestion: null }, 201); },
    'GET /v1/import/history': () => ok({ items: [{ prompt_id: 'a1b2c3', number: 41, nodes: 12, has_editor: true, status: 'success', files: ['ComfyUI_00041_.png'], from_gaifa: null, types: ['CLIPTextEncode', 'KSampler', 'SaveImage'] }] }),
    'POST /v1/import/history/{pid}': () => { const w = { ...packs().find(x => x.id === 'my-portrait'), id: 'comfy-a1b2c3', name: 'comfy-a1b2c3', loose: false }; ws.push(w); svcStats(); return ok({ id: w.id, workflow: clone(w), suggestion: null }, 201); },
    'POST /v1/downloads': ({ json }) => { const d = { id: 'd-' + Math.random().toString(16).slice(2, 8), url: json.url, folder: json.folder, name: json.name, state: 'running', bytes: 0, total: 9e9, error: null, created: now() };
      downloads.unshift(d); const tick = () => { d.bytes = Math.min(d.total, d.bytes + 1.5e9); if (d.bytes >= d.total) d.state = 'done'; else later(800, tick); }; later(800, tick); return ok(clone(d), 202); },
    'GET /v1/downloads': () => ok({ downloads: clone(downloads) }),
    'GET /v1/hub/widgets/made': ({ query }) => { const n = query.range === '30d' ? 30 : 7, cats = Array.from({ length: n }, (_, i) => new Date(Date.now() - (n - 1 - i) * 864e5).toISOString().slice(5, 10));
      return ok({ unit: 'files', categories: cats, series: [{ name: 'Images', values: cats.map((_, i) => Math.max(0, Math.round(4 + 3 * Math.sin(i / 1.7)))) }, { name: 'Videos', values: cats.map((_, i) => (i % 3 === 0 ? 1 : 0)) }] }); },
    'GET /v1/stats': () => { const by = {}; runs.forEach(r => { const w = by[r.workflow] ||= { id: r.workflow, name: get(r.workflow).name, runs: 0, done: 0, failed: 0, cancelled: 0, secs: [] }; w.runs++; if (w[r.state] != null) w[r.state]++; if (r.state === 'done') w.secs.push(r.finished - r.started); });
      return ok({ range: '30d', workflows: Object.values(by).map(({ secs, ...w }) => ({ ...w, avg_s: secs.length ? secs.reduce((a, b) => a + b, 0) / secs.length : null, p50_s: secs.length ? secs.sort((a, b) => a - b)[secs.length >> 1] : null })), recent: [] }); },
    'GET /v1/tools': () => ok({ tools: [] }),
    'POST /v1/load': () => { const s = svcById('comfy'); s.load = 'loaded'; s.used = 2 * m.GB; pushSvc(s); return ok({ loaded: true }); },
    'POST /v1/unload': () => { const s = svcById('comfy'); s.load = 'unloaded'; s.used = 0.07 * m.GB; pushSvc(s); return ok({ loaded: false }); },
  };
}
