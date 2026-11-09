// The chat mock's sub-agents (plan agent-workflows 3.1, `?mock`): the agent's tree and request routes on in-memory
// threads, with the same shapes as services/agent/agent/api_workflows.py. One fixture workflow, "Compare the folders":
// a finished sub-agent (Read tests, unseen), one still running in the background (Read src) and a writer waiting on a
// card its parent forwarded to you (Add a header). Approving or denying it from the parent finishes the writer and
// sends `agent_done` to the parent. Every change is an `agent_child` event to the `watchWorkflows` listeners.

export function createAgentMocks({ threads, newThread, emit, net, err, now, rid }) {
  const watchers = new Set();
  const spawnOf = t => t?.thread?.settings?.spawn || null;
  const kids = (pid, by = 'parent') => [...threads.values()].filter(t => spawnOf(t)?.[by] === pid).sort((a, b) => a.thread.created - b.thread.created);
  const node = t => { const sp = spawnOf(t);
    return { id: t.thread.id, title: t.thread.title, label: sp.label, parent: sp.parent, state: t.thread.state, model: t.thread.model, mode: t.thread.mode,
      write: !!sp.write, depth: sp.depth || 1, by: sp.by || 'agent', seen: sp.seen !== false, archived: !!t.thread.archived,
      created: t.thread.created, updated: t.thread.updated, children: kids(t.thread.id).length }; };
  const tell = t => { const sp = spawnOf(t), ev = { type: 'agent_child', thread_id: null, seq: null, ts: now(), id: t.thread.id, parent: sp.parent, root: sp.root, child: node(t) };
    watchers.forEach(f => { try { f(ev); } catch { /* a listener's own error */ } }); };
  const T = tid => { const t = threads.get(tid); if (!t) throw err(404, `no thread '${tid}'`, 'not_found'); return t; };
  const decided = (child, call) => child.events.some(e => (e.type === 'decision' || e.type === 'tool_result') && e.payload.id === call);
  function requestsOf(tid) {
    const t = T(tid), reviews = new Map(t.events.filter(e => e.type === 'agent_review').map(e => [e.payload.id, e.payload]));
    return t.events.filter(e => e.type === 'agent_request').map(e => {
      const p = e.payload, child = threads.get(p.child), waiting = !!child && !decided(child, p.call);
      return { ...structuredClone(p), seq: e.seq, waiting, open: waiting && !reviews.has(p.id), ...(reviews.has(p.id) ? { review: reviews.get(p.id) } : {}) };
    });
  }
  function child(parent, label, o = {}) {
    const c = newThread({ title: label, mode: parent.thread.mode, settings: { no_learn: true, spawn: { root: parent.thread.id, parent: parent.thread.id, label, by: 'agent',
      depth: 1, turn: 1, seen: o.seen ?? true, write: !!o.write, ...(o.background ? { background: true, reported: false } : {}) } }, parent_id: parent.thread.id });
    emit(c, 'note', { text: `A sub-agent of “${parent.thread.title}”, started by the chat; ${o.write ? 'it may change files' : 'it only reads'}. Its last reply goes back to the chat that started it.`, level: 'info' });
    emit(c, 'user', { text: o.prompt, by: 'parent' });
    return c;
  }
  function seed() {
    const p = newThread({ title: 'Compare the folders', mode: 'accept_edits' });
    const s1 = rid('s_'), a = rid('tc_'), b = rid('tc_'), w = rid('tc_');
    emit(p, 'user', { text: 'Compare the src and tests folders of my project, and add a header comment to src/store.py.' });
    emit(p, 'assistant', { text: 'I’ll read the two folders side by side and have a third sub-agent add the header.', step: s1, model: 'skynet' });
    emit(p, 'tool_call', { id: a, name: 'agent', arguments: { label: 'Read tests', prompt: 'List every test in tests/ and what it checks.' }, step: s1, by: 'model' });
    emit(p, 'tool_call', { id: b, name: 'agent', arguments: { label: 'Read src', prompt: 'List every function in src/ with what it does.', background: true }, step: s1, by: 'model' });
    emit(p, 'tool_call', { id: w, name: 'agent', arguments: { label: 'Add a header', prompt: 'Add “# store: the shopping list” at the top of src/store.py.', write: true, background: true }, step: s1, by: 'model' });
    const tests = child(p, 'Read tests', { prompt: 'List every test in tests/ and what it checks.', seen: false });
    emit(tests, 'tool_call', { id: 'k1', name: 'workspace_tree', arguments: { folder: 'myproj', path: 'tests' }, step: 'sk1', by: 'model' });
    emit(tests, 'tool_result', { id: 'k1', name: 'workspace_tree', status: 'done', content: 'tests/\n  test_store.py' });
    emit(tests, 'assistant', { text: '`tests/test_store.py` has two tests: `test_total` (counts items) and `test_load` (reads a file into words).', step: 'sk2', model: 'skynet' });
    tests.thread.state = 'idle';
    const src = child(p, 'Read src', { prompt: 'List every function in src/ with what it does.', background: true });
    emit(src, 'tool_call', { id: 'k2', name: 'workspace_read', arguments: { folder: 'myproj', path: 'src/store.py' }, step: 'sk3', by: 'model' });
    src.thread.state = 'running';
    const wr = child(p, 'Add a header', { prompt: 'Add “# store: the shopping list” at the top of src/store.py.', write: true, background: true });
    const args = { folder: 'myproj', path: 'src/store.py', old: 'def load(path):', new: '# store: the shopping list\ndef load(path):' };
    emit(wr, 'tool_call', { id: 'k3', name: 'workspace_edit', arguments: args, step: 'sk4', by: 'model' });
    const apid = rid('ap_');
    emit(wr, 'approval', { id: 'k3', approval_id: apid, tool: 'workspace_edit', arguments: args, ask_fields: [], schema: {}, risk: 'write', description: 'Change a file in place' });
    wr.thread.state = 'waiting';
    emit(p, 'tool_result', { id: a, name: 'agent', status: 'done', content: JSON.stringify({ child: tests.thread.id, label: 'Read tests', state: 'idle', answer: tests.events.at(-1).payload.text, chat: '#/chat/' + tests.thread.id }),
      data: { agent: { child: tests.thread.id, label: 'Read tests', state: 'idle' } } });
    emit(p, 'tool_result', { id: b, name: 'agent', status: 'done', content: JSON.stringify({ child: src.thread.id, label: 'Read src', state: 'queued', background: true }),
      data: { agent: { child: src.thread.id, label: 'Read src', background: true } } });
    emit(p, 'tool_result', { id: w, name: 'agent', status: 'done', content: JSON.stringify({ child: wr.thread.id, label: 'Add a header', state: 'queued', background: true }),
      data: { agent: { child: wr.thread.id, label: 'Add a header', background: true } } });
    const rq = rid('rq_');
    emit(p, 'agent_request', { id: rq, child: wr.thread.id, label: 'Add a header', kind: 'approval', call: 'k3', approval_id: apid, tool: 'workspace_edit', risk: 'write', arguments: args, in_result: false });
    emit(p, 'agent_review', { id: rq, child: wr.thread.id, action: 'forward', reason: 'It changes your file: your call.', kind: 'approval', approval_id: apid });
    emit(p, 'assistant', { text: 'The tests reader is done; the src reader is still going. The header edit needs your approval: it’s on the card below.', step: rid('s_'), model: 'skynet' });
    p.thread.updated = now() - 60;
  }
  return {
    seed,
    node: t => (spawnOf(t) ? node(t) : null),
    childrenOf: tid => kids(tid).length,
    async tree(tid) {
      await net(); const t = T(tid), rootId = spawnOf(t)?.root || tid, root = T(rootId);
      return { root: { id: root.thread.id, title: root.thread.title, state: root.thread.state, model: root.thread.model, mode: root.thread.mode,
        archived: !!root.thread.archived, created: root.thread.created, updated: root.thread.updated, children: kids(rootId).length },
      children: kids(rootId, 'root').map(node) };
    },
    async requests(tid, { waiting } = {}) { await net(); return requestsOf(tid).filter(r => r.waiting || !waiting); },
    async decideRequest(tid, rqid, body = {}) {
      await net(); const p = T(tid), r = requestsOf(tid).find(x => x.id === rqid);
      if (!r) throw err(404, `no request '${rqid}' in this chat`, 'not_found');
      if (!r.waiting) throw err(409, `request ${rqid} was decided already`, 'already_decided');
      const c = T(r.child), approve = !!body.approve, action = r.kind === 'question' ? 'answer' : approve ? 'approve' : 'deny';
      emit(c, 'decision', { id: r.call, approval_id: r.approval_id, approve, reason: body.reason || null, status: approve ? 'running' : 'denied' });
      emit(c, 'tool_result', { id: r.call, name: r.tool, status: approve ? 'done' : 'denied', content: approve ? '{"edited": true}' : '{}',
        ...(approve ? {} : { error: { code: 'denied_by_user', detail: body.reason || 'the user said no' } }) });
      const answer = approve ? 'Added the header to src/store.py.' : `I didn’t change src/store.py (${body.reason || 'you said no'}).`;
      emit(c, 'assistant', { text: answer, step: rid('s_'), model: 'skynet' });
      c.thread.state = 'idle'; c.thread.settings.spawn = { ...c.thread.settings.spawn, seen: false, reported: true };
      const ev = emit(p, 'agent_review', { id: rqid, child: r.child, action, by: 'user', kind: r.kind, ...(body.reason ? { reason: body.reason } : {}) });
      emit(p, 'agent_done', { child: r.child, label: r.label, state: 'idle', answer, chat: '#/chat/' + r.child });
      tell(c);
      return { request: rqid, action, event: ev };
    },
    watchWorkflows(onEvent) { watchers.add(onEvent); return { close() { watchers.delete(onEvent); } }; },
    tell,
  };
}
