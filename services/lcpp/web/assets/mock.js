import { GB, MB, fmtGB, nowS, clone, NAME_RE, modelNick } from './utils.js';
import { ApiError } from './api.js';

/* ============================================================
   api (mock) — in-memory daemon with simulated time.
   Same validation rules and shapes as the real one.
   ============================================================ */
export function createMockApi() {
  let speed = 1, daemonDown = false;
  const timers = new Set();
  const later = (ms, fn) => { const id = setTimeout(() => { timers.delete(id); fn(); }, ms / speed); timers.add(id); return id; };
  const clearAll = () => { timers.forEach(clearTimeout); timers.clear(); };
  const rnd = (a, b) => a + Math.random() * (b - a);

  // ---- seed: this is the real machine ----
  const MODEL_DIR = 'models';
  const FS = new Map(); // path -> bytes
  const catalogSeed = () => [
    { id: 'gemma-4-26B-it', nicknames: ['gemma4-26B'], path: `${MODEL_DIR}/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf`, mmproj: `${MODEL_DIR}/Gemma4-26B/mmproj-Gemma4-26B-A4B-BF16.gguf`, draft: `${MODEL_DIR}/Gemma4-26B/mtp-gemma-4-26B-A4B-it.gguf`, spec_type: 'draft-mtp', overrides: { 'gpu-layers-draft': 999 } },
    { id: 'gemma-4-19B-it', nicknames: ['gemma4-19B'], path: `${MODEL_DIR}/Gemma4-19B/gemma-4-19B-A4B-it-Q4_K_M.gguf`, overrides: {} },
    { id: 'gemma-4-E4B-it', nicknames: ['gemma4-E4B'], path: `${MODEL_DIR}/Gemma4-E4B/Gemma4-E4B.gguf`, overrides: {} },
    { id: 'ornith1-35B', nicknames: ['ornith1-35B'], path: `${MODEL_DIR}/Ornith1-35B/ornith-1.0-35b-Q4_K_M.gguf`, overrides: {} },
    { id: 'minicpm-5-2B', nicknames: ['MiniCPM5-2B'], path: `${MODEL_DIR}/MiniCPM5-2B/MiniCPM5-2B-Q8_0.gguf`, overrides: { 'ctx-size': 131072 } },
    { id: 'nemotron-3-super', nicknames: ['nemotron3-super'], path: '~/Models/Nemotron3Super/Nemotron3-120B-Q4KM-00001-of-00003.gguf', overrides: {} },
  ];
  const fsSeed = () => {
    FS.clear();
    FS.set(`${MODEL_DIR}/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf`, 16796015520); FS.set(`${MODEL_DIR}/Gemma4-26B/mmproj-Gemma4-26B-A4B-BF16.gguf`, 1194827776); FS.set(`${MODEL_DIR}/Gemma4-26B/mtp-gemma-4-26B-A4B-it.gguf`, 251937728);
    FS.set(`${MODEL_DIR}/Gemma4-19B/gemma-4-19B-A4B-it-Q4_K_M.gguf`, 12291399776); FS.set(`${MODEL_DIR}/Gemma4-E4B/Gemma4-E4B.gguf`, 11302792672);
    FS.set(`${MODEL_DIR}/Ornith1-35B/ornith-1.0-35b-Q4_K_M.gguf`, 21166757408); FS.set(`${MODEL_DIR}/MiniCPM5-2B/MiniCPM5-2B-Q8_0.gguf`, 2679710688);
    FS.set('~/Models/Nemotron3Super/Nemotron3-120B-Q4KM-00001-of-00003.gguf', 7872576); FS.set('~/Models/Nemotron3Super/Nemotron3-120B-Q4KM-00002-of-00003.gguf', 49932117344); FS.set('~/Models/Nemotron3Super/Nemotron3-120B-Q4KM-00003-of-00003.gguf', 32601178560);
    FS.set('~/Models/Qwen3.6-27B-Q4KM.gguf', 17106773120); FS.set('~/Models/Serenity-12B-Q4_K_M.gguf', 7381382208); FS.set('~/Models/Serenity-26B-A4B-Q4_K_M.gguf', 16796016576);
  };
  const OTHER_PORTS = { 4000: 'Relay', 4096: 'opencode (pid 2231)', 5432: 'postgres (pid 1180)', 6379: 'redis (pid 1204)', 7710: 'lcpp daemon' };
  const RESERVED = { 4000: 'reserved (Relay)', 7710: 'reserved (lcpp daemon)' };
  const S = {};
  function baseState() {
    fsSeed();
    S.defaults = { 'ctx-size': 262144, 'cache-type-k': 'q8_0', 'cache-type-v': 'q8_0', 'n-gpu-layers': 999, 'flash-attn': true, 'no-mmap': false, 'batch-size': 2048, 'ubatch-size': 512 };
    S.catalog = catalogSeed();
    S.settings = { daemon: { port: 7710 }, llama: { binary: 'LlamaCPP/bin/current/llama-server', environment: { AMD_VULKAN_ICD: 'RADV', GPU_MAX_HW_QUEUES: '8' }, server_params: { jinja: true, reasoning: 'auto', 'reasoning-format': 'deepseek', 'reasoning-budget': -1 } }, ports: { start: 7071, end: 7199 }, relay: { url: 'http://127.0.0.1:4000', dashboard_url: 'http://127.0.0.1:4000/', auto_register: true }, scan_dirs: ['models/', '~/Models'] };
    S.relayReachable = true;
    S.instances = []; S.registrations = []; S.logs = new Map(); S.listeners = new Map(); S.recent = [];
    S.others = [
      { name: 'skynet', alias: null, server_type: 'vllm', health: 'failed', base_url: 'http://127.0.0.1:9090/v1' },
      { name: 'opencode', alias: 'agent', server_type: 'opencode', health: 'healthy', base_url: 'http://127.0.0.1:4096' },
    ];
    S.daemonStart = nowS() - 3600 * 5 - 60 * 12;
    S.chatUsed = 0;
    S.downloads = [];
  }
  // ---- models ----
  function splitInfo(path) { const m = /-(\d{5})-of-(\d{5})\.gguf$/.exec(path); return m ? { idx: +m[1], n: +m[2], base: path.slice(0, m.index) } : null; }
  function modelFiles(m) {
    const files = []; const sp = splitInfo(m.path);
    if (sp) for (let i = 1; i <= sp.n; i++) { const p = `${sp.base}-${String(i).padStart(5, '0')}-of-${String(sp.n).padStart(5, '0')}.gguf`; files.push({ role: i === 1 ? 'model' : 'split', path: p, size_bytes: FS.get(p) ?? null, exists: FS.has(p), part: `${i}/${sp.n}` }); }
    else files.push({ role: 'model', path: m.path, size_bytes: FS.get(m.path) ?? null, exists: FS.has(m.path) });
    if (m.mmproj) files.push({ role: 'mmproj', path: m.mmproj, size_bytes: FS.get(m.mmproj) ?? null, exists: FS.has(m.mmproj) });
    if (m.draft) files.push({ role: 'draft', path: m.draft, size_bytes: FS.get(m.draft) ?? null, exists: FS.has(m.draft) });
    return files;
  }
  function modelView(m) {
    const files = modelFiles(m); const problems = files.filter(f => !f.exists).map(f => `${f.role} file not found: ${f.path}`);
    const overrides = { ...m.overrides }; if (m.mmproj) overrides.mmproj = m.mmproj; if (m.draft) { overrides['model-draft'] = m.draft; overrides['spec-type'] = m.spec_type || 'draft'; }
    return { id: m.id, nicknames: [...m.nicknames], path: m.path, location: m.path.startsWith(MODEL_DIR + '/') ? 'models' : 'external', files, size_bytes: files.reduce((a, f) => a + (f.size_bytes || 0), 0), ok: problems.length === 0, problems, capabilities: { vision: !!m.mmproj, speculative: !!m.draft, split: !!splitInfo(m.path) }, overrides, effective: { ...S.defaults, ...overrides }, running: S.instances.filter(i => i.model_id === m.id || (i.models || []).some(x => x.id === m.id)).map(i => i.name) };
  }
  const findModel = id => S.catalog.find(m => m.id === id || m.nicknames.includes(id));
  // ---- system ----
  function system() {
    const rss = S.instances.reduce((a, i) => a + (i.rss_bytes || 0), 0); const base = 17.4 * GB; const total = 121 * GB; const used = Math.min(total, base + rss);
    return { memory: { total_bytes: total, used_bytes: used, available_bytes: total - used }, gpu: { name: 'AMD Radeon 8060S (Strix Halo)', vram_total_bytes: 4 * GB, vram_used_bytes: 0.6 * GB, gtt_total_bytes: 121.5 * GB, gtt_used_bytes: 0.9 * GB + rss }, daemon: { version: '0.1.0', pid: 41337, rss_bytes: 48 * MB, uptime_s: nowS() - S.daemonStart, port: S.settings.daemon.port }, llama: { build: 'b9692', binary: S.settings.llama.binary, binary_ok: true } };
  }
  const relayStatus = () => ({ url: S.settings.relay.url, dashboard_url: S.settings.relay.dashboard_url, reachable: S.relayReachable, latency_ms: S.relayReachable ? Math.round(rnd(2, 6)) : null, error: S.relayReachable ? null : `connect ECONNREFUSED ${S.settings.relay.url.replace(/^https?:\/\//, '')}` });
  // ---- logs ----
  function log(name, text, stream = 'stderr') { const line = { ts: nowS(), text, stream }; let arr = S.logs.get(name); if (!arr) S.logs.set(name, arr = []); arr.push(line); if (arr.length > 5000) arr.shift(); (S.listeners.get(name) || new Set()).forEach(fn => fn(line)); const i = S.instances.find(x => x.name === name); if (i && (i.state === 'starting' || i.state === 'failed')) i.last_log_lines = arr.slice(-5).map(l => l.text); }
  // ---- ports & names ----
  const portUsedBy = port => { const i = S.instances.find(x => x.port === port); if (i) return `lcpp instance ${i.name}`; if (RESERVED[port]) return null; return OTHER_PORTS[port] || null; };
  function portCheck(port) { if (RESERVED[port]) return { ok: false, reason: RESERVED[port], code: 'port_reserved' }; const by = portUsedBy(port); if (by) return { ok: false, reason: `in use by ${by}`, code: 'port_in_use' }; if (port < 1024 || port > 65535) return { ok: false, reason: 'outside 1024–65535', code: 'invalid_param' }; return { ok: true, reason: null }; }
  function freePort() { const { start, end } = S.settings.ports; for (let p = start; p <= end; p++) if (portCheck(p).ok) return p; return end; }
  function nameCheck(name, self) { if (!NAME_RE.test(name)) return { ok: false, reason: 'lowercase letters, digits and dashes; 1–48 chars', code: 'invalid_name' }; if (S.instances.some(i => i.name === name && i !== self)) return { ok: false, reason: 'already used by a running instance', code: 'name_taken' }; return { ok: true, reason: null }; }
  // ---- params & argv ----
  const kvBytes = (ctx, p) => ctx * 96 * 1024 * ((p['cache-type-k'] === 'q8_0' ? 0.5 : p['cache-type-k'] === 'q4_0' ? 0.25 : 1) + (p['cache-type-v'] === 'q8_0' ? 0.5 : p['cache-type-v'] === 'q4_0' ? 0.25 : 1)) / 2;
  function specModels(spec) { if (spec.kind === 'router') { const ids = spec.model_ids && spec.model_ids.length ? spec.model_ids : S.catalog.map(m => m.id); return ids.map(findModel).filter(Boolean); } const m = findModel(spec.model_id); return m ? [m] : []; }
  function effective(model, over) { return { ...S.defaults, ...(model ? modelView(model).overrides : {}), ...(over || {}) }; }
  function argvFor(spec, port, name) {
    const models = specModels(spec); const p = effective(models[0], spec.params);
    const a = [S.settings.llama.binary, '--host', '127.0.0.1', '--port', String(port), '--alias', name];
    if (spec.kind === 'router') { a.push('--models-preset', 'LlamaCPP/generated/models.ini', '--models-max', String(spec.models_max || 1)); }
    else if (models[0]) { a.push('-m', models[0].path); }
    const sp = { ...S.settings.llama.server_params, ...p };
    for (const [k, v] of Object.entries(sp)) { if (v === null || v === undefined || v === false || v === '') continue; if (v === true) a.push('--' + k); else a.push('--' + k, String(v)); }
    return a;
  }
  function preflightCalc(spec) {
    const models = specModels(spec); const errors = [], warnings = [];
    const port = spec.port || freePort(); const pc = portCheck(port);
    if (!pc.ok) errors.push({ code: pc.code, detail: `Port ${port}: ${pc.reason}`, field: 'port' });
    const autoName = spec.kind === 'router' ? `router-${port}` : `${(models[0] ? modelNick(models[0]) : 'model').toLowerCase()}-${port}`;
    const name = (spec.name || autoName).trim(); const nc = nameCheck(name);
    if (!nc.ok) errors.push({ code: nc.code, detail: `Name "${name}": ${nc.reason}`, field: 'name' });
    if (spec.kind === 'single' && !models[0]) errors.push({ code: 'model_not_found', detail: `Model "${spec.model_id || ''}" is not in the catalog`, field: 'model' });
    for (const m of models) { const mv = modelView(m); if (!mv.ok) errors.push({ code: 'model_files_missing', detail: `${m.id}: ${mv.problems[0]}`, field: 'model' }); }
    const loaded = spec.kind === 'router' ? [...models].sort((a, b) => modelView(b).size_bytes - modelView(a).size_bytes).slice(0, spec.models_max || 1) : models;
    let est = 0; for (const m of loaded) { const p = effective(m, spec.params); est += modelView(m).size_bytes + kvBytes(+p['ctx-size'] || 4096, p); }
    const avail = system().memory.available_bytes;
    if (est > avail) warnings.push(`Estimated ${fmtGB(est)} needed, ${fmtGB(avail)} available. Loading may fail or swap.`);
    else if (est > avail * 0.85) warnings.push(`Estimated ${fmtGB(est)} needed, ${fmtGB(avail)} available. Little headroom for other work.`);
    if (spec.relay && spec.relay.enabled && !S.relayReachable) warnings.push('Relay is unreachable. The instance will register when Relay comes back.');
    return { port, port_ok: pc.ok, port_reason: pc.reason, suggested_port: freePort(), name, name_ok: nc.ok, name_reason: nc.reason, estimated_bytes: est, available_bytes: avail, warnings, errors, argv: argvFor(spec, port, name) };
  }
  // ---- instances ----
  const instView = i => { const { _t, ...rest } = i; return clone(rest); };
  const pub = i => instView(i);
  function loadSeq(i, model, onReady) {
    const size = modelView(model).size_bytes; const dur = 2000 + 400 * (size / GB); const t0 = Date.now();
    log(i.name, `main: llama-server build ${'b9692'} starting on port ${i.port}`); log(i.name, `srv  load_model: loading model '${model.path}'`);
    const steps = [[0.05, `llama_model_loader: loaded meta data with 41 key-value pairs and ${Math.round(size / 1e7)} tensors from ${model.path}`], [0.15, `print_info: file size = ${fmtGB(size)} (${(4.7).toFixed(2)} BPW)`], [0.3, 'load_tensors: offloading 999 layers to GPU'], [0.45, `load_tensors: Vulkan0 model buffer size = ${(size / MB).toFixed(2)} MiB`], [0.6, `llama_context: n_ctx = ${i.params['ctx-size']}`], [0.7, `llama_kv_cache: Vulkan0 KV buffer size = ${(kvBytes(+i.params['ctx-size'], i.params) / MB).toFixed(2)} MiB`], [0.85, `srv  init: initializing slots, n_slots = ${i.params.parallel || 1}`], [0.92, 'main: model loaded']];
    const failMid = model.id === 'ornith1-35B' && S.instances.some(x => x !== i && x.model_id === 'gemma-4-26B-it' && x.state === 'ready') && S.instances.some(x => x !== i && x.state === 'ready' && x.model_id !== 'gemma-4-26B-it' && (x.rss_bytes || 0) > 10 * GB);
    const ticks = () => { if (i.state !== 'starting' || i._t !== t0) return; const f = Math.min(1, (Date.now() - t0) / (dur / speed)); i.rss_bytes = Math.round(size * f * 1.08); if (failMid && f >= 0.6) { i.state = 'failed'; i.last_error = 'failed to allocate buffer: out of device memory'; log(i.name, 'ggml_vulkan: failed to allocate buffer: out of device memory'); log(i.name, 'llama_model_load: error loading model: unable to allocate Vulkan0 buffer'); log(i.name, 'srv  load_model: failed to load model'); i.pid = null; i.rss_bytes = null; if (i.relay.state !== 'off') { i.relay.state = 'error'; i.relay.error = 'instance never became ready'; } return; } while (steps.length && f >= steps[0][0]) log(i.name, steps.shift()[1]); if (f < 1) later(250, ticks); else onReady(); };
    later(250, ticks);
  }
  function becomeReady(i) { i.state = 'ready'; i.ready_ts = nowS(); i.last_log_lines = []; log(i.name, `main: server is listening on http://127.0.0.1:${i.port}`, 'stdout'); log(i.name, 'srv  update_slots: all slots are idle', 'stdout'); if (i.relay.state === 'pending') scheduleRegister(i); }
  function scheduleRegister(i) { later(1000, () => { if (i.state !== 'ready' || i.relay.state !== 'pending') return; if (!S.relayReachable) return; const conflict = S.others.find(o => (o.alias || o.name) === i.relay.alias) || S.registrations.find(r => r.alias === i.relay.alias && r.key !== i.relay.key); if (conflict) { i.relay.state = 'error'; i.relay.error = `alias "${i.relay.alias}" already used by endpoint ${conflict.name || conflict.instance}`; return; } i.relay.state = 'registered'; i.relay.health = 'healthy'; i.relay.error = null; if (!S.registrations.some(r => r.key === i.relay.key)) S.registrations.push({ key: i.relay.key, instance: i.name, alias: i.relay.alias, models: i.kind === 'router' ? i.models.map(m => m.id) : [i.model_id], health: 'healthy', registered_ts: nowS(), orphan: false, endpoint_id: 'ep_' + Math.random().toString(36).slice(2, 8) }); log(i.name, `lcpp: registered with Relay as "${i.relay.alias}" (${i.relay.key})`, 'stdout'); }); }
  function makeInstance(spec, pf, opts = {}) {
    const models = specModels(spec); const model = models[0]; const params = effective(model, spec.params);
    const i = { name: pf.name, kind: spec.kind, model_id: spec.kind === 'single' ? model.id : null, models: spec.kind === 'router' ? models.map((m, k) => ({ id: m.id, loaded: k === 0 })) : [], host: '127.0.0.1', port: pf.port, url: `http://127.0.0.1:${pf.port}/v1`, state: 'starting', pid: 40000 + Math.floor(Math.random() * 20000), started_ts: nowS(), ready_ts: null, rss_bytes: 120 * MB, params: spec.kind === 'router' ? { ...params, 'models-max': spec.models_max || 1 } : params, argv: pf.argv, capabilities: { vision: !!(model && model.mmproj) && spec.kind === 'single', speculative: !!(model && model.draft) && spec.kind === 'single' }, relay: { state: spec.relay && spec.relay.enabled ? 'pending' : 'off', key: spec.relay && spec.relay.enabled ? `lcpp:${pf.port}` : null, alias: spec.relay && spec.relay.enabled ? (spec.relay.alias || modelNick(model)) : null, health: null, error: null }, last_error: null, last_log_lines: [], _t: Date.now() };
    S.instances.push(i); S.logs.set(i.name, []);
    if (!opts.silent) { S.recent = [clone(spec), ...S.recent.filter(r => JSON.stringify(r) !== JSON.stringify(spec))].slice(0, 5); }
    startInstance(i);
    return i;
  }
  function startInstance(i) { i._t = Date.now(); const model = i.kind === 'router' ? findModel(i.models[0].id) : findModel(i.model_id); loadSeq(i, model, () => becomeReady(i)); }
  function removeInstance(i) { S.instances = S.instances.filter(x => x !== i); S.registrations = S.registrations.filter(r => r.instance !== i.name); }
  function stopInstance(i, then) { i.state = 'stopping'; log(i.name, 'srv  stop: shutting down'); later(1500, () => { if (i.state !== 'stopping') return; log(i.name, 'main: exited', 'stdout'); if (then) then(); else removeInstance(i); }); }
  const need = name => { const i = S.instances.find(x => x.name === name); if (!i) throw new ApiError(404, `Instance "${name}" not found`, 'instance_not_found'); return i; };
  // ---- scenarios ----
  function seedInstance(spec, opts) { const pf = preflightCalc(spec); const i = makeInstance(spec, pf, { silent: true }); if (opts.ready) { clearAll(); i.state = 'ready'; i.started_ts = nowS() - (opts.uptime || 0); i.ready_ts = i.started_ts + 30; i.rss_bytes = opts.rss; i.last_log_lines = []; const m = findModel(i.model_id || i.models[0].id); S.logs.set(i.name, [`main: llama-server build b9692 starting on port ${i.port}`, `srv  load_model: loading model '${m.path}'`, 'load_tensors: offloading 999 layers to GPU', `llama_context: n_ctx = ${i.params['ctx-size']}`, 'main: model loaded', `main: server is listening on http://127.0.0.1:${i.port}`, 'srv  update_slots: all slots are idle'].map((t, k) => ({ ts: i.started_ts + k * 3, text: t, stream: k > 4 ? 'stdout' : 'stderr' }))); if (i.relay.state === 'pending') { i.relay.state = 'registered'; i.relay.health = opts.health || 'healthy'; S.registrations.push({ key: i.relay.key, instance: i.name, alias: i.relay.alias, models: i.kind === 'router' ? i.models.map(x => x.id) : [i.model_id], health: opts.health || 'healthy', registered_ts: i.ready_ts + 1, orphan: false, endpoint_id: 'ep_' + i.port }); } } return i; }
  function reset(kind) {
    clearAll(); baseState();
    S.recent = [{ kind: 'single', model_id: 'gemma-4-26B-it', port: 7071, relay: { enabled: true, alias: 'gemma4-26B' } }, { kind: 'single', model_id: 'minicpm-5-2B', params: { 'ctx-size': 131072 }, relay: { enabled: true, alias: 'MiniCPM5-2B' } }, { kind: 'router', model_ids: ['gemma-4-19B-it', 'gemma-4-E4B-it', 'minicpm-5-2B'], models_max: 1, relay: { enabled: false } }];
    if (kind === 'empty') return;
    seedInstance({ kind: 'single', model_id: 'gemma-4-26B-it', port: 7071, relay: { enabled: true, alias: 'gemma4-26B' } }, { ready: true, uptime: 2 * 3600 + 14 * 60, rss: 18.6 * GB });
    if (kind !== 'busy') return;
    seedInstance({ kind: 'router', model_ids: ['gemma-4-19B-it', 'gemma-4-E4B-it', 'minicpm-5-2B'], models_max: 1, port: 7080, name: 'lab-router-7080', relay: { enabled: true, alias: 'agent' } }, { ready: true, uptime: 41 * 60, rss: 12.9 * GB });
    const r = S.instances.find(x => x.name === 'lab-router-7080'); r.relay.state = 'error'; r.relay.error = 'alias "agent" already used by endpoint opencode'; r.relay.health = null; S.registrations = S.registrations.filter(x => x.instance !== r.name);
    seedInstance({ kind: 'single', model_id: 'gemma-4-19B-it', port: 7074, name: 'gemma4-19b-7074', relay: { enabled: false } }, { ready: true, uptime: 12 * 60, rss: 13.1 * GB });
    const f = seedInstance({ kind: 'single', model_id: 'ornith1-35B', port: 7073, relay: { enabled: true, alias: 'ornith1-35B' } }, { ready: false }); clearAll(); f.state = 'failed'; f.pid = null; f.rss_bytes = null; f.last_error = 'failed to allocate buffer: out of device memory'; f.relay.state = 'error'; f.relay.error = 'instance never became ready'; ['load_tensors: offloading 999 layers to GPU', 'load_tensors: Vulkan0 model buffer size = 20186.34 MiB', 'ggml_vulkan: failed to allocate buffer: out of device memory', 'llama_model_load: error loading model: unable to allocate Vulkan0 buffer', 'srv  load_model: failed to load model'].forEach(t => log(f.name, t));
    makeInstance({ kind: 'single', model_id: 'minicpm-5-2B', port: 7072, relay: { enabled: true, alias: 'MiniCPM5-2B' } }, preflightCalc({ kind: 'single', model_id: 'minicpm-5-2B', port: 7072 }), { silent: true });
    S.registrations.push({ key: 'lcpp:7088', instance: null, alias: 'serenity-12b', models: ['serenity-12B'], health: 'failed', registered_ts: nowS() - 3 * 86400, orphan: true, endpoint_id: 'ep_7088' });
  }
  reset('seed');
  // ---- chat ----
  const REPLIES = ['Here is a concise answer. llama.cpp serves an OpenAI-compatible API on each instance, so any client that speaks `/v1/chat/completions` works unchanged. Streaming returns `chat.completion.chunk` events with a `delta.content` string; the final chunk carries `finish_reason: "stop"`.', 'Sure. The quickest way to check a server is a single curl against its `/v1/models` endpoint, which lists the loaded model id, followed by a short chat completion with `max_tokens` set low. If both return within a second or two, the instance is healthy and the KV cache is warm.', 'Good question. Speculative decoding keeps the draft model resident beside the target, proposes several tokens per step and verifies them in one forward pass. On this machine it roughly doubles tokens per second for long outputs while the accepted-token rate stays above 70%.'];
  const THINK = 'The user is asking a short technical question. I should answer directly, give one concrete example, and keep it under a paragraph.';
  // ---- Hugging Face (a canned hub) + downloads ----
  const HF_REPOS = {
    'ewin-reg/MiniCPM5-1B-Agentic-Tooluse-v3-GGUF': { files: [['MiniCPM5-1B-Agentic-Tooluse-v3.F16.gguf', 2166551872], ['MiniCPM5-1B-Agentic-Tooluse-v3.Q4_K_M.gguf', 688065856], ['MiniCPM5-1B-Agentic-Tooluse-v3.Q8_0.gguf', 1153529152]] },
    'unsloth/gemma-4-E4B-it-GGUF': { gated: 'auto', files: [['gemma-4-E4B-it-Q4_K_M.gguf', 4979541312], ['gemma-4-E4B-it-Q5_K_M.gguf', 5764519232], ['gemma-4-E4B-it-Q8_0.gguf', 8190130496], ['gemma-4-E4B-it-BF16.gguf', 15048001344], ['mmproj-F16.gguf', 990257152]] },
    'openbmb/MiniCPM5-1B': { kind: 'safetensors' },
  };
  const QUANT = /[-_.](IQ\d[A-Z0-9_]*|Q\d[A-Z0-9_]*|BF16|F16|F32)$/i;
  const stemOf = n => n.replace(/\.gguf$/i, '').replace(/-\d+-of-\d+$/, '');
  const suggestId = n => stemOf(n).replace(QUANT, '').replace(/[^A-Za-z0-9.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').toLowerCase() || 'model';
  function hfRepo(repo) {
    const known = HF_REPOS[repo]; if (known) return known; const name = repo.split('/')[1];
    if (/gguf/i.test(name)) { const base = name.replace(/[-_.]?gguf$/i, ''); return { files: [['Q4_K_M', 4.9], ['Q5_K_M', 5.7], ['Q8_0', 8.5]].map(([q, g]) => [`${base}-${q}.gguf`, Math.round(g * GB)]) }; }
    const q = /awq|gptq|exl2|mlx/i.exec(name); if (q) return { kind: q[0].toLowerCase() };
    return null;
  }
  function hfParse(text) {
    const raw = (text || '').trim(); if (/^[A-Za-z0-9][\w.-]*\/[\w.-]+$/.test(raw)) return { repo: raw, revision: 'main', file: null };
    const m = /^(?:https?:\/\/)?(?:www\.)?(?:huggingface\.co|hf\.co)\/([\w.-]+\/[\w.-]+)(?:\/(resolve|blob|tree)\/([^/?#]+)(?:\/([^?#]+))?)?\/?(?:[?#].*)?$/.exec(raw);
    if (!m) throw new ApiError(400, 'Enter a Hugging Face repo (owner/name) or a huggingface.co link', 'invalid_param');
    return { repo: m[1], revision: m[3] || 'main', file: m[2] === 'tree' || !m[4] ? null : decodeURIComponent(m[4]) };
  }
  function hfChoices(r) {
    const files = (r.files || []).map(([path, size_bytes]) => ({ path, size_bytes, sha256: null }));
    const mmproj = files.filter(f => /^mmproj[-_]/i.test(f.path)), drafts = files.filter(f => /^mtp[-_]/i.test(f.path));
    const choices = files.filter(f => !mmproj.includes(f) && !drafts.includes(f)).map(f => { const q = QUANT.exec(stemOf(f.path)); return { id: f.path, label: f.path, quant: q ? q[1].toUpperCase() : null, files: [f], size_bytes: f.size_bytes, complete: true, suggested_id: suggestId(f.path) }; }).sort((a, b) => a.size_bytes - b.size_bytes);
    return { choices, mmproj, drafts };
  }
  const FREE = 812 * GB;
  function hfResolve(text) {
    const { repo, revision, file } = hfParse(text); const r = hfRepo(repo);
    if (!r) throw new ApiError(404, `Repo ${repo} (revision ${revision}) was not found on Hugging Face.`, 'hf_not_found');
    const g = hfChoices(r); const out = { repo, revision, sha: 'b8ed16e7', gated: r.gated || false, kind: 'gguf', message: null, search_url: null, ...g, selected: null, suggested_dir: repo.split('/')[1].replace(/[-_.]?gguf$/i, ''), suggested_id: null, free_bytes: FREE - S.downloads.reduce((a, j) => a + j.bytes_done, 0) };
    if (file) { const c = g.choices.find(x => x.id === file); if (!c) { if (g.mmproj.some(f => f.path === file)) throw new ApiError(400, `${file} is a projector/draft sidecar, not a model. Link the model GGUF; its sidecars are offered alongside it.`, 'invalid_param'); throw new ApiError(404, `${file} is not in ${repo} at ${revision}`, 'hf_not_found'); } out.selected = c.id; }
    else if (g.choices.length === 1) out.selected = g.choices[0].id;
    if (!g.choices.length) { const label = { safetensors: 'full-precision safetensors weights', awq: 'AWQ-quantized weights', gptq: 'GPTQ-quantized weights' }[r.kind] || `${r.kind} weights`; out.kind = r.kind; out.search_url = `https://huggingface.co/models?search=${encodeURIComponent(repo.split('/')[1])}%20gguf`; out.message = `${repo} has ${label}, not GGUF. llama-server can only run GGUF, so look for a GGUF conversion of it.`; }
    if (out.selected) out.suggested_id = g.choices.find(x => x.id === out.selected).suggested_id;
    return out;
  }
  const dlView = j => { const { _t, _model, ...rest } = j; return clone(rest); };
  const needDl = id => { const j = S.downloads.find(x => x.id === id); if (!j) throw new ApiError(404, `Download ${id} not found`, 'download_not_found'); return j; };
  function runDownload(j) {
    const t = j._t = Date.now(); j.state = 'downloading'; const rate = rnd(60, 110) * MB;
    const tick = () => {
      if (j._t !== t || j.state !== 'downloading') return; let budget = rate * 0.25;
      for (const f of j.files) { if (f.state === 'done' || budget <= 0) continue; f.state = 'downloading'; const n = Math.min(budget, f.size_bytes - f.done_bytes); f.done_bytes += n; budget -= n; if (f.done_bytes >= f.size_bytes) { f.state = 'done'; FS.set(`${j.dir}/${f.name}`, f.size_bytes); } }
      j.bytes_done = j.files.reduce((a, f) => a + f.done_bytes, 0); j.speed_bps = Math.round(rate); j.eta_s = Math.round((j.bytes_total - j.bytes_done) / rate);
      if (j.bytes_done < j.bytes_total) { later(250, tick); return; }
      j.state = 'done'; j.speed_bps = 0; j.eta_s = null; j.finished_ts = nowS();
      if (j._model) { if (findModel(j._model.id)) j.warning = `"${j._model.id}" was added to the catalog meanwhile; add this one from Discovered GGUFs`; else S.catalog.push(j._model); }
    };
    later(250, tick);
  }
  function startDownload(spec) {
    const r = hfRepo(spec.repo || ''); if (!r) throw new ApiError(404, `Repo ${spec.repo} was not found on Hugging Face.`, 'hf_not_found');
    const g = hfChoices(r); const c = g.choices.find(x => x.id === spec.choice); if (!c) throw new ApiError(400, `${spec.choice || 'no file'} is not a GGUF model in ${spec.repo}`, 'invalid_param');
    const dir = String(spec.dir || '').trim(); if (!/^[A-Za-z0-9][\w.+-]{0,127}$/.test(dir)) throw new ApiError(400, 'folder must be one name (letters, digits, . _ + -), no slashes', 'invalid_param');
    const id = String(spec.model_id || c.suggested_id); const nicks = (spec.nicknames || []).filter(Boolean);
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id)) throw new ApiError(400, 'id must be a slug (letters, digits, dots, dashes, underscores)', 'invalid_param');
    if (S.catalog.some(m => m.id === id) || S.downloads.some(j => (j.state === 'queued' || j.state === 'downloading') && j.model_id === id)) throw new ApiError(400, `"${id}" is already in the catalog`, 'invalid_param');
    const clash = S.catalog.find(m => nicks.some(n => m.nicknames.includes(n) || m.id === n)); if (clash) throw new ApiError(400, `a name is already used by model ${clash.id}`, 'invalid_param');
    const side = [g.mmproj.find(f => f.path === spec.mmproj), g.drafts.find(f => f.path === spec.draft)];
    const files = [...c.files, ...side.filter(Boolean)].map(f => ({ path: f.path, name: f.path.split('/').pop(), size_bytes: f.size_bytes, done_bytes: 0, state: 'queued' }));
    const at = `${MODEL_DIR}/${dir}`, total = files.reduce((a, f) => a + f.size_bytes, 0);
    const j = { id: Math.random().toString(16).slice(2, 10), repo: spec.repo, revision: spec.revision || 'main', label: c.label, dir: at, state: 'queued', error: null, warning: null, model_id: id, bytes_total: total, bytes_done: 0, speed_bps: 0, eta_s: null, created_ts: nowS(), finished_ts: null, files,
      _model: { id, nicknames: nicks, path: `${at}/${files[0].name}`, mmproj: side[0] ? `${at}/${side[0].path}` : null, draft: side[1] ? `${at}/${side[1].path}` : null, spec_type: side[1] ? 'draft-mtp' : null, overrides: {} } };
    S.downloads.unshift(j); runDownload(j); return dlView(j);
  }

  // ---- the api ----
  const guard = () => { if (daemonDown) throw new ApiError(0, 'lcpp daemon not responding', 'network'); };
  const wait = (ms = 60) => new Promise(r => setTimeout(r, ms / speed));
  const call = async fn => { guard(); await wait(rnd(30, 90)); guard(); return fn(); };
  const api = {
    getOverview: () => call(() => ({ instances: S.instances.map(pub), system: system(), relay: relayStatus() })),
    listInstances: () => call(() => S.instances.map(pub)),
    getInstance: n => call(() => pub(need(n))),
    preflight: spec => call(() => preflightCalc(spec)),
    launch: spec => call(() => { const pf = preflightCalc(spec); if (pf.errors.length) { const e = pf.errors[0]; throw new ApiError(409, e.detail, e.code); } if (spec.save_preset) S.recent.unshift({ ...clone(spec), name: spec.save_preset }); const i = makeInstance(spec, pf); return { instance: pub(i), warnings: pf.warnings }; }),
    stop: n => call(() => { const i = need(n); if (i.state === 'failed') { removeInstance(i); return pub(i); } stopInstance(i); return pub(i); }),
    stopAll: () => call(() => { const names = []; for (const i of [...S.instances]) { if (i.state === 'failed') { removeInstance(i); continue; } if (i.state !== 'stopping') { stopInstance(i); names.push(i.name); } } return { stopping: names }; }),
    restart: n => call(() => { const i = need(n); const relaunch = () => { i.state = 'starting'; i.pid = 40000 + Math.floor(Math.random() * 20000); i.started_ts = nowS(); i.ready_ts = null; i.rss_bytes = 120 * MB; i.last_error = null; if (i.relay.key) { i.relay.state = 'pending'; i.relay.health = null; i.relay.error = null; S.registrations = S.registrations.filter(r => r.instance !== i.name); } startInstance(i); }; if (i.state === 'failed') relaunch(); else stopInstance(i, relaunch); return pub(i); }),
    dismiss: n => call(() => { const i = need(n); removeInstance(i); return null; }),
    routerLoad: (n, id) => call(() => { const i = need(n); if (i.kind !== 'router') throw new ApiError(400, `${n} is not a router`, 'invalid_param'); const m = i.models.find(x => x.id === id); if (!m) throw new ApiError(404, `Model "${id}" is not served by ${n}`, 'model_not_found'); m.loading = true; log(i.name, `srv  load_model: loading model '${findModel(id).path}'`); later(3000, () => { if (!m.loading) return; m.loading = false; m.loaded = true; m._at = Date.now(); const max = i.params['models-max'] || 1; const loaded = i.models.filter(x => x.loaded).sort((a, b) => (a._at || 0) - (b._at || 0)); while (loaded.length > max) { const old = loaded.shift(); old.loaded = false; log(i.name, `srv  unload_model: unloaded '${old.id}' (models-max ${max})`); } log(i.name, `srv  load_model: '${id}' loaded`, 'stdout'); }); return pub(i); }),
    routerUnload: (n, id) => call(() => { const i = need(n); const m = i.models.find(x => x.id === id); if (!m) throw new ApiError(404, `Model "${id}" is not served by ${n}`, 'model_not_found'); m.loaded = false; m.loading = false; log(i.name, `srv  unload_model: unloaded '${id}'`, 'stdout'); return pub(i); }),
    getLogs: (n, lines) => call(() => ({ lines: (S.logs.get(n) || []).slice(-(lines || 200)) })),
    streamLogs(n, onLine) { if (daemonDown) return { close() { } }; let set = S.listeners.get(n); if (!set) S.listeners.set(n, set = new Set()); set.add(onLine); return { close: () => set.delete(onLine) }; },
    publish: (n, alias) => call(() => { const i = need(n); alias = (alias || '').trim() || modelNick(findModel(i.model_id || i.models[0].id)); if (S.others.some(o => (o.alias || o.name) === alias) || S.registrations.some(r => r.alias === alias && r.instance !== n)) throw new ApiError(409, `Alias "${alias}" is already used on Relay`, 'alias_conflict'); i.relay = { state: 'pending', key: `lcpp:${i.port}`, alias, health: null, error: null }; S.registrations = S.registrations.filter(r => r.instance !== n); if (i.state === 'ready') scheduleRegister(i); return pub(i); }),
    unpublish: n => call(() => { const i = need(n); if (S.relayReachable === false && i.relay.state === 'registered') throw new ApiError(502, 'Relay unreachable: registration could not be removed', 'relay_unreachable'); S.registrations = S.registrations.filter(r => r.instance !== n); i.relay = { state: 'off', key: null, alias: null, health: null, error: null }; log(i.name, 'lcpp: unregistered from Relay', 'stdout'); return pub(i); }),
    async chat(target, request, onDelta, signal) {
      guard();
      const inst = target.type === 'instance' ? S.instances.find(x => x.name === target.name) : (() => { const r = S.registrations.find(x => x.alias === target.model); return r ? S.instances.find(x => x.name === r.instance) : null; })();
      if (target.type === 'relay' && !S.relayReachable) throw new ApiError(502, 'Relay unreachable', 'relay_unreachable');
      if (target.type === 'relay' && !inst) { if (S.others.some(o => (o.alias || o.name) === target.model)) throw new ApiError(502, `Relay routed "${target.model}" to an endpoint lcpp does not manage; that endpoint returned 503`, 'daemon_error'); throw new ApiError(404, `No routable model "${target.model}" on Relay`, 'model_not_found'); }
      if (!inst || inst.state !== 'ready') throw new ApiError(409, `Instance ${inst ? inst.name : target.name} is not ready`, 'instance_not_found');
      const abort = () => { throw new DOMException('Aborted', 'AbortError'); };
      const check = () => { if (signal && signal.aborted) abort(); if (!S.instances.includes(inst) || inst.state !== 'ready') throw new ApiError(502, `Instance ${inst.name} stopped mid-stream`, 'instance_not_found'); if (daemonDown) throw new ApiError(0, 'lcpp daemon not responding', 'network'); };
      const t0 = performance.now(); await wait(rnd(300, 900)); check();
      const think = request.chat_template_kwargs && request.chat_template_kwargs.enable_thinking; const reply = REPLIES[S.chatUsed++ % REPLIES.length];
      const maxTok = request.max_tokens || 512; let count = 0; const ttft = performance.now() - t0;
      const stream = async (text, key) => { for (const w of text.split(/(?<=\s)/)) { if (count >= maxTok) return; check(); onDelta({ id: 'chatcmpl-mock', object: 'chat.completion.chunk', choices: [{ index: 0, delta: { [key]: w }, finish_reason: null }] }); count++; await wait(25); } };
      if (think) await stream(THINK, 'reasoning_content');
      await stream(reply, 'content'); check();
      onDelta({ id: 'chatcmpl-mock', object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: count >= maxTok ? 'length' : 'stop' }] });
      const total = performance.now() - t0; const prompt = (request.messages || []).reduce((a, m) => a + Math.ceil((m.content || '').length / 4), 0) + 12;
      return { ttft_ms: Math.round(ttft), tokens_per_s: +(count / ((total - ttft) / 1000)).toFixed(1), prompt_tokens: prompt, completion_tokens: count, total_ms: Math.round(total) };
    },
    listModels: () => call(() => ({ defaults: { ...S.defaults }, models: S.catalog.map(modelView) })),
    saveModel: m => call(() => { const v = validate(m); if (v.errors.length) throw new ApiError(400, v.errors[0], 'invalid_param'); const rec = { id: m.id, nicknames: (m.nicknames || []).filter(Boolean), path: m.path, mmproj: m.mmproj || null, draft: m.draft || null, spec_type: m.spec_type || null, overrides: { ...(m.overrides || {}) } }; delete rec.overrides.mmproj; delete rec.overrides['model-draft']; delete rec.overrides['spec-type']; const k = S.catalog.findIndex(x => x.id === m.id); if (k >= 0) S.catalog[k] = rec; else S.catalog.push(rec); return modelView(rec); }),
    deleteModel: id => call(() => { const m = findModel(id); if (!m) throw new ApiError(404, `Model "${id}" not found`, 'model_not_found'); const mv = modelView(m); if (mv.running.length) throw new ApiError(409, `Model ${id} is in use by ${mv.running.join(', ')}`, 'model_in_use'); S.catalog = S.catalog.filter(x => x !== m); return null; }),
    saveDefaults: p => call(() => { S.defaults = { ...p }; return { ...S.defaults }; }),
    validateModel: m => call(() => validate(m)),
    listDiscovered: () => call(() => { const known = new Set(S.catalog.flatMap(m => modelFiles(m).map(f => f.path))); return [...FS.entries()].filter(([p]) => !known.has(p) && !/-(\d{5})-of-/.test(p)).map(([p, b]) => ({ path: p, size_bytes: b, suggested_id: p.split('/').pop().replace(/\.gguf$/i, '').replace(/[-_.]?(Q\d.*|BF16|F16)$/i, '').toLowerCase().replace(/[^a-z0-9.-]+/g, '-').replace(/-+$/, ''), dir: p.slice(0, p.lastIndexOf('/')) || '.' })); }),
    getRelay: () => call(() => { const owned = S.registrations.map(r => ({ ...r, orphan: !S.instances.some(i => i.name === r.instance), health: S.relayReachable ? r.health : 'unknown' })); return { status: relayStatus(), owned, others: clone(S.others), routable_models: [...owned.filter(r => !r.orphan).map(r => r.alias), ...S.others.map(o => o.alias || o.name)] }; }),
    testRelay: () => call(async () => { await wait(300); return relayStatus(); }),
    removeRegistration: k => call(() => { if (!S.registrations.some(r => r.key === k)) throw new ApiError(404, `Registration ${k} not found`, 'instance_not_found'); S.registrations = S.registrations.filter(r => r.key !== k); const i = S.instances.find(x => x.relay.key === k); if (i) i.relay = { state: 'off', key: null, alias: null, health: null, error: null }; return null; }),
    cleanupOrphans: () => call(() => { const removed = S.registrations.filter(r => !S.instances.some(i => i.name === r.instance)).map(r => r.key); S.registrations = S.registrations.filter(r => !removed.includes(r.key)); return { removed }; }),
    getSettings: () => call(() => clone(S.settings)),
    saveSettings: s => call(() => { if (!(s.ports.start >= 1024 && s.ports.end <= 65535 && s.ports.start < s.ports.end)) throw new ApiError(400, 'Port range must be within 1024–65535 and start before end', 'invalid_param'); if (!/^https?:\/\//.test(s.relay.url)) throw new ApiError(400, 'Relay URL must start with http:// or https://', 'invalid_param'); const restart = s.daemon.port !== S.settings.daemon.port; S.settings = clone(s); return { settings: clone(S.settings), restart_required: restart }; }),
    getRecent: () => call(() => clone(S.recent.slice(0, 5))),
    suggestPort: () => call(() => ({ port: freePort() })),
    resolveHf: input => call(async () => { await wait(rnd(250, 600)); return hfResolve(input); }),
    listDownloads: () => call(() => S.downloads.map(dlView)),
    startDownload: spec => call(() => startDownload(spec)),
    cancelDownload: id => call(() => { const j = needDl(id); if (j.state === 'queued' || j.state === 'downloading') { j._t = null; j.state = 'cancelled'; j.files.forEach(f => { if (FS.has(`${j.dir}/${f.name}`)) FS.delete(`${j.dir}/${f.name}`); f.done_bytes = 0; f.state = 'queued'; }); j.bytes_done = 0; j.speed_bps = 0; j.eta_s = null; j.finished_ts = nowS(); } return dlView(j); }),
    retryDownload: id => call(() => { const j = needDl(id); if (j.state === 'done') throw new ApiError(400, 'That download already finished', 'invalid_param'); if (j.state !== 'downloading') { j.error = null; j.finished_ts = null; runDownload(j); } return dlView(j); }),
    dismissDownload: id => call(() => { const j = needDl(id); j._t = null; S.downloads = S.downloads.filter(x => x !== j); return null; }),
  };
  function validate(m) {
    const errors = []; if (!m.id || !/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(m.id)) errors.push('id must be a slug (letters, digits, dots, dashes)'); if (S.catalog.some(x => x.id !== m.id && x.nicknames.some(n => (m.nicknames || []).includes(n)))) errors.push('a nickname is already used by another model');
    const files = modelFiles({ path: m.path || '', mmproj: m.mmproj || null, draft: m.draft || null }); if (!m.path) errors.push('model file path is required'); files.filter(f => !f.exists).forEach(f => errors.push(`${f.role}${f.part ? ' ' + f.part : ''} not found: ${f.path}`));
    return { ok: errors.length === 0, files, errors };
  }
  // ---- dev panel hooks (mock only) ----
  api.mock = {
    get relayReachable() { return S.relayReachable; }, set relayReachable(v) { S.relayReachable = !!v; if (v) S.instances.forEach(i => { if (i.relay.state === 'pending' && i.state === 'ready') scheduleRegister(i); }); else S.instances.forEach(i => { if (i.relay.state === 'registered') { i.relay.state = 'pending'; i.relay.health = null; } }); },
    get daemonDown() { return daemonDown; }, set daemonDown(v) { daemonDown = !!v; },
    get speed() { return speed; }, set speed(v) { speed = +v || 1; },
    reset,
  };
  return api;
}
