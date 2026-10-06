// The built-in mods' native APIs on the mock (brief §7, Part B): what each mod's own page calls
// through ctx.call. Moved out of mock.js in plan 8.7; `m` is mock.js's toolbox (state + helpers).
// Written by us, not Claude Design.

export function createModMocks(m) {
  const { ok, media, upstream, svcById, pushSvc, act, doLoad, doUnload, loadSvc, ttsOutput, makeWav, clone, now, GB, jobs, emit, models, usedBytes, renderImageBlob, voices, KOKORO, voice } = m;
  return {
  tts: {
    'GET /health': () => ok({ status: 'ok', engines: { breeze: { state: svcById('tts').load === 'loaded' ? 'ready' : 'unloaded' }, kokoro: { state: 'unloaded' } }, voices: voices.length }),
    'GET /v1/voices': () => ok({ custom: clone(voices), kokoro: KOKORO }),
    'GET /v1/voices/{name}/audio': () => media(makeWav(4, 3), 'audio/wav'),
    'POST /v1/voices': ({ form }) => { const name = form?.name ?? form?.get?.('name'), file = form?.audio ?? form?.get?.('audio');
      if (!name) throw upstream(422, 'name: field required'); if (!file || !file.size) throw upstream(422, 'audio: a reference clip is required');
      if (voices.some(v => v.name.toLowerCase() === String(name).toLowerCase())) throw upstream(409, `voice '${name}' exists; pass overwrite=true to replace it`);
      const tr = form?.transcript ?? form?.get?.('transcript'), v = voice(String(name), 'upload', 12.0, tr || 'Hello, this is my voice.', { transcript_auto: !tr });
      voices.push(v); svcById('tts').stats[0].value = voices.length; pushSvc(svcById('tts')); act(`Speech: voice "${v.name}" cloned`, 'tts'); return ok(clone(v), 201); },
    'PATCH /v1/voices/{name}': ({ pp, json }) => { const v = voices.find(x => x.name === pp.name); if (!v) throw upstream(404, `no voice named '${pp.name}'`);
      if (json?.transcript) Object.assign(v, { transcript: json.transcript, transcript_auto: false }); if (json?.rename) v.name = json.rename; return ok(clone(v)); },
    'POST /v1/voices/design': ({ json }) => { if (!json?.name || !json?.instruction) throw upstream(422, 'name and instruction are required');
      const v = voice(json.name, 'design', 8.1, json.sample_text || 'Hello, and welcome.', { instruction: json.instruction }); voices.push(v); svcById('tts').stats[0].value = voices.length; pushSvc(svcById('tts')); return ok({ ...clone(v), stats: { audio_s: 8.1 } }, 201); },
    'DELETE /v1/voices/{name}': ({ pp }) => { const i = voices.findIndex(v => v.name === pp.name); if (i < 0) throw upstream(404, `no voice named '${pp.name}'`); voices.splice(i, 1); svcById('tts').stats[0].value = voices.length; pushSvc(svcById('tts')); return ok({ deleted: pp.name, permanent: true }); },
    'POST /v1/speech': async ({ json }) => { if (!json?.text?.trim()) throw upstream(400, 'text is empty');
      const s = svcById('tts'); if (s.load === 'unloaded') doLoad(s);
      const engine = json.engine === 'kokoro' || KOKORO.includes(json.voice) ? 'kokoro' : 'breeze', v = json.voice || (engine === 'kokoro' ? 'af_heart' : 'design');
      const blob = json.no_save ? makeWav(4, json.seed || 7) : ttsOutput(json.text.trim(), v, engine === 'kokoro' ? 'kokoro-82m' : 'breeze-tts-2', json.format || 'wav', { instructions: json.instruction, speed: json.speed });
      if (!json.timings) return media(blob, 'audio/wav');
      const buf = new Uint8Array(await blob.arrayBuffer()); let bin = ''; buf.forEach(c => { bin += String.fromCharCode(c); });
      const words = json.text.trim().split(/\s+/), dur = Math.max(1.5, (buf.length - 44) / 2 / 16000), step = dur / words.length;
      return ok({ audio: btoa(bin), format: 'wav', sample_rate: 16000, engine, voice: v, saved: json.no_save ? 'no' : 'mock.wav',
        timings: { duration: dur, sample_rate: 16000, words: words.map((w, i) => ({ w, start: +(i * step).toFixed(2), end: +((i + 1) * step).toFixed(2) })) }, stats: { rtf: 0.4 } }); },
    'POST /v1/audio/speech': ({ json }) => { if (!json?.input) throw upstream(422, 'input: field required'); return media(ttsOutput(json.input, json.voice || 'hope', 'breeze-tts-2', json.response_format || 'mp3', { openai: true }), 'audio/wav'); },
    'POST /v1/enhance': ({ json }) => { if (!json?.text) throw upstream(400, 'text is empty'); const parts = json.text.split(/(?<=[.!?])\s+/);
      return ok({ text: parts.map((p, i) => (i === 0 ? '(laugh) ' : '') + p).join(' '), delivery: 'Warm and amused, unhurried.', tags_added: 1, model: 'gemma-4-26b-it' }); },
    'GET /v1/hub/widgets/clips': ({ query }) => { const n = query.range === '30d' ? 30 : 7, day = 86400e3;
      const cats = Array.from({ length: n }, (_, i) => new Date(Date.now() - (n - 1 - i) * day).toISOString().slice(5, 10));
      return ok({ unit: 'count', categories: cats, series: ['Hope', 'af_heart', 'Brendon'].map((name, k) => ({ name, values: cats.map((_, i) => Math.max(0, Math.round(3 * Math.sin(i / 2 + k * 2) + 2 - k))) })) }); },
    'POST /v1/load': () => { loadSvc(svcById('tts'), true).catch(() => {}); return ok({ engine: 'breeze', state: 'loading' }); },
    'POST /v1/unload': () => { doUnload(svcById('tts')); return ok({ unloaded: ['breeze'] }); },
  },
  gen3d: gen3dMock(m),
  lcpp: {
    'GET /api/overview': () => ok({ instances: [{ name: 'gemma4-26B-7071', model: 'gemma-4-26b-it', port: 7071, state: 'ready', ctx: 32768, mem_bytes: svcById('lcpp').used }], catalog: 4, on_disk_bytes: 20.9 * GB }),
    'GET /api/models': () => ok({ models: models.filter(m => m.services.includes('lcpp')).map(m => ({ id: m.id, name: m.name, status: m.status, size_bytes: m.size_bytes })) }),
    'POST /api/instances': ({ json }) => { const m = models.find(x => x.id === json?.model); if (!m) throw upstream(422, 'model: unknown catalog model'); if (m.status !== 'ok') throw upstream(409, `${m.id}: files missing`); return ok({ name: `${json.name || m.id}-${json.port || 7072}`, state: 'starting' }, 202); },
    'DELETE /api/instances/{name}': ({ pp }) => { if (pp.name !== 'gemma4-26B-7071') throw upstream(404, `instance ${pp.name} not found`); return ok({ name: pp.name, state: 'stopping' }, 202); },
    'GET /api/instances/{name}/logs/stream': ({ pp }) => ({ stream: async function* () { for (let i = 0; i < 200; i++) { yield `[${pp.name}] slot ${i % 4} | prompt ${Math.floor(200 + Math.random() * 3000)} tok, gen ${Math.floor(20 + Math.random() * 400)} tok, ${(30 + Math.random() * 20).toFixed(1)} t/s`; await new Promise(r => setTimeout(r, 450)); } } }),
  },
  relay: {
    'GET /admin/stats/summary': ({ query }) => ok({ window: query.window || '24h', requests: Number(svcById('relay').stats[0].value), tokens: 3100000, ttft_p50_ms: 412, ttft_p95_ms: 1380, tok_s: 41.7, error_rate: 0.012 }),
    'GET /admin/stats/by-model': () => ok({ dimensions: ['model'], source: 'requests', rows: [{ model: 'gemma-4-26b-it', requests: 1031, tokens: 2610000 }, { model: 'minicpm-5-2b', requests: 241, tokens: 402000 }, { model: 'openrouter/auto', requests: 12, tokens: 88000 }] }),
    'GET /admin/endpoints': () => ok({ endpoints: [{ id: 'lcpp/gemma4-26B-7071', url: 'http://127.0.0.1:7071/v1', owner: 'lcpp', healthy: true }, { id: 'openrouter', url: 'https://openrouter.ai/api/v1', owner: null, healthy: true }, { id: 'lab-box', url: 'http://10.0.0.12:8080/v1', owner: null, healthy: false }] }),
    'GET /v1/models': () => ok({ object: 'list', data: [{ id: 'gemma-4-26b-it', object: 'model', owned_by: 'lcpp' }, { id: 'minicpm-5-2b', object: 'model', owned_by: 'lcpp' }] }),
    'POST /v1/chat/completions': ({ json }) => { if (!json?.messages?.length) throw upstream(400, 'messages: must contain at least one message');
      const words = 'Shared pool of light — / weights and frames drink from one well, / nothing waits its turn.'.split(' ');
      return { stream: async function* () { for (const w of words) { yield JSON.stringify({ choices: [{ delta: { content: w + ' ' } }] }); await new Promise(r => setTimeout(r, 140)); } yield '[DONE]'; } }; },
  },
  comfy: {
    'GET /system_stats': () => ok({ system: { os: 'posix', comfyui_version: '0.3.62', python_version: '3.12.7', pytorch_version: '2.8.0+rocm7.0' }, devices: [{ name: 'AMD Radeon 8060S', type: 'cuda', vram_total: 121.5 * GB, vram_free: 121.5 * GB - usedBytes() }] }),
    'GET /object_info': () => ok({ KSampler: { input: { required: { seed: ['INT'], steps: ['INT'], cfg: ['FLOAT'] } } }, CLIPTextEncode: { input: { required: { text: ['STRING'] } } }, VAEDecode: {}, SaveImage: {} }),
    'POST /prompt': ({ json }) => { if (!json?.prompt) throw upstream(400, 'prompt: missing'); return ok({ prompt_id: Math.random().toString(16).slice(2, 10), number: 1, node_errors: {} }); },
    'GET /history/{prompt_id}': ({ pp }) => ok({ [pp.prompt_id]: { status: { status_str: 'success', completed: true }, outputs: { 9: { images: [{ filename: 'ComfyUI_00012_.png', type: 'output' }] } } } }),
    'GET /view': async ({ query }) => { if (!query.filename) throw upstream(400, 'filename: required'); return media(await renderImageBlob([...query.filename].reduce((a, c) => a + c.charCodeAt(0), 0)), 'image/png'); },
  },
  transcribe: {
    'GET /health': () => ok({ status: 'ok', model: 'whisper-large-v3-turbo' }),
    'POST /v1/transcribe': ({ form }) => { const f = form?.get?.('file'); if (!f || !f.size) throw upstream(422, 'file: an audio file is required');
      return ok({ text: 'Good morning! The coffee is ready and the forecast looks bright.', language: 'en', duration_s: 4.2, file: f.name, segments: [{ start: 0, end: 1.4, text: 'Good morning!' }, { start: 1.4, end: 4.2, text: 'The coffee is ready and the forecast looks bright.' }] }); },
  },
  };
}

