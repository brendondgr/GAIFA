// GAIFA's API for the UI: HTTP for the areas the hub serves, the mock for the rest.
// Written by us, not Claude Design (brief §6.1). The page builds it with
//   createApi({ base: window.GAIFA_API_BASE ?? null, liveAreas: window.GAIFA_LIVE_AREAS, mock: createMockApi() })
// and `?mock` in the URL forces everything to the mock.

export class ApiError extends Error {
  constructor(status, detail, code, data) { super(detail); Object.assign(this, { status, detail, code, data }); }
}

// Method → area (brief §6.1). getOverview and subscribe span areas and are handled separately.
export const METHOD_AREA = {
  getSystem: 'system', getDoctor: 'system', getHardware: 'system',
  getRepos: 'repos', fetchRepos: 'repos', repoIncoming: 'repos', updateRepo: 'repos', pinRepo: 'repos',
  getLlmEngines: 'llm', loadLlm: 'llm', unloadLlm: 'llm',
  listServices: 'services', getService: 'services', startService: 'services', stopService: 'services',
  restartService: 'services', loadService: 'services', unloadService: 'services', saveServiceConfig: 'services',
  getServiceLogs: 'logs', streamServiceLogs: 'logs',
  listOperations: 'operations',
  callService: 'proxy',
  getMemory: 'memory', planRoom: 'memory',
  getGpu: 'gpu', cancelGpuLease: 'gpu',
  listModels: 'models', getModel: 'models', saveModel: 'models', verifyModel: 'models', deleteModel: 'models',
  scanModels: 'models', addModel: 'models',
  listOutputs: 'outputs', getOutput: 'outputs', deleteOutput: 'outputs', uploadOutput: 'outputs',
  outputText: 'outputs', outputSearch: 'outputs', outputPageUrl: 'outputs',
  getSettings: 'settings', saveSettings: 'settings', getSettingsDefaults: 'settings',
  getMetrics: 'metrics', listMetricSeries: 'metrics', getTimeline: 'metrics', getOutputStats: 'metrics',
  getActivityStats: 'metrics', getJobStats: 'metrics',
  listWidgets: 'widgets', getWidget: 'widgets',
  listTools: 'tools', getToolIndex: 'tools', callTool: 'tools', getToolCall: 'tools', cancelToolCall: 'tools',
  listApprovals: 'tools', getApproval: 'tools', decideApproval: 'tools', listGrants: 'tools', revokeGrant: 'tools', listJudged: 'tools', getJudgeStatus: 'tools',
  listSessions: 'sessions', saveSession: 'sessions', renameSession: 'sessions', deleteSession: 'sessions',
  restoreSession: 'sessions', getSessionState: 'sessions',
  readWebPage: 'webpages', getWebReading: 'webpages',
  listMentions: 'mentions',
};

// HubEvent type → area, for merging live and mock event streams.
export const EVENT_AREA = {
  service: 'services', memory: 'memory', gpu: 'gpu', output: 'outputs', output_deleted: 'outputs', model: 'models', model_deleted: 'models',
  activity: 'events', job: 'events', alert: 'events', alert_cleared: 'events',
  approval: 'tools', tool_call: 'tools', grant: 'tools', grant_deleted: 'tools',
  session: 'sessions', session_step: 'sessions', repos: 'repos', settings: 'settings',
};

const enc = encodeURIComponent;

function qs(params) {
  const p = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + p.map(([k, v]) => `${enc(k)}=${enc(Array.isArray(v) ? v.join(',') : v)}`).join('&') : '';
}

function down(base) {
  return new ApiError(0, `GAIFA not responding at ${base || (globalThis.location ? location.host : '127.0.0.1:7000')}`, 'hub_error');
}

async function envelopeError(res) {
  const text = await res.text().catch(() => '');
  let j = null;
  try { j = JSON.parse(text); } catch { /* not JSON */ }
  if (j && typeof j.detail === 'string') return new ApiError(res.status, j.detail, j.code || 'hub_error', j.data);
  return new ApiError(res.status, text || res.statusText || `HTTP ${res.status}`, 'hub_error');
}

