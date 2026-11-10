// The Chat page's client for the agent mod (plan 14.2–14.9), through the hub's proxy at
// /api/s/agent. `createChatClient({api})` returns the live client when the `proxy` area is live,
// and the scripted mock agent (chat-mock.js) in `?mock`. Both have the same methods:
//
//   models() threads({q, archived: false | true | 'all', limit, environment, sort, offset}) threadGroups({archived}) threadCount({q, archived, environment}) → {count} searchChats(q, limit) create(body: {model, mode, settings, message?: messageBody(…)} → the thread, with `event` when it had a message) get(tid) patch(tid, p) remove(tid) events(tid, after)
//   stream(tid, after, {onEvent, onReady, onState}) → {close()}   (reconnects with after=lastSeq; the live client shares one
//   connection for every open chat, chat-streams.js; `sharedStream` says whether it does)
//   send(tid, text, attachments, doc_modes, quotes, mentions, client_id, when) → the user event, or {queued: item} (held during a turn)
//   queue(tid) queueEdit(tid, qid, {text, index}) queueRemove(tid, qid) queueSend(tid, qid) queueResume(tid) queueClear(tid)
//   answer(tid, question_id, answers) approval(tid, {approval_id, approve, arguments, reason})
//   action(tid, tool, args) fork(tid, seq) cancel(tid) compact(tid) context(tid) settings() saveSettings(body)
//   feedback(tid, {value, output_id | seq, note}) decidePref(pid, approve)   (plan 21.7)
//   projects({q, sort}) project(pid) createProject(body) patchProject(pid, p) deleteProject(pid) projectThreads(pid, opts)
//   addSource(pid, body) patchSource(pid, sid, p) removeSource(pid, sid) refreshSource(pid, sid) projectFolders(pid)
//   addProjectFolder(pid, {path, level}) patchProjectFolder(pid, fid, p) removeProjectFolder(pid, fid) projectMemory(pid)
//   patchProjectFact(pid, fid, p) forgetProjectFact(pid, fid) watchProjects(onEvent) → {close()}   (plan projects)
//   tasks({q, project}) task(kid) createTask(body) patchTask(kid, p) deleteTask(kid) taskRuns(kid, opts) seeRun(kid, rid)
//   tasksUnread() runTask(kid) testTask(kid) checkTask(kid) taskNotes(kid) addTaskNote(kid, text) patchTaskNote(kid, nid, text)
//   removeTaskNote(kid, nid) taskFolders(kid) addTaskFolder(kid, body) patchTaskFolder(kid, fid, p) removeTaskFolder(kid, fid)
//   runAllows(kid, rid) addAllows(kid, body) runLog(kid, rid) watchTasks(onEvent)   (plan scheduled-tasks)
//   tree(tid) requests(tid, {waiting}) decideRequest(tid, rid, {approve, reason, remember} | {answers}) seenChild(tid) watchWorkflows(onEvent)
//                                                                                   (plan agent-workflows 3.1: sub-agents)
//
// Errors are ChatError {status, detail, code, data}; status 0 means GAIFA didn't answer.

import { createMockClient } from './chat-mock.js';
import { createStreamPool } from './chat-streams.js';

export class ChatError extends Error {
  constructor(status, detail, code, data) { super(detail); Object.assign(this, { status, detail, code, data }); }
}

const enc = encodeURIComponent;
/** `archived`: false (live chats), true, or 'all' (both, plan chat-history 1.1). */
const archivedQ = a => (a === 'all' ? 'all' : a ? 'true' : undefined);
const qs = o => { const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => `${enc(k)}=${enc(v)}`).join('&') : ''; };

