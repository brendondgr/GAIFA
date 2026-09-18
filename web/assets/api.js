/* ============================================================
   api (http) — live mode. Each method maps to one endpoint.
   ============================================================ */
export class ApiError extends Error {
  constructor(status, detail, code) { super(detail); this.status = status; this.detail = detail; this.code = code || 'daemon_error'; }
}
export function createHttpApi(base) {
  const enc = encodeURIComponent;
  async function req(method, path, body) {
    let res;
    try { res = await fetch(base + path, { method, headers: body ? { 'content-type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); }
    catch (e) { throw new ApiError(0, 'lcpp daemon not responding', 'network'); }
    if (res.status === 204) return null;
    let data = null; try { data = await res.json(); } catch { /* no body */ }
    if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText, data && data.code);
    return data;
  }
  return {
    getOverview: () => req('GET', '/api/overview'),
    listInstances: () => req('GET', '/api/instances'),
    getInstance: n => req('GET', `/api/instances/${enc(n)}`),
    preflight: spec => req('POST', '/api/instances/preflight', spec),
    launch: spec => req('POST', '/api/instances', spec),
    stop: n => req('DELETE', `/api/instances/${enc(n)}`),
    stopAll: () => req('POST', '/api/instances/stop-all'),
    restart: n => req('POST', `/api/instances/${enc(n)}/restart`),
    dismiss: n => req('DELETE', `/api/instances/${enc(n)}?dismiss=1`),
    routerLoad: (n, m) => req('POST', `/api/instances/${enc(n)}/models/${enc(m)}/load`),
    routerUnload: (n, m) => req('POST', `/api/instances/${enc(n)}/models/${enc(m)}/unload`),
    getLogs: (n, lines) => req('GET', `/api/instances/${enc(n)}/logs?lines=${lines || 200}`),
    streamLogs(n, onLine) {
      const es = new EventSource(base + `/api/instances/${enc(n)}/logs/stream`);
      es.onmessage = e => { try { onLine(JSON.parse(e.data)); } catch { /* ignore malformed */ } };
      return { close: () => es.close() };
    },
    publish: (n, alias) => req('POST', `/api/instances/${enc(n)}/relay`, { alias }),
    unpublish: n => req('DELETE', `/api/instances/${enc(n)}/relay`),
    async chat(target, request, onDelta, signal) {
      let res;
      try { res = await fetch(base + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ target, request: { ...request, stream: true } }), signal }); }
      catch (e) { if (e.name === 'AbortError') throw e; throw new ApiError(0, 'lcpp daemon not responding', 'network'); }
      if (!res.ok) { let d = null; try { d = await res.json(); } catch { } throw new ApiError(res.status, (d && d.detail) || res.statusText, d && d.code); }
      const reader = res.body.getReader(), dec = new TextDecoder(); let buf = '', metrics = null;
      for (;;) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const evt = buf.slice(0, i); buf = buf.slice(i + 2);
          for (const line of evt.split('\n')) {
            if (!line.startsWith('data:')) continue; const d = line.slice(5).trim(); if (!d || d === '[DONE]') continue;
            let j; try { j = JSON.parse(d); } catch { continue; }
            if (j.lcpp_metrics) metrics = j.lcpp_metrics; else if (j.error) throw new ApiError(502, j.error.message || 'upstream error', j.error.code || 'daemon_error'); else onDelta(j);
          }
        }
      }
      return metrics;
    },
    listModels: () => req('GET', '/api/models'),
    saveModel: m => req('PUT', `/api/models/${enc(m.id)}`, m),
    deleteModel: id => req('DELETE', `/api/models/${enc(id)}`),
    saveDefaults: p => req('PUT', '/api/models/defaults', p),
    validateModel: m => req('POST', '/api/models/validate', m),
    listDiscovered: () => req('GET', '/api/models/discovered'),
    getRelay: () => req('GET', '/api/relay'),
    testRelay: () => req('POST', '/api/relay/test'),
    removeRegistration: k => req('DELETE', `/api/relay/registrations/${enc(k)}`),
    cleanupOrphans: () => req('POST', '/api/relay/cleanup'),
    getSettings: () => req('GET', '/api/settings'),
    saveSettings: s => req('PUT', '/api/settings', s),
    getRecent: () => req('GET', '/api/recent'),
    suggestPort: () => req('GET', '/api/ports/suggest'),
  };
}