// A mod's own error, proxied unchanged: becomes upstream_error with the mod's message (brief §6.3).
async function upstreamError(res) {
  const text = await res.text().catch(() => '');
  let body = text;
  try { body = JSON.parse(text); } catch { /* keep text */ }
  const msg = (body && typeof body === 'object' && (body.detail || body.error || body.message)) || text || res.statusText;
  return new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg), 'upstream_error', { body });
}

function toForm(form) {
  if (typeof FormData !== 'undefined' && form instanceof FormData) return form;
  const fd = new FormData();
  for (const [k, v] of Object.entries(form || {})) {
    if (Array.isArray(v)) v.forEach(x => fd.append(k, x)); else if (v !== undefined && v !== null) fd.append(k, v);
  }
  return fd;
}

export function createHttpApi(base = '', { fetch: fetchFn = globalThis.fetch?.bind(globalThis), EventSource: ES = globalThis.EventSource } = {}) {
  const url = path => base + path;

  async function send(method, path, { json, body, signal, headers } = {}) {
    const init = { method, signal, headers: { ...(headers || {}) } };
    if (json !== undefined) { init.body = JSON.stringify(json); init.headers['content-type'] = 'application/json'; }
    else if (body !== undefined) init.body = body;
    try {
      return await fetchFn(url(path), init);
    } catch (e) {
      // Stopped before any answer: its own code, never status 0 (which means "GAIFA is down").
      if (e?.name === 'AbortError' || signal?.aborted) throw new ApiError(499, 'Request stopped', 'aborted');
      throw down(base);
    }
  }

  async function req(method, path, opts) {
    const res = await send(method, path, opts);
    if (!res.ok) throw await envelopeError(res);
    if (res.status === 204) return null;
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  function stream(path, onData, onError) {
    const es = new ES(url(path));
    let failed = false;
    es.onmessage = m => { let d; try { d = JSON.parse(m.data); } catch { return; } onData(d); };
    es.onerror = () => { if (failed) return; failed = true; es.close(); onError?.(down(base)); };
    return { close: () => es.close() };
  }

  async function readEvents(res, onEvent, signal) {
    const reader = res.body.getReader(), dec = new TextDecoder(), lines = [];
    let buf = '';
    for (;;) {
      if (signal?.aborted) { reader.cancel().catch(() => {}); break; }
      let chunk;
      try { chunk = await reader.read(); } catch (e) {
        // Stop pressed mid-stream: resolve with what arrived, like the mock (brief §6.4 ServiceResponse).
        if (signal?.aborted || e?.name === 'AbortError') break;
        throw down(base);
      }
      const { value, done } = chunk;
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, ''); buf = buf.slice(i + 1);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trimStart();
        lines.push(data); onEvent?.(data);
      }
    }
    return lines.join('\n');
  }

  return {
    getOverview: () => req('GET', '/api/overview'),
    getSystem: () => req('GET', '/api/system'),
    getDoctor: () => req('GET', '/api/doctor'),
    getHardware: (refresh = false) => req('GET', `/api/system/hardware${refresh ? '?refresh=true' : ''}`),
    // plan mod-repos 3.3–3.5: the mods that are their own repositories
    getRepos: (refresh = false) => req('GET', `/api/repos${refresh ? '?refresh=1' : ''}`),
    fetchRepos: id => req('POST', `/api/repos/fetch${qs({ id })}`),
    repoIncoming: id => req('GET', `/api/repos/${enc(id)}/incoming`),
    updateRepo: (id, body = {}) => req('POST', `/api/repos/${enc(id)}/update`, { json: body }),
    pinRepo: id => req('POST', `/api/repos/${enc(id)}/pin`),
    // plan llm-servers 3.4: the local LLM engines ([llm] mods)
    getLlmEngines: () => req('GET', '/api/llm/engines'),
    loadLlm: (sid, id, makeRoom = false) => req('POST', `/api/llm/${enc(sid)}/load${makeRoom ? '?make_room=1' : ''}`, { json: { id } }),
    unloadLlm: (sid, id) => req('POST', `/api/llm/${enc(sid)}/unload`, { json: id ? { id } : {} }),
    getRecentEvents: (limit = 80) => req('GET', `/api/events/recent${qs({ limit })}`),  // not in the brief: getOverview's fill-in while `overview` is mocked
    listServices: () => req('GET', '/api/services'),
    getService: id => req('GET', `/api/services/${enc(id)}`),
    startService: id => req('POST', `/api/services/${enc(id)}/start`),
    stopService: id => req('POST', `/api/services/${enc(id)}/stop`),
    restartService: id => req('POST', `/api/services/${enc(id)}/restart`),
    loadService: (id, { makeRoom = false } = {}) => req('POST', `/api/services/${enc(id)}/load${makeRoom ? '?make_room=1' : ''}`),
    unloadService: id => req('POST', `/api/services/${enc(id)}/unload`),
    getServiceLogs: (id, lines = 200) => req('GET', `/api/services/${enc(id)}/logs${qs({ lines })}`),
    streamServiceLogs: (id, onLine) => stream(`/api/services/${enc(id)}/logs/stream`, onLine),
    listOperations: id => req('GET', `/api/services/${enc(id)}/operations`),
    saveServiceConfig: (id, cfg) => req('PUT', `/api/services/${enc(id)}/config`, { json: cfg }),
    getMemory: () => req('GET', '/api/memory'),
    getGpu: () => req('GET', '/api/gpu'),  // plan 31.1: the GPU slot's holder, the waiting leases and the last 20
    cancelGpuLease: id => req('DELETE', `/api/gpu/${enc(id)}`),
    planRoom: (id, needsBytes) => req('POST', '/api/memory/plan', { json: { service: id, needs_bytes: needsBytes } }),
    listModels: (f = {}) => req('GET', `/api/models${qs(f)}`),
    getModel: id => req('GET', `/api/models/${enc(id)}`),
    saveModel: (id, patch) => req('PUT', `/api/models/${enc(id)}`, { json: patch }),
    verifyModel: id => req('POST', `/api/models/${enc(id)}/verify`),
    deleteModel: (id, { files = false } = {}) => req('DELETE', `/api/models/${enc(id)}?files=${files ? 1 : 0}`),
    scanModels: () => req('POST', '/api/models/scan'),
    addModel: input => req('POST', '/api/models', { json: input }),
    listOutputs: (f = {}) => req('GET', `/api/outputs${qs(f)}`),
    getOutput: id => req('GET', `/api/outputs/${enc(id)}`),
    deleteOutput: id => req('DELETE', `/api/outputs/${enc(id)}`),
    // A File or Blob (with .name) sent as the raw body: it becomes an output in outputs/uploads/.
    uploadOutput: file => req('POST', `/api/outputs/upload${qs({ name: file.name || 'upload' })}`, { body: file, headers: { 'content-type': file.type || 'application/octet-stream' } }),
    // Plan 24.3: a window of an output's text ({offset, limit} or {page} / {pages: '3-5'}), a search in it
    // (words, "a phrase" or /regex/), and a PDF page as an image URL (not a request).
    outputText: (id, { offset, limit, page, pages } = {}) => req('GET', `/api/outputs/${enc(id)}/text${qs({ offset, limit, page, pages })}`),
    outputSearch: (id, q, { limit } = {}) => req('GET', `/api/outputs/${enc(id)}/search${qs({ q, limit })}`),
    outputPageUrl: (id, n, { width } = {}) => url(`/api/outputs/${enc(id)}/page/${n}.png${qs({ width })}`),
    // Plan 30.8: a web page read for the user (saved as a web output, screened whole); text: also its markdown
    readWebPage: (pageUrl, { text } = {}) => req('POST', '/api/web/read', { json: { url: pageUrl, text: !!text } }),
    // Plan 48.1: what the user can @-mention (the mods' kinds: voices, workflows, engines), each with the fields it fills
    listMentions: ({ q, kind } = {}) => req('GET', `/api/mentions${qs({ q, kind })}`),
    // How pages are read and screened, for Settings → Permissions → Screening and Agent → Reading web pages: the models each backend offers, what relevance uses now
    getWebReading: () => req('GET', '/api/web/reading'),
    getSettings: () => req('GET', '/api/settings'),
    // settings-that-stick 2.2: `base` (what each changed key held when loaded; settings-merge.js baseOf) merges with what is saved now
    saveSettings: (s, { base } = {}) => req('PUT', '/api/settings', { json: base && Object.keys(base).length ? { ...s, base } : s }),
    getSettingsDefaults: () => req('GET', '/api/settings/defaults'),   // plan settings-redesign 4.1: config.example.toml's values
    getMetrics: ({ series, range, step } = {}) => req('GET', `/api/metrics${qs({ series, range, step })}`),
    listMetricSeries: () => req('GET', '/api/metrics/series'),
    getTimeline: ({ range, services } = {}) => req('GET', `/api/timeline${qs({ range, services })}`),
    getOutputStats: ({ range, by } = {}) => req('GET', `/api/outputs/stats${qs({ range, by })}`),
    getActivityStats: ({ range } = {}) => req('GET', `/api/activity/stats${qs({ range })}`),
    getJobStats: ({ range } = {}) => req('GET', `/api/jobs/stats${qs({ range })}`),
    listWidgets: () => req('GET', '/api/widgets'),
    getWidget: (service, id, { range } = {}) => req('GET', `/api/widgets/${enc(service)}/${enc(id)}${qs({ range })}`),
    listTools: ({ q, names } = {}) => req('GET', `/api/tools${qs({ q, names })}`),
    getToolIndex: () => req('GET', '/api/tools/index'),
    callTool: (name, args = {}, { mode, origin, wait } = {}) => req('POST', `/api/tools/${enc(name)}/call${qs({ wait })}`, { json: { arguments: args, mode, origin } }),
    getToolCall: (id, { wait } = {}) => req('GET', `/api/tools/calls/${enc(id)}${qs({ wait })}`),
    cancelToolCall: id => req('POST', `/api/tools/calls/${enc(id)}/cancel`),
    listApprovals: ({ state } = {}) => req('GET', `/api/approvals${qs({ state })}`),
    getApproval: id => req('GET', `/api/approvals/${enc(id)}`),
    // remember: once | thread | always (plan 25.2); confirm: the second confirm an always grant for execute/destructive needs
    decideApproval: (id, { approve, args, reason, remember, confirm, wait } = {}) => req('POST', `/api/approvals/${enc(id)}${qs({ wait })}`, { json: { approve, arguments: args, reason, remember, confirm } }),
    listGrants: ({ thread, tool } = {}) => req('GET', `/api/grants${qs({ thread, tool })}`),
    revokeGrant: id => req('DELETE', `/api/grants/${enc(id)}`),
    listJudged: ({ thread, limit } = {}) => req('GET', `/api/judge/recent${qs({ thread, limit })}`),   // plan 30.3, 30.5
    getJudgeStatus: () => req('GET', '/api/judge/status'),
    listSessions: () => req('GET', '/api/sessions'),
    saveSession: name => req('POST', '/api/sessions', { json: { name } }),
    renameSession: (id, name) => req('PUT', `/api/sessions/${enc(id)}`, { json: { name } }),
    deleteSession: id => req('DELETE', `/api/sessions/${enc(id)}`),
    restoreSession: (id, { dryRun = false } = {}) => req('POST', `/api/sessions/${enc(id)}/restore${dryRun ? '?dry_run=1' : ''}`),
    getSessionState: () => req('GET', '/api/sessions/state'),

    async callService(id, method, path, opts = {}) {
      const [p, q0] = path.split('?');
      const query = { ...Object.fromEntries(new URLSearchParams(q0 || '')), ...(opts.query || {}) };
      const body = opts.json !== undefined ? undefined : opts.form ? toForm(opts.form) : undefined;
      const t0 = Date.now();
      // makeRoom: retry of a call the hub answered with needs_room ("Unload & continue", plan 5.5).
      const headers = opts.makeRoom ? { 'X-GAIFA-Make-Room': '1' } : undefined;
      const res = await send(method, `/api/s/${enc(id)}${p}${qs(query)}`, { json: opts.json, body, signal: opts.signal, headers });
      if (!res.ok) throw res.headers.get('x-gaifa-error') ? await envelopeError(res) : await upstreamError(res);
      const ct = res.headers.get('content-type') || '';
      const out = { status: res.status, ok: true, ms: 0, content_type: ct.split(';')[0] };
      if (opts.stream || ct.startsWith('text/event-stream')) out.text = await readEvents(res, opts.onEvent, opts.signal);
      else if (/json/.test(ct)) { const t = await res.text(); out.json = t ? JSON.parse(t) : null; }
      else if (ct.startsWith('text/') || res.status === 204) out.text = await res.text();
      else { out.blob = await res.blob(); out.url = URL.createObjectURL(out.blob); }
      out.ms = Date.now() - t0;
      return out;
    },

    subscribe: (onEvent, onError) => stream('/api/events', onEvent, onError),
  };
}

