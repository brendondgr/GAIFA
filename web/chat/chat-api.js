// The Chat page's client for the agent mod (plan 14.2–14.9), through the hub's proxy at
// /api/s/agent. `createChatClient({api})` returns the live client when the `proxy` area is live,
// and the scripted mock agent (chat-mock.js) in `?mock`. Both have the same methods:
//
//   models() threads({q, archived, limit}) searchChats(q, limit) create(body) get(tid) patch(tid, p) remove(tid) events(tid, after)
//   stream(tid, after, {onEvent, onReady, onState}) → {close()}   (reconnects with after=lastSeq)
//   send(tid, text, attachments, doc_modes, quote) answer(tid, question_id, answers) approval(tid, {approval_id, approve, arguments, reason})
//   action(tid, tool, args) fork(tid, seq) cancel(tid) compact(tid) context(tid) settings() saveSettings(body)
//   feedback(tid, {value, output_id | seq, note}) decidePref(pid, approve)   (plan 21.7)
//
// Errors are ChatError {status, detail, code, data}; status 0 means AIHub didn't answer.

import { createMockClient } from './chat-mock.js';

export class ChatError extends Error {
  constructor(status, detail, code, data) { super(detail); Object.assign(this, { status, detail, code, data }); }
}

const enc = encodeURIComponent;
const qs = o => { const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => `${enc(k)}=${enc(v)}`).join('&') : ''; };

// FastAPI answers {detail: "…"}, or {detail: {code, detail, data}} for the agent's own errors
// (an approval whose edited arguments are invalid), or {detail: [validation errors]}; the hub's
// proxy answers its envelope {detail, code, data}.
export async function errorFrom(res) {
  const text = await res.text().catch(() => '');
  let j = null;
  try { j = JSON.parse(text); } catch { /* not JSON */ }
  let detail = j?.detail, code = j?.code || (res.status === 404 ? 'not_found' : 'agent_error'), data = j?.data;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) { code = detail.code || code; data = detail.data ?? data; detail = detail.detail; }
  if (Array.isArray(detail)) { code = 'invalid_request'; detail = detail.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; '); }
  return new ChatError(res.status, typeof detail === 'string' && detail ? detail : (text || res.statusText || `HTTP ${res.status}`), code, data);
}

export function createLiveClient({ base = '', fetch: f = globalThis.fetch?.bind(globalThis), EventSource: ES = globalThis.EventSource } = {}) {
  const url = p => `${base}/api/s/agent${p}`;
  async function req(method, path, json) {
    let res;
    try {
      res = await f(url(path), { method, headers: json !== undefined ? { 'content-type': 'application/json' } : {}, body: json !== undefined ? JSON.stringify(json) : undefined });
    } catch { throw new ChatError(0, 'AIHub not responding', 'hub_error'); }
    if (!res.ok) throw await errorFrom(res);
    if (res.status === 204) return null;
    const t = await res.text();
    return t ? JSON.parse(t) : null;
  }
  const T = tid => `/v1/threads/${enc(tid)}`;

  // SSE with our own reconnect: always `after=` the last stored seq we saw, so a dropped stream
  // (or a hub/agent restart) catches up without duplicates.
  function stream(tid, after = 0, { onEvent, onReady, onState } = {}) {
    let last = after, es = null, closed = false, tries = 0, timer = null;
    const open = () => {
      if (closed) return;
      es = new ES(url(`${T(tid)}/stream?after=${last}`));
      es.onopen = () => { tries = 0; onState?.('open'); };
      es.onmessage = m => {
        let ev;
        try { ev = JSON.parse(m.data); } catch { return; }
        if (ev.type === 'ready') { onReady?.(ev); return; }
        if (ev.seq != null) { if (ev.seq <= last) return; last = ev.seq; }
        onEvent?.(ev);
      };
      es.onerror = () => {
        es.close();
        if (closed) return;
        onState?.('reconnecting');
        timer = setTimeout(open, Math.min(10000, 800 * 2 ** tries++));
      };
    };
    open();
    return { close() { closed = true; clearTimeout(timer); es?.close(); }, get lastSeq() { return last; } };
  }

  return {
    live: true,
    models: () => req('GET', '/v1/models'),
    threads: ({ q, archived, limit } = {}) => req('GET', '/v1/threads' + qs({ q, archived: archived ? 'true' : undefined, limit })),
    searchChats: (q, limit = 8) => req('GET', '/v1/chats/search' + qs({ q, limit })).then(r => r.results || []),  // plan 28.5
    create: (body = {}) => req('POST', '/v1/threads', body),
    get: tid => req('GET', T(tid)),
    patch: (tid, p) => req('PATCH', T(tid), p),
    remove: tid => req('DELETE', T(tid)),
    events: (tid, after = 0) => req('GET', `${T(tid)}/events?after=${after}`),
    stream,
    // quote: {text (markdown), seq?}: the part of an earlier reply this message answers (Select → Reply)
    send: (tid, text, attachments = [], doc_modes = {}, quote = null) => req('POST', `${T(tid)}/messages`, { text, attachments, ...(Object.keys(doc_modes || {}).length ? { doc_modes } : {}),
      ...(quote?.text ? { quote: { text: quote.text, ...(quote.seq != null ? { seq: quote.seq } : {}) } } : {}) }),
    answer: (tid, question_id, answers) => req('POST', `${T(tid)}/answer`, { question_id, answers }),
    approval: (tid, body) => req('POST', `${T(tid)}/approval`, body),
    action: (tid, tool, args = {}) => req('POST', `${T(tid)}/action`, { tool, arguments: args }),
    fork: (tid, seq) => req('POST', `${T(tid)}/fork`, { seq }),
    cancel: tid => req('POST', `${T(tid)}/cancel`),
    compact: tid => req('POST', `${T(tid)}/compact`),
    context: tid => req('GET', `${T(tid)}/context`),
    settings: () => req('GET', '/v1/settings'),
    saveSettings: body => req('PUT', '/v1/settings', body),
    feedback: (tid, body) => req('POST', `${T(tid)}/feedback`, body),
    decidePref: (pid, approve) => req('POST', `/v1/prefs/${enc(pid)}/${approve ? 'approve' : 'reject'}`),
  };
}

/** The live client when AIHub proxies to mods, else the scripted mock agent. */
export function createChatClient({ api, base = '', mock = null } = {}) {
  const forceMock = mock ?? (typeof location !== 'undefined' && new URLSearchParams(location.search).has('mock'));
  if (!forceMock && api?.isLive?.('proxy')) return createLiveClient({ base });
  return createMockClient(api);
}