// ---- gen3d: jobs with stages, live events and small GLBs for the viewer ----------------------
const STAGES = ['shape', 'parts', 'rig', 'preview'];
const PRESETS = {
  lowpoly: { label: 'Low-poly', help: 'about 1,000 faces for the whole asset: coarse decode, then decimation', shape: { resolution_base: 7.0, target_faces: 1000 }, parts: { steps: 25, target_faces: 1000 }, rig: { target_faces: 1000 } },
  fast: { label: 'Fast', help: 'coarser meshes, 25 CubePart steps (~1 min shape, ~1.8 min parts)', shape: { resolution_base: 7.5 }, parts: { steps: 25 }, rig: {} },
  balanced: { label: 'Balanced', help: 'the upstream defaults (~1.5 min shape, ~3.2 min parts)', shape: { resolution_base: 8.0 }, parts: { steps: 50 }, rig: {} },
  quality: { label: 'Quality', help: 'finer meshes (~2.5 min shape, ~3.7 min parts, 52 GB peak)', shape: { resolution_base: 8.5 }, parts: { steps: 50 }, rig: {} },
};
const TEMPLATES = { Chair: ['seat', 'backrest', 'legs', 'armrests'], Character: ['head', 'torso', 'left arm', 'right arm', 'left leg', 'right leg'], Vehicle: ['body', 'front left wheel', 'front right wheel', 'rear left wheel', 'rear right wheel', 'windows'], Weapon: ['blade', 'guard', 'grip', 'pommel'], Creature: ['head', 'body', 'tail', 'wings', 'legs'] };
const SECS = { shape: 70, parts: 110, rig: 8, preview: 12 };
const COLORS = [[242, 109, 109], [109, 180, 242], [140, 220, 120], [240, 200, 90], [190, 130, 240], [90, 220, 210], [240, 150, 60], [200, 200, 200]];

