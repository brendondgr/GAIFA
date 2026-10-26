// The built-in mods' native APIs on the mock (brief §7, Part B): what each mod's own page calls
// through ctx.call. Moved out of mock.js in plan 8.7; `m` is mock.js's toolbox (state + helpers).
// Written by us, not Claude Design.

import { comfyMock } from './mock-comfy.js';

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
  lcpp: lcppMock(m),
  relay: relayMock(m),
  comfy: comfyMock(m),
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

// ---- relay: DashLLM's admin API shapes ({dimensions, source} datasets) -------------------------
function relayMock(m) {
  const { ok, upstream, svcById, now } = m;
  const EP = [
    { id: 'ep-lcpp', name: 'gemma4-26B-7071', alias: 'gemma-4-26b-it', kind: 'local', server_type: 'llama.cpp', protocol: 'openai', available_models: ['gemma-4-26b-it'], base_url: 'http://127.0.0.1:7071/v1', health: 'healthy', ewma_latency_ms: 212, active: true, share: 0.81, enabled: true, owner: 'lcpp' },
    { id: 'ep-sky', name: 'skynet', alias: 'skynet', kind: 'remote_tunnel', server_type: 'vLLM', protocol: 'openai', available_models: [], base_url: 'http://127.0.0.1:9090/v1', tunnel_command: 'ssh -N -L 127.0.0.1:9090:localhost:9090 skynet', health: 'healthy', ewma_latency_ms: 279, active: false, share: 0.17, enabled: true, owner: null },
    { id: 'ep-lab', name: 'lab-box', alias: 'lab', kind: 'remote', server_type: 'openai', protocol: 'openai', available_models: [], base_url: 'http://10.0.0.12:8080/v1', health: 'failed', ewma_latency_ms: null, active: false, share: 0.02, enabled: true, owner: null },
  ];
  const MODELS = ['gemma-4-26b-it', 'minicpm-5-2b', 'skynet', 'agent'];
  const hours = w => (w === '1h' ? 60 : w === '7d' ? 168 : w === '30d' ? 720 : 24);
  const step = w => (w === '1h' ? 60 : 3600);
  const labels = w => { const n = hours(w), st = step(w), t0 = Math.floor(now() / st) * st; return Array.from({ length: n }, (_, i) => { const d = new Date((t0 - (n - 1 - i) * st) * 1000), p = x => String(x).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; }); };
  const wave = (i, k) => Math.max(0, Math.round(40 + 35 * Math.sin(i / 3 + k) + 10 * Math.sin(i * 1.7)));
  return {
    'GET /admin/stats/summary': ({ query }) => { const req = Number(svcById('relay').stats[0].value) * (query.window === '7d' ? 6 : query.window === '30d' ? 22 : 1);
      return ok({ requests: req, errors: Math.round(req * 0.012), error_rate: 0.012, prompt_tokens: req * 1400, completion_tokens: req * 1000, total_tokens: req * 2400, cost_usd: 0, ttft_ms: { p50: 412, p95: 1380 }, latency_ms: { p50: 2400, p95: 7100 }, tokens_per_sec: { p50: 41.7 } }); },
    'GET /admin/stats/tokens/timeseries': ({ query }) => ok({ dimensions: ['time', 'input', 'output'], source: labels(query.window).map((t, i) => [t, wave(i, 0) * 900, wave(i, 1) * 700]) }),
    'GET /admin/stats/volume': ({ query }) => ok({ dimensions: ['time', 'requests', 'errors'], source: labels(query.window).map((t, i) => [t, wave(i, 0), i % 9 === 0 ? 1 : 0]) }),
    'GET /admin/stats/latency': ({ query }) => ok({ dimensions: ['time', 'ttft_p50', 'ttft_p95', 'tps_p50'], source: labels(query.window).map((t, i) => [t, 380 + wave(i, 2), 1200 + wave(i, 3) * 4, 38 + (i % 7)]) }),
    'GET /admin/stats/tokens/by-hour': () => ok({ dimensions: ['hour', 'input', 'output'], source: Array.from({ length: 24 }, (_, hh) => [hh, hh > 7 && hh < 23 ? wave(hh, 0) * 3000 : 0, hh > 7 && hh < 23 ? wave(hh, 1) * 2200 : 0]) }),
    'GET /admin/stats/by-model': () => ok({ dimensions: ['model', 'requests', 'tokens', 'cost', 'avg_tps', 'errors'], source: [['gemma-4-26b-it', 1031, 2610000, 0, 41.2, 9], ['skynet', 241, 402000, 0, 146.3, 3], ['agent', 12, 88000, 0, 0, 0]] }),
    'GET /admin/stats/by-endpoint': () => ok({ dimensions: ['endpoint', 'requests', 'tokens', 'errors'], source: EP.map((e, i) => [e.name, [1031, 241, 12][i], 0, [9, 3, 12][i]]) }),
    'GET /admin/stats/live': () => ok({ in_flight: 1, active: 1, waiting: 0, max_concurrency: 256 }),
    'GET /admin/stats/recent': () => { const t = now(); return ok({ rows: Array.from({ length: 30 }, (_, i) => ({ id: `req_${i}`, ts: t - i * 37, endpoint_name: EP[i % 2].name, route: 'chat.completions', model: i % 2 ? 'skynet' : 'gemma-4-26b-it', status: i % 11 === 5 ? 502 : 200, error: i % 11 === 5 ? 'upstream timed out' : null, prompt_tokens: 400 + i * 7, completion_tokens: 300 + i * 5, total_tokens: 700 + i * 12, ttft_ms: 400, latency_ms: 2200 + i * 30, tokens_per_sec: 41 + (i % 5), stream: i % 3 === 0, ok: i % 11 !== 5, state: i % 11 === 5 ? 'error' : 'done' })), counts: { done: 27, error: 3 } }); },
    'GET /admin/endpoints': () => ok(EP.map(e => ({ ...e }))),
    'GET /admin/router': () => ok({ policy: 'priority', pinned_id: null, resolved_id: 'ep-lcpp', resolved_name: EP[0].name }),
    'POST /admin/endpoints': ({ json }) => {   // plan llm-servers: a preset (anthropic, openai, gemini) fills the rest
      const PRE = { anthropic: ['anthropic', 'https://api.anthropic.com', 'claude'], openai: ['openai', 'https://api.openai.com/v1', 'openai'], gemini: ['gemini', 'https://generativelanguage.googleapis.com', 'gemini'] }[json?.preset];
      if (!json?.name || (!json?.base_url && !PRE)) throw upstream(422, 'base_url is required (or a preset: anthropic, openai, gemini)');
      const { upstream_key: key, preset, ...rest } = json;
      const e = { id: 'ep-' + Math.random().toString(16).slice(2, 8), alias: PRE ? PRE[2] : json.name, kind: PRE ? 'cloud' : 'remote_direct', protocol: PRE ? PRE[0] : 'openai', server_type: PRE ? preset : 'openai',
        base_url: PRE ? PRE[1] : '', health: 'healthy', share: 0, enabled: true, owner: null, available_models: [], list_models: !!PRE, hidden_models: [], hide_filter: true, has_key: !!key, key_hint: key ? '…' + key.slice(-4) : null, ...rest };
      EP.push(e); return ok(e, 201); },
    'GET /admin/endpoints/{eid}/models': ({ pp }) => { const e = EP.find(x => x.id === pp.eid); if (!e) throw upstream(404, 'endpoint not found');
      const ids = { anthropic: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'], gemini: ['gemini-3.7-flash', 'gemini-3.5-pro'] }[e.protocol] || (e.kind === 'cloud' ? ['gpt-5.6', 'gpt-5.6-mini', 'text-embedding-3-large', 'whisper-1'] : e.available_models);
      const hide = id => (e.hidden_models || []).includes(id) || (e.hide_filter !== false && e.kind === 'cloud' && /embed|whisper/.test(id));
      return ok({ endpoint: e.name, alias: e.alias, ts: now(), error: e.has_key === false && e.kind === 'cloud' ? 'HTTP 401: key rejected' : null, hide_filter: e.hide_filter !== false,
        models: ids.map(id => ({ id, display_name: id, context_length: e.protocol === 'openai' ? null : 1000000, max_output: null, tools: true, vision: true, reasoning: true, hidden: hide(id) })) }); },
    'PATCH /admin/endpoints/{eid}/models': ({ pp, json }) => { const e = EP.find(x => x.id === pp.eid); if (json.hidden) e.hidden_models = json.hidden; if (json.hide_filter !== undefined) e.hide_filter = json.hide_filter; return ok({ ok: true }); },
    'PATCH /admin/endpoints/{eid}': ({ pp, json }) => { const e = EP.find(x => x.id === pp.eid); if (!e) throw upstream(404, 'no endpoint'); Object.assign(e, json); return ok(e); },
    'DELETE /admin/endpoints/{eid}': ({ pp }) => { const i = EP.findIndex(x => x.id === pp.eid); if (i < 0) throw upstream(404, 'no endpoint'); EP.splice(i, 1); return ok({ deleted: pp.eid }); },
    'POST /admin/endpoints/{eid}/activate': ({ pp }) => { EP.forEach(e => { e.active = e.id === pp.eid; }); return ok({ ok: true }); },
    'POST /admin/endpoints/{eid}/test': ({ pp }) => { const e = EP.find(x => x.id === pp.eid); return ok(e?.health === 'failed' ? { ok: false, error: 'connection refused' } : { ok: true, latency_ms: 231 }); },
    'GET /admin/endpoints/{eid}/tunnel': ({ pp }) => ok({ endpoint_id: pp.eid, status: 'connected', prompt: null, prompt_secret: false, output: [], last_error: null, local_port: 9090, pid: 4242, uptime_s: 5400 }),
    'POST /admin/endpoints/{eid}/tunnel/connect': () => ok({ status: 'connecting' }),
    'POST /admin/endpoints/{eid}/tunnel/disconnect': () => ok({ status: 'idle' }),
    'GET /admin/tunnels': () => ok([]),
    'GET /admin/proxy': () => ok({ base_url: 'http://localhost:4000/v1', port: 4000, example_model: 'auto', uptime_s: 18000, requests_total: 148117, active_clients: 1, db_size_bytes: 47e6 }),
    'GET /admin/status': () => ok({ loaded: null, busy: false, stats: svcById('relay').stats }),
    'GET /admin/hub/widgets/traffic': ({ query }) => { const L = labels(query.range === '7d' ? '7d' : '24h'); return ok({ unit: 'count', t: L.map(x => new Date(x).getTime() / 1000), series: [{ name: 'Requests', values: L.map((_, i) => wave(i, 0)) }, { name: 'Tokens', values: L.map((_, i) => wave(i, 1) * 1600), axis: 'right' }] }); },
    'GET /v1/models': () => ok({ object: 'list', data: MODELS.map(id => ({ id, object: 'model', owned_by: 'relay' })) }),
    'POST /v1/chat/completions': ({ json }) => { if (!json?.messages?.length) throw upstream(400, 'messages: must contain at least one message');
      const words = 'Shared pool of light — / weights and frames drink from one well, / nothing waits its turn.'.split(' ');
      return { stream: async function* () { for (const w of words) { yield JSON.stringify({ choices: [{ delta: { content: w + ' ' } }] }); await new Promise(r => setTimeout(r, 140)); } yield '[DONE]'; } }; },
  };
}

// ---- lcpp: lcppd's API (instances, catalog, preflight, chat stream, downloads, relay, settings) ----
function lcppMock(m) {
  const { ok, upstream, svcById, now, GB } = m;
  const CAT = [
    { id: 'gemma-4-26B-it', nicknames: ['gemma4-26B'], path: 'Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf', location: 'models', size_bytes: 18.2 * GB, ok: true, problems: [], capabilities: { vision: true, speculative: true, split: false }, effective: { 'ctx-size': 262144 } },
    { id: 'minicpm-5-2B', nicknames: ['MiniCPM5-2B'], path: 'MiniCPM5-2B/MiniCPM5-2B-Q8_0.gguf', location: 'models', size_bytes: 2.7 * GB, ok: true, problems: [], capabilities: { vision: false, speculative: false, split: false }, effective: { 'ctx-size': 131072 } },
  ];
  const inst = new Map([['gemma4-26b-7071', { name: 'gemma4-26b-7071', kind: 'single', model_id: 'gemma-4-26B-it', models: [], port: 7071, url: 'http://127.0.0.1:7071/v1', state: 'ready', started_ts: now() - 5400, rss_bytes: 18.6 * GB, params: { 'ctx-size': 32768, 'cache-type-k': 'q8_0', 'cache-type-v': 'q8_0' }, capabilities: { vision: true, speculative: true }, relay: { state: 'registered', alias: 'gemma4-26B', key: 'lcpp:7071', health: 'healthy' }, last_error: null }]]);
  const view = () => [...inst.values()].map(i => ({ ...i, models: [], argv: [] }));
  const find = n => { const i = inst.get(n); if (!i) throw upstream(404, `Instance ${n} not found`); return i; };
  const est = id => (CAT.find(c => c.id === id)?.size_bytes || 0) * 1.4;
  let portN = 7072;
  return {
    'GET /api/health': () => ok({ ok: true }),
    'GET /api/overview': () => ok({ instances: view(), system: {}, relay: { reachable: true } }),
    'GET /api/instances': () => ok(view()),
    'POST /api/instances/preflight': ({ json }) => { const e = est(json?.model_id); const errors = CAT.some(c => c.id === json?.model_id) ? [] : [{ code: 'model_not_found', detail: 'Pick a model', field: 'model_id' }];
      return ok({ port: json?.port || portN, port_ok: true, name: json?.name || `${(json?.model_id || 'model').toLowerCase()}-${json?.port || portN}`, name_ok: true, estimated_bytes: e, available_bytes: 64 * GB, warnings: e > 60 * GB ? ['Little headroom for other work.'] : [], errors, argv: [] }); },
    'POST /api/instances': ({ json }) => { const c = CAT.find(x => x.id === json?.model_id); if (!c) throw upstream(404, 'Model is not in the catalog');
      const name = json.name || `${c.id.toLowerCase()}-${portN}`, i = { name, kind: 'single', model_id: c.id, models: [], port: portN, url: `http://127.0.0.1:${portN}/v1`, state: 'starting', started_ts: now(), rss_bytes: 0.4 * GB, params: json.params || {}, capabilities: c.capabilities, relay: json.relay?.enabled ? { state: 'pending', alias: json.relay.alias || c.nicknames[0] } : { state: 'off' }, last_error: null };
      portN++; inst.set(name, i); setTimeout(() => { i.state = 'ready'; i.rss_bytes = c.size_bytes * 1.1; if (i.relay.state === 'pending') i.relay.state = 'registered'; }, 2500);
      svcById('lcpp').used += c.size_bytes; return ok({ instance: i, warnings: [] }, 201); },
    'DELETE /api/instances/{name}': ({ pp, query }) => { const i = find(pp.name); if (query.dismiss) { inst.delete(pp.name); return { status: 204 }; } inst.delete(pp.name); svcById('lcpp').used = Math.max(0, svcById('lcpp').used - i.rss_bytes); return ok({ ...i, state: 'stopping' }, 202); },
    'POST /api/instances/{name}/restart': ({ pp }) => ok({ ...find(pp.name), state: 'starting' }, 202),
    'POST /api/instances/{name}/relay': ({ pp, json }) => { const i = find(pp.name); i.relay = { state: 'registered', alias: json?.alias || i.model_id }; return ok(i); },
    'DELETE /api/instances/{name}/relay': ({ pp }) => { const i = find(pp.name); i.relay = { state: 'off' }; return ok(i); },
    'GET /api/instances/{name}/logs': ({ pp }) => ok({ lines: Array.from({ length: 20 }, (_, k) => ({ ts: now() - 20 + k, text: `[${pp.name}] srv  update_slots: all slots are idle (${k})`, stream: 'stdout' })) }),
    'GET /api/instances/{name}/logs/stream': ({ pp }) => ({ stream: async function* () { for (let i = 0; i < 200; i++) { yield JSON.stringify({ ts: now(), text: `[${pp.name}] slot ${i % 4} | prompt ${Math.floor(200 + Math.random() * 3000)} tok, gen ${Math.floor(20 + Math.random() * 400)} tok, ${(30 + Math.random() * 20).toFixed(1)} t/s` }); await new Promise(r => setTimeout(r, 450)); } } }),
    'POST /api/chat': ({ json }) => { if (!json?.request?.messages?.length) throw upstream(400, 'messages are required');
      const words = 'Shared pool of light — weights and frames drink from one well, nothing waits its turn.'.split(' ');
      return { stream: async function* () { for (const w of words) { yield JSON.stringify({ choices: [{ delta: { content: w + ' ' } }] }); await new Promise(r => setTimeout(r, 90)); } yield JSON.stringify({ lcpp_metrics: { ttft_ms: 120, tokens_per_s: 38 + Math.round(Math.random() * 10), prompt_tokens: 24, completion_tokens: words.length, total_ms: 1500 } }); } }; },
    'GET /api/models': () => ok({ models: CAT.map(c => ({ ...c, running: view().filter(i => i.model_id === c.id).map(i => i.name) })), defaults: {} }),
    'GET /api/models/discovered': () => ok([{ path: 'Qwen3-4B/Qwen3-4B-Q4_K_M.gguf', size_bytes: 2.5 * GB, suggested_id: 'qwen3-4b', dir: 'Qwen3-4B' }]),
    'PUT /api/models/{id}': ({ pp, json }) => { CAT.push({ id: pp.id, nicknames: json?.nicknames || [], path: json?.path, location: 'models', size_bytes: 2.5 * GB, ok: true, problems: [], capabilities: { vision: false, speculative: false, split: false }, effective: {} }); return ok(CAT.at(-1)); },
    'DELETE /api/models/{id}': ({ pp }) => { const k = CAT.findIndex(c => c.id === pp.id); if (k >= 0) CAT.splice(k, 1); return { status: 204 }; },
    'GET /api/downloads': () => ok([]),
    'POST /api/downloads/resolve': ({ json }) => ok({ repo: json?.input || 'owner/repo', revision: 'main', gated: false, choices: [{ id: 'model-Q4_K_M.gguf', label: 'model.gguf', quant: 'Q4_K_M', size_bytes: 2.5 * GB, complete: true, suggested_id: 'model' }], mmproj: [], drafts: [], selected: 'model-Q4_K_M.gguf', suggested_dir: 'Model', free_bytes: 480 * GB }),
    'POST /api/downloads': () => ok({ id: 'dl1', state: 'queued' }, 202),
    'GET /api/relay': () => ok({ status: { url: 'http://127.0.0.1:4000', reachable: true, latency_ms: 2, error: null },
      owned: view().filter(i => i.relay.state === 'registered').map(i => ({ key: `lcpp:${i.port}`, instance: i.name, alias: i.relay.alias, models: [i.model_id], health: 'healthy', registered_ts: now() - 600, orphan: false })),
      others: [{ name: 'skynet', health: 'healthy', base_url: 'http://127.0.0.1:9090/v1' }] }),
    'POST /api/relay/test': () => ok({ reachable: true, latency_ms: 2 }),
    'GET /api/settings': () => ok({ daemon: { port: 7710 }, llama: { binary: 'runtime/llama.cpp/bin/current/llama-server', environment: { AMD_VULKAN_ICD: 'RADV' }, server_params: { jinja: true } }, ports: { start: 7071, end: 7199 }, relay: { url: 'http://127.0.0.1:4000', dashboard_url: 'http://127.0.0.1:4000/', auto_register: true }, scan_dirs: ['models', '~/Models'] }),
    'PUT /api/settings': ({ json }) => ok(json),
    'GET /api/status': () => ok({ loaded: inst.size > 0, busy: false, stats: svcById('lcpp').stats }),
  };
}
