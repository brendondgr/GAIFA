// AIHub's API for the UI: HTTP for the areas the hub serves, the mock for the rest.
// Written by us, not Claude Design (brief §6.1). The page builds it with
//   createApi({ base: window.AIHUB_API_BASE ?? null, liveAreas: window.AIHUB_LIVE_AREAS, mock: createMockApi() })
// and `?mock` in the URL forces everything to the mock.

export class ApiError extends Error {
  constructor(status, detail, code, data) { super(detail); Object.assign(this, { status, detail, code, data }); }
}

// Method → area (brief §6.1). getOverview and subscribe span areas and are handled separately.
export const METHOD_AREA = {
  getSystem: 'system',
  listServices: 'services', getService: 'services', startService: 'services', stopService: 'services',
  restartService: 'services', loadService: 'services', unloadService: 'services', saveServiceConfig: 'services',
  getServiceLogs: 'logs', streamServiceLogs: 'logs',
  listOperations: 'operations',
  callService: 'proxy',
  getMemory: 'memory', planRoom: 'memory',
  listModels: 'models', getModel: 'models', saveModel: 'models', verifyModel: 'models', deleteModel: 'models',
  scanModels: 'models', addModel: 'models',
  listOutputs: 'outputs', getOutput: 'outputs', deleteOutput: 'outputs',
  getSettings: 'settings', saveSettings: 'settings',
  getMetrics: 'metrics', listMetricSeries: 'metrics', getTimeline: 'metrics', getOutputStats: 'metrics',
  getActivityStats: 'metrics', getJobStats: 'metrics',
  listWidgets: 'widgets', getWidget: 'widgets',
};

// HubEvent type → area, for merging live and mock event streams.
export const EVENT_AREA = {
  service: 'services', memory: 'memory', output: 'outputs', output_deleted: 'outputs', model: 'models',
  activity: 'events', job: 'events', alert: 'events', alert_cleared: 'events',
};

const enc = encodeURIComponent;

function qs(params) {
  const p = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + p.map(([k, v]) => `${enc(k)}=${enc(Array.isArray(v) ? v.join(',') : v)}`).join('&') : '';
}

function down(base) {
  return new ApiError(0, `AIHub not responding at ${base || (globalThis.location ? location.host : '127.0.0.1:7000')}`, 'hub_error');
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

  async function send(method, path, { json, body, signal } = {}) {
    const init = { method, signal, headers: {} };
    if (json !== undefined) { init.body = JSON.stringify(json); init.headers['content-type'] = 'application/json'; }
    else if (body !== undefined) init.body = body;
    try {
      return await fetchFn(url(path), init);
    } catch (e) {
      if (e?.name === 'AbortError') throw e;
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
      const { value, done } = await reader.read();
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
    getRecentEvents: (limit = 80) => req('GET', `/api/events/recent${qs({ limit })}`),  // not in the brief: overview fill-in until Phase 6
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
    getSettings: () => req('GET', '/api/settings'),
    saveSettings: s => req('PUT', '/api/settings', { json: s }),
    getMetrics: ({ series, range, step } = {}) => req('GET', `/api/metrics${qs({ series, range, step })}`),
    listMetricSeries: () => req('GET', '/api/metrics/series'),
    getTimeline: ({ range, services } = {}) => req('GET', `/api/timeline${qs({ range, services })}`),
    getOutputStats: ({ range, by } = {}) => req('GET', `/api/outputs/stats${qs({ range, by })}`),
    getActivityStats: ({ range } = {}) => req('GET', `/api/activity/stats${qs({ range })}`),
    getJobStats: ({ range } = {}) => req('GET', `/api/jobs/stats${qs({ range })}`),
    listWidgets: () => req('GET', '/api/widgets'),
    getWidget: (service, id, { range } = {}) => req('GET', `/api/widgets/${enc(service)}/${enc(id)}${qs({ range })}`),

    async callService(id, method, path, opts = {}) {
      const [p, q0] = path.split('?');
      const query = { ...Object.fromEntries(new URLSearchParams(q0 || '')), ...(opts.query || {}) };
      const body = opts.json !== undefined ? undefined : opts.form ? toForm(opts.form) : undefined;
      const t0 = Date.now();
      const res = await send(method, `/api/s/${enc(id)}${p}${qs(query)}`, { json: opts.json, body, signal: opts.signal });
      if (!res.ok) throw res.headers.get('x-aihub-error') ? await envelopeError(res) : await upstreamError(res);
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

  // Assembled from the per-area calls until the hub serves /api/overview (Phase 6).
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