const noMock = name => () => Promise.reject(new ApiError(501, `${name} is not available in the mock`, 'hub_error'));

export function createApi({ base = null, liveAreas = [], mock, fetch, EventSource } = {}) {
  const live = new Set(base === null || base === undefined ? [] : liveAreas);
  const http = createHttpApi(base || '', { fetch, EventSource });
  const isLive = area => live.has(area);
  const api = {};

  for (const [name, area] of Object.entries(METHOD_AREA)) {
    api[name] = isLive(area) ? http[name] : (mock?.[name] ? mock[name].bind(mock) : noMock(name));
  }

  // The hub's /api/overview when the `overview` area is live; otherwise the mock's, with live areas filled in.
  api.getOverview = async () => {
    if (isLive('overview')) return http.getOverview();
    const ov = await mock.getOverview();
    const parts = [];
    if (isLive('system')) parts.push(http.getSystem().then(s => { ov.system = s; }));
    if (isLive('services')) parts.push(http.listServices().then(s => { ov.services = s; }));
    if (isLive('memory')) parts.push(http.getMemory().then(m => { ov.memory = m; }));
    if (isLive('outputs')) parts.push(http.listOutputs({ limit: 8 }).then(p => { ov.recent_outputs = p.items; }));
    if (isLive('events')) parts.push(http.getRecentEvents().then(e => { ov.activity = e.activity; ov.alerts = e.alerts; ov.jobs = e.jobs; }));
    await Promise.all(parts);
    return ov;
  };

  // Live events for live areas, mock events for the rest. While anything is live the
  // hub's stream stays open even with `events` mocked: its error is how the UI notices
  // the hub went down.
  api.subscribe = (onEvent, onError) => {
    const subs = [];
    if (mock?.subscribe) subs.push(mock.subscribe(ev => { if (!isLive(EVENT_AREA[ev.type])) onEvent(ev); }, onError));
    if (live.size) subs.push(http.subscribe(ev => { if (ev.type === 'resync' || isLive(EVENT_AREA[ev.type])) onEvent(ev); }, onError));
    return { close: () => subs.forEach(s => s.close()) };
  };

  api.liveAreas = [...live];
  api.isLive = isLive;
  api.mock = mock?.mock;
  return api;
}