/** A GLB of coloured boxes, one node each (enough for the viewer on the mock). */
export function boxesGlb(boxes) {
  const nodes = [], meshes = [], accessors = [], views = [];
  const bins = [];
  let off = 0;
  const add = (arr, Type, target) => { const a = new Type(arr); const b = new Uint8Array(a.buffer); const pad = (4 - (b.length % 4)) % 4; bins.push(b, new Uint8Array(pad)); views.push({ buffer: 0, byteOffset: off, byteLength: b.length, target }); off += b.length + pad; return views.length - 1; };
  boxes.forEach((bx, k) => {
    const [cx, cy, cz] = bx.center, [sx, sy, sz] = bx.size.map(v => v / 2), c = (bx.color || [184, 178, 168]).map(v => v / 255);
    const P = [], C = [], I = [];
    for (let i = 0; i < 8; i++) { P.push(cx + (i & 1 ? sx : -sx), cy + (i & 2 ? sy : -sy), cz + (i & 4 ? sz : -sz)); C.push(...c); }
    for (const f of [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]) I.push(f[0], f[1], f[2], f[0], f[2], f[3]);
    const pv = add(P, Float32Array, 34962), cv = add(C, Float32Array, 34962), iv = add(I, Uint16Array, 34963);
    const mn = [cx - sx, cy - sy, cz - sz], mx = [cx + sx, cy + sy, cz + sz];
    accessors.push({ bufferView: pv, componentType: 5126, count: 8, type: 'VEC3', min: mn, max: mx }, { bufferView: cv, componentType: 5126, count: 8, type: 'VEC3' }, { bufferView: iv, componentType: 5123, count: I.length, type: 'SCALAR' });
    const a0 = accessors.length - 3;
    meshes.push({ primitives: [{ attributes: { POSITION: a0, COLOR_0: a0 + 1 }, indices: a0 + 2 }] });
    nodes.push({ name: bx.name || `box_${k}`, mesh: k });
  });
  const bin = new Uint8Array(off); let o = 0; for (const b of bins) { bin.set(b, o); o += b.length; }
  const json = { asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: nodes.map((_, i) => i) }], nodes, meshes, accessors, bufferViews: views, buffers: [{ byteLength: off }] };
  let js = new TextEncoder().encode(JSON.stringify(json)); const jp = (4 - (js.length % 4)) % 4;
  js = new Uint8Array([...js, ...new Array(jp).fill(32)]);
  const total = 12 + 8 + js.length + 8 + bin.length, out = new DataView(new ArrayBuffer(total));
  out.setUint32(0, 0x46546C67, true); out.setUint32(4, 2, true); out.setUint32(8, total, true);
  out.setUint32(12, js.length, true); out.setUint32(16, 0x4E4F534A, true); new Uint8Array(out.buffer, 20, js.length).set(js);
  out.setUint32(20 + js.length, bin.length, true); out.setUint32(24 + js.length, 0x004E4942, true); new Uint8Array(out.buffer, 28 + js.length, bin.length).set(bin);
  return new Blob([out.buffer], { type: 'model/gltf-binary' });
}