// FastAPI answers {detail: "…"}, or {detail: {code, detail, data}} for the agent's own errors
// (an approval whose edited arguments are invalid), or {detail: [validation errors]}; the hub's
// proxy answers its envelope {detail, code, data}.
// A message's body for `send(tid, …)` and `create({…, message})` (chat-responsive 1.2): mentions [{kind, id, label, fills}]
// (plan 48.2); client_id the page's id for the message, kept on its user event (chat-responsive 1.1).
// when (chat-responsive 2.1): 'now' writes it into a running turn; otherwise a message sent during a turn is held.
export const messageBody = (text, attachments = [], doc_modes = {}, quotes = [], mentions = [], client_id, when) => ({ text, attachments,
  ...(Object.keys(doc_modes || {}).length ? { doc_modes } : {}),
  ...(quotes?.length ? { quotes: quotes.map(q => ({ text: q.text, reply: q.reply || '', ...(q.seq != null ? { seq: q.seq } : {}) })) } : {}),
  ...(mentions?.length ? { mentions } : {}), ...(client_id ? { client_id } : {}), ...(when && when !== 'auto' ? { when } : {}) });

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
    } catch { throw new ChatError(0, 'GAIFA not responding', 'hub_error'); }
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
  // chat-split plan 3.2: every open chat on /v1/streams; an agent that answers 404 itself (not the hub's envelope,
  // which says the agent is down) hasn't got the route, and each chat gets its own stream as before
  const pool = createStreamPool({ EventSource: ES, single: stream, streamsUrl: spec => url(`/v1/streams?threads=${spec}`),
    // chat-responsive 3.1: a chat opened or closed later joins or leaves the open connection
    control: (id, body) => f(url(`/v1/streams/${enc(id)}/threads`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(r => !!r.ok, () => false),
    probe: async () => {
      const ac = globalThis.AbortController ? new AbortController() : null;
      try { const r = await f(url('/v1/streams?threads='), ac ? { signal: ac.signal } : {}); return !(r.status === 404 && !r.headers?.get?.('x-gaifa-error')); }
      catch { return true; } finally { ac?.abort(); }
    } });

  const watch = sharedWatch(url, ES);   // projects, tasks and sub-agents: one connection for all of them

  return {
    live: true,
    models: () => req('GET', '/v1/models'),
    threads: ({ q, archived, limit, environment, sort, offset, project, task } = {}) => req('GET', '/v1/threads' + qs({ q, archived: archivedQ(archived), limit,
      environment, sort: sort && sort !== 'updated' ? sort : undefined, offset: offset || undefined, project, task })),
    threadGroups: ({ archived, by } = {}) => req('GET', '/v1/threads/groups' + qs({ archived: archivedQ(archived),   // plan 41.1
      by: by && by !== 'environment' ? by : undefined })),                                 // by: 'project' (plan projects 1.3)
    threadCount: ({ q, archived, environment, project } = {}) => req('GET', '/v1/threads/count' + qs({ q, archived: archivedQ(archived), environment, project })),   // chat-history 1.1
    ...projectCalls(req, watch),                                                           // plan projects 1.3
    ...taskCalls(req, watch),                                                              // plan scheduled-tasks 4.1
    ...workflowCalls(req, watch),                                                          // plan agent-workflows 3.1
    searchChats: (q, limit = 8) => req('GET', '/v1/chats/search' + qs({ q, limit })).then(r => r.results || []),  // plan 28.5
    create: (body = {}) => req('POST', '/v1/threads', body),
    get: tid => req('GET', T(tid)),
    patch: (tid, p) => req('PATCH', T(tid), p),
    remove: tid => req('DELETE', T(tid)),
    events: (tid, after = 0) => req('GET', `${T(tid)}/events?after=${after}`),
    stream: pool.stream,
    get sharedStream() { return pool.shared; },
    // quotes: [{text (markdown), reply, seq?}], parts of earlier replies and the user's reply to each (Select → Reply);
    // `text` may be empty when a reply says something
    send: (tid, ...msg) => req('POST', `${T(tid)}/messages`, messageBody(...msg)),
    // the queue (chat-responsive 2.1): {items, paused}
    queue: tid => req('GET', `${T(tid)}/queue`),
    queueEdit: (tid, qid, p) => req('PATCH', `${T(tid)}/queue/${enc(qid)}`, p),
    queueRemove: (tid, qid) => req('DELETE', `${T(tid)}/queue/${enc(qid)}`),
    queueSend: (tid, qid) => req('POST', `${T(tid)}/queue/${enc(qid)}/send`),
    queueResume: tid => req('POST', `${T(tid)}/queue/resume`),
    queueClear: tid => req('DELETE', `${T(tid)}/queue`),
    answer: (tid, question_id, answers) => req('POST', `${T(tid)}/answer`, { question_id, answers }),
    approval: (tid, body) => req('POST', `${T(tid)}/approval`, body),
    action: (tid, tool, args = {}) => req('POST', `${T(tid)}/action`, { tool, arguments: args }),
    fork: (tid, seq) => req('POST', `${T(tid)}/fork`, { seq }),
    cancel: tid => req('POST', `${T(tid)}/cancel`),
    compact: tid => req('POST', `${T(tid)}/compact`),
    context: tid => req('GET', `${T(tid)}/context`),
    settings: () => req('GET', '/v1/settings'),
    saveSettings: body => req('PUT', '/v1/settings', body),
    uploadSkill: body => req('POST', '/v1/skills', body),                                  // skill-sources 3.1
    copySkill: body => req('POST', '/v1/skills/copy', body),
    setSkill: (name, enabled) => req('PATCH', `/v1/skills/${enc(name)}`, { enabled }),
    deleteSkill: name => req('DELETE', `/v1/skills/${enc(name)}`),
    feedback: (tid, body) => req('POST', `${T(tid)}/feedback`, body),
    decidePref: (pid, approve) => req('POST', `/v1/prefs/${enc(pid)}/${approve ? 'approve' : 'reject'}`),
  };
}

// Projects (plan projects 1.3): the agent's /v1/projects routes. watchProjects(onEvent) hears the `project` and
// `project_source` events on the client's one watch connection (sharedWatch below).
export function projectCalls(req, watch) {
  const P = pid => `/v1/projects/${enc(pid)}`;
  return {
    projects: ({ q, sort } = {}) => req('GET', '/v1/projects' + qs({ q, sort: sort && sort !== 'activity' ? sort : undefined })),
    project: pid => req('GET', P(pid)),
    createProject: body => req('POST', '/v1/projects', body),
    patchProject: (pid, patch) => req('PATCH', P(pid), patch),
    deleteProject: pid => req('DELETE', P(pid)),
    projectThreads: (pid, { q, archived, limit, sort, offset } = {}) => req('GET', `${P(pid)}/threads` + qs({ q, archived: archived ? 'true' : undefined, limit,
      sort: sort && sort !== 'updated' ? sort : undefined, offset: offset || undefined })),
    addSource: (pid, body) => req('POST', `${P(pid)}/sources`, body),
    patchSource: (pid, sid, patch) => req('PATCH', `${P(pid)}/sources/${enc(sid)}`, patch),
    removeSource: (pid, sid) => req('DELETE', `${P(pid)}/sources/${enc(sid)}`),
    refreshSource: (pid, sid) => req('POST', `${P(pid)}/sources/${enc(sid)}/refresh`),
    projectFolders: pid => req('GET', `${P(pid)}/folders`),
    addProjectFolder: (pid, body) => req('POST', `${P(pid)}/folders`, body),
    patchProjectFolder: (pid, fid, patch) => req('PATCH', `${P(pid)}/folders/${enc(fid)}`, patch),
    removeProjectFolder: (pid, fid) => req('DELETE', `${P(pid)}/folders/${enc(fid)}`),
    projectMemory: pid => req('GET', `${P(pid)}/memory`),
    patchProjectFact: (pid, fid, patch) => req('PATCH', `/v1/memory/facts/${enc(fid)}`, patch),
    forgetProjectFact: (pid, fid) => req('DELETE', `/v1/memory/facts/${enc(fid)}`),
    watchProjects: onEvent => watch(ev => (ev.type === 'project' || ev.type === 'project_source') && onEvent?.(ev)),
  };
}

// Scheduled tasks (plan scheduled-tasks 4.1): the agent's /v1/tasks routes. watchTasks(onEvent) hears the `task` and
// `task_run` events on the client's one watch connection.
export function taskCalls(req, watch) {
  const K = kid => `/v1/tasks/${enc(kid)}`;
  return {
    tasks: ({ q, project } = {}) => req('GET', '/v1/tasks' + qs({ q, project })),
    task: kid => req('GET', K(kid)),
    createTask: body => req('POST', '/v1/tasks', body),
    patchTask: (kid, patch) => req('PATCH', K(kid), patch),
    deleteTask: kid => req('DELETE', K(kid)),
    taskRuns: (kid, { limit, before } = {}) => req('GET', `${K(kid)}/runs` + qs({ limit, before })),
    seeRun: (kid, rid, seen = true) => req('PATCH', `${K(kid)}/runs/${enc(rid)}`, { seen }),
    tasksUnread: () => req('GET', '/v1/tasks/unread'),
    runTask: kid => req('POST', `${K(kid)}/run`),
    testTask: kid => req('POST', `${K(kid)}/test`),
    checkTask: kid => req('POST', `${K(kid)}/check`),
    taskNotes: kid => req('GET', `${K(kid)}/notes`),
    addTaskNote: (kid, text) => req('POST', `${K(kid)}/notes`, { text }),
    patchTaskNote: (kid, nid, text) => req('PATCH', `${K(kid)}/notes/${enc(nid)}`, { text }),
    removeTaskNote: (kid, nid) => req('DELETE', `${K(kid)}/notes/${enc(nid)}`),
    taskFolders: kid => req('GET', `${K(kid)}/folders`),
    addTaskFolder: (kid, body) => req('POST', `${K(kid)}/folders`, body),
    patchTaskFolder: (kid, fid, patch) => req('PATCH', `${K(kid)}/folders/${enc(fid)}`, patch),
    removeTaskFolder: (kid, fid) => req('DELETE', `${K(kid)}/folders/${enc(fid)}`),
    runAllows: (kid, rid) => req('GET', `${K(kid)}/runs/${enc(rid)}/allows`),
    addAllows: (kid, body) => req('POST', `${K(kid)}/allow`, body),
    runLog: (kid, rid) => req('GET', `${K(kid)}/runs/${enc(rid)}/log`),
    watchTasks: onEvent => watch(ev => (ev.type === 'task' || ev.type === 'task_run') && onEvent?.(ev)),
  };
}
// Sub-agents (plan agent-workflows 3.1): a chat's workflow tree, its sub-agents' requests and deciding one from it.
// watchWorkflows(onEvent) hears the `agent_child` events (a sub-agent started, changed state or ended:
// {id, parent, root, child: <tree row>}) on the client's one watch connection.
export function workflowCalls(req, watch) {
  const T = tid => `/v1/threads/${enc(tid)}`;
  return {
    tree: tid => req('GET', `${T(tid)}/tree`),
    requests: (tid, { waiting } = {}) => req('GET', `${T(tid)}/requests` + qs({ waiting: waiting ? 'true' : undefined })),
    decideRequest: (tid, rid, body) => req('POST', `${T(tid)}/requests/${enc(rid)}`, body),
    seenChild: tid => req('POST', `${T(tid)}/seen`),                                       // 3.2: its unread dot goes
    watchWorkflows: onEvent => watch(ev => ev.type === 'agent_child' && onEvent?.(ev)),
  };
}
// The events about no one chat (projects, tasks, sub-agents) on ONE /v1/streams connection for every listener: a
// browser keeps about six connections to the hub over HTTP/1.1, and one each for projects, tasks and workflows next to
// /api/events and the chats' stream left none for ordinary requests (the chat list stayed at Loading…). It opens with
// the first listener, closes after the last and reconnects on errors; each listener picks its own events.
export function sharedWatch(url, ES = globalThis.EventSource) {
  const listeners = new Set();
  let es = null, tries = 0, timer = null;
  const open = () => {
    timer = null;
    if (!listeners.size || !ES) return;
    es = new ES(url('/v1/streams?threads=&watch=projects,tasks,workflows'));
    es.onopen = () => { tries = 0; };
    es.onmessage = m => { let ev; try { ev = JSON.parse(m.data); } catch { return; } for (const on of [...listeners]) on(ev); };
    es.onerror = () => { es.close(); es = null; if (listeners.size) timer = setTimeout(open, Math.min(10000, 800 * 2 ** tries++)); };
  };
  return on => {
    listeners.add(on);
    if (!es && !timer) open();
    return { close() {
      if (!listeners.delete(on) || listeners.size) return;
      clearTimeout(timer); timer = null; es?.close(); es = null; tries = 0;
    } };
  };
}

/** The live client when GAIFA proxies to mods, else the scripted mock agent. */
export function createChatClient({ api, base = '', mock = null } = {}) {
  const forceMock = mock ?? (typeof location !== 'undefined' && new URLSearchParams(location.search).has('mock'));
  if (!forceMock && api?.isLive?.('proxy')) return createLiveClient({ base });
  return createMockClient(api);
}