function gen3dMock(m) {
  const { ok, media, upstream, svcById, pushSvc, clone, now, runJob, renderImageBlob, later } = m;
  const store = new Map(), listeners = new Set();
  const pub = j => { for (const fn of listeners) fn(clone(j)); };
  const partsOf = req => (req.parts?.parts?.length ? req.parts.parts : ['body']).slice(0, 8);
  const filesFor = j => {
    const f = ['output.json'];
    if (j.stages.shape?.state === 'done') f.push('mesh.glb');
    if (j.stages.parts?.state === 'done') f.push('parts.glb');
    if (j.stages.rig?.state === 'done') f.push('rigged.glb');
    if (j.stages.preview?.state === 'done') f.push('preview.png');
    return f;
  };
  const make = (req, t0, status = 'queued') => {
    const id = 'j_' + Math.random().toString(16).slice(2, 12), stages = Object.fromEntries(req.stages.map(s => [s, { state: 'pending' }]));
    const j = { id, chat_id: req.chat_id === 'new' ? 'c_' + id.slice(2) : req.chat_id || null, parent_id: req.parent_id || null, title: (req.title || req.prompt || req.stages.join(' + ')).slice(0, 80), status, request: req, stages, result: {}, error: null, created: t0, started: null, finished: null, files: [], eta: null };
    store.set(id, j); return j;
  };
  const finish = (j, t0) => { let t = t0; for (const s of j.request.stages) { const d = SECS[s] * (0.8 + Math.random() * 0.4); j.stages[s] = { state: 'done', started: t, finished: t + d, seconds: Math.round(d * 10) / 10 }; t += d; } j.status = 'done'; j.started = t0; j.finished = t;
    if (j.stages.shape) j.result.shape = { mesh: 'mesh.glb', faces: 1000, peak_gpu_gb: 10.5 }; if (j.stages.parts) j.result.parts = { dir: 'parts', scene: 'parts.glb', parts: partsOf(j.request).map((name, index) => ({ index, name, file: `part_0${index}.glb`, faces: 120 + index * 30, color: COLORS[index % 8] })), peak_gpu_gb: 29.9 };
    if (j.stages.rig) j.result.rig = { glb: 'rigged.glb', joints: [], faces: 960, peak_gpu_gb: 0 }; j.files = filesFor(j); };
  // three finished jobs to browse
  [['low-poly cartoon fox sitting', ['shape', 'parts', 'rig', 'preview'], ['head', 'body', 'tail', 'legs']], ['ornate brass hanging lantern', ['shape', 'preview'], []], ['wooden treasure chest with iron bands', ['shape', 'parts', 'preview'], ['lid', 'base', 'lock']]].forEach(([prompt, stages, parts], i) => {
    const j = make({ prompt, stages, preset: 'lowpoly', parts: { parts }, shape: { seed: 0 }, rig: {} }, now() - 86400 * (i + 1));
    finish(j, j.created);
  });
  const run = j => {
    let i = 0; const steps = j.request.stages; j.status = 'running'; j.started = now();
    const tick = () => {
      if (j.status === 'canceled') return;
      if (i >= steps.length) { j.status = 'done'; j.finished = now(); j.eta = null; j.files = filesFor(j); finish(j, j.started); j.finished = now(); pub(j); return; }
      const s = steps[i], st = j.stages[s];
      if (st.state === 'pending') Object.assign(st, { state: 'running', started: now(), step: 0, total: 10 });
      st.step += 1;
      j.eta = { queue_position: 0, starts_in_s: 0, eta_s: (steps.length - i) * 5 - st.step * 0.5, own_s: steps.length * 5, by_stage: Object.fromEntries(steps.map(x => [x, 5])) };
      if (st.step >= st.total) { Object.assign(st, { state: 'done', finished: now(), seconds: Math.round((now() - st.started) * 10) / 10, step: null, total: null }); i++; j.files = filesFor(j); }
      pub(j); later(500, tick);
    };
    later(300, tick);
  };
  const box = (name, center, size, color) => ({ name, center, size, color });
  const glb = (j, f) => {
    const parts = partsOf(j.request);
    if (f === 'mesh.glb') return boxesGlb([box('mesh', [0, 0.5, 0], [0.8, 1, 0.5], [184, 178, 168])]);
    return boxesGlb(parts.map((p, i) => box(`part_0${i}_${p.replace(/\W+/g, '_')}`, [((i % 3) - 1) * 0.45, 0.25 + Math.floor(i / 3) * 0.5, 0], [0.4, 0.4, 0.4], COLORS[i % 8])));
  };
  const get = id => { const j = store.get(id); if (!j) throw upstream(404, `no job '${id}'`); return j; };
  const queue = req => {
    if (!req?.stages?.length) throw upstream(422, 'choose at least one stage');
    if (req.stages.includes('shape') && !req.prompt?.trim()) throw upstream(422, 'the shape stage needs a prompt');
    const j = make(req, now()); pub(j); run(j);
    if (req.prompt) runJob(req.prompt, req);
    return ok(clone(j), 201);
  };
  return {
    'GET /health': () => ok({ status: 'ok', worker: { state: svcById('gen3d').load === 'loaded' ? 'ready' : 'stopped' } }),
    'GET /v1/options': () => ok({ stages: STAGES.map(key => ({ key })), presets: PRESETS, part_templates: TEMPLATES, max_parts: 8 }),
    'GET /v1/presets': () => ok(PRESETS),
    'POST /v1/estimate': ({ json }) => { const stages = json?.stages || ['shape', 'preview']; if (stages.includes('shape') && !json?.prompt?.trim()) throw upstream(422, 'the shape stage needs a prompt');
      const plan = stages.map(stage => ({ stage, sub: stage, seconds: SECS[stage] })), own = plan.reduce((a, p) => a + p.seconds, 0);
      return ok({ plan, own_s: own, wait_s: 0, eta_s: own, done_at: now() + own }); },
    'POST /v1/jobs': ({ json }) => queue(json),
    'POST /v1/jobs/upload': ({ form }) => { const job = JSON.parse(form?.job ?? form?.get?.('job') ?? '{}'); return queue({ ...job, title: 'upload' }); },
    'GET /v1/jobs': ({ query }) => { let js = [...store.values()].sort((a, b) => b.created - a.created); if (query.status) js = js.filter(j => query.status.split(',').includes(j.status)); return ok({ jobs: clone(js.slice(0, Number(query.limit) || 100)) }); },
    'GET /v1/jobs/{id}': ({ pp }) => ok(clone(get(pp.id))),
    'POST /v1/jobs/{id}/cancel': ({ pp }) => { const j = get(pp.id); if (['queued', 'running'].includes(j.status)) { j.status = 'canceled'; j.finished = now(); pub(j); } return ok(clone(j)); },
    'POST /v1/jobs/{id}/retry': ({ pp }) => { const j = get(pp.id); return queue({ ...j.request, shape: { ...j.request.shape, seed: (j.request.shape?.seed || 0) + 1 } }); },
    'DELETE /v1/jobs/{id}': ({ pp }) => { get(pp.id); store.delete(pp.id); for (const fn of listeners) fn({ id: pp.id }); return ok({ deleted: pp.id }); },
    'GET /v1/jobs/{id}/files/{file}': async ({ pp }) => { const j = get(pp.id);
      if (pp.file.endsWith('.glb')) return media(glb(j, pp.file), 'model/gltf-binary');
      if (pp.file === 'preview.png') return media(await renderImageBlob(j.id.length * 7 + j.created % 97), 'image/png');
      throw upstream(404, `no file '${pp.file}' in job ${j.id}`); },
    'GET /v1/jobs/{id}/download': ({ pp }) => { get(pp.id); return media(new Blob(['PK mock zip'], { type: 'application/zip' }), 'application/zip'); },
    'GET /v1/events': () => ({ stream: async function* () {
      const q = []; let wake = null; const fn = j => { q.push(j); wake?.(); };
      listeners.add(fn);
      try { for (let n = 0; n < 2000; n++) { if (!q.length) await new Promise(r => { wake = r; setTimeout(r, 15000); }); while (q.length) yield JSON.stringify(q.shift()); } } finally { listeners.delete(fn); }
    } }),
    'GET /v1/hub/widgets/stages': () => { const js = [...store.values()].filter(j => j.status === 'done').sort((a, b) => a.finished - b.finished);
      return ok({ unit: 'seconds', categories: js.map(j => j.title.slice(0, 24)), series: STAGES.map(s => ({ name: s, values: js.map(j => j.stages[s]?.seconds ?? null) })).filter(s => s.values.some(v => v)) }); },
    'POST /v1/load': () => { loadSvc(svcById('gen3d'), true).catch(() => {}); return ok({ state: 'starting' }); },
    'POST /v1/unload': () => { m.doUnload(svcById('gen3d')); return ok({ stopped: true, state: 'stopped' }); },
  };
}
