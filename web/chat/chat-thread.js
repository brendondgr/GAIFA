// A thread's event log → the list of cards the page draws (plan 14.1). Pure (no React, no DOM),
// tested in utils/tests/web/chat.test.mjs.
//
// Each item is `{key, kind, …}`; `kind` is what the card registry (chat-cards.js) looks up:
//   user, assistant, thinking          one per event (plus streaming ones from live deltas)
//   tool                               a tool_call with its call, progress and tool_result folded in
//   approval                           a tool_call that needs a parameter card (approval + decision)
//   question                           an ask_user question with its answer
//   result                             the outputs of a tool_result (#n), after the tool card
//   todos                              the checklist, where it first appeared (it is also pinned)
//   <any other event type>             memory, note, error, compact … and types added later:
//                                      unknown kinds fall back to a generic card, never an error.

// Tool calls the page never shows as tool cards: their effect has its own card.
export const HIDDEN_TOOLS = new Set(['ask_user', 'update_todos', 'remember']);
// Events folded into other cards or into the page state.
const FOLDED = new Set(['call', 'answer', 'decision', 'usage', 'state']);

export function buildView(events, live = {}) {
  const items = [], calls = new Map(), questions = new Map(), outputs = [];
  let todos = null, todoItem = null, state = null, usage = null, lastSeq = 0;
  const queued = [];
  for (const ev of events || []) {
    const p = ev.payload || {};
    if (ev.seq > lastSeq) lastSeq = ev.seq;
    switch (ev.type) {
      case 'user': {
        const it = { key: 'e' + ev.seq, kind: 'user', ev, queued: !!p.queued };
        items.push(it);
        (p.docs || []).forEach(d => outputs.push({ n: +String(d.ref).replace('#', ''), output_id: d.id, kind: d.kind, title: d.name, tool: 'attached' }));  // plan 24.5
        if (p.queued) queued.push(it);
        break;
      }
      case 'thinking':
      case 'assistant':
        queued.splice(0).forEach(q => { q.queued = false; });
        if (ev.type === 'assistant' && !String(p.text || '').trim()) break;
        items.push({ key: 'e' + ev.seq, kind: ev.type, ev });
        break;
      case 'tool_call': {
        queued.splice(0).forEach(q => { q.queued = false; });
        const it = { key: 'c' + p.id, kind: 'tool', ev, call: p, run: null, approval: null, decision: null, result: null, progress: null, hidden: HIDDEN_TOOLS.has(p.name) };
        calls.set(p.id, it);
        if (!it.hidden) items.push(it);
        break;
      }
      case 'call': { const it = calls.get(p.id); if (it) it.run = p; break; }
      case 'approval': {
        let it = calls.get(p.id);
        if (!it) { it = { key: 'c' + p.id, ev, call: { id: p.id, name: p.tool, arguments: p.arguments }, run: null, decision: null, result: null, progress: null }; calls.set(p.id, it); items.push(it); }
        it.kind = 'approval'; it.approval = p;
        if (it.hidden) { it.hidden = false; items.push(it); }
        break;
      }
      case 'decision': { const it = calls.get(p.id); if (it) { it.decision = p; it.decisionTs = ev.ts; } break; }
      case 'question': {
        const it = { key: 'q' + p.id, kind: 'question', ev, q: p, answer: null, result: null };
        questions.set(p.id, it); items.push(it);
        break;
      }
      case 'answer': { const it = questions.get(p.id); if (it) { it.answer = p; it.answerTs = ev.ts; } break; }
      case 'tool_result': {
        const q = questions.get(p.id);
        if (q) { q.result = p; break; }
        const it = calls.get(p.id);
        if (it) { it.result = p; it.resultTs = ev.ts; }
        else items.push({ key: 'e' + ev.seq, kind: 'tool', ev, call: { id: p.id, name: p.name, arguments: {} }, result: p });
        if (Array.isArray(p.outputs) && p.outputs.length && !(it && it.hidden)) {
          p.outputs.forEach(o => outputs.push({ ...o, tool: p.name }));
          items.push({ key: 'r' + p.id, kind: 'result', ev, result: p, call: it?.call || { id: p.id, name: p.name } });
        }
        break;
      }
      case 'todos':
        todos = Array.isArray(p.items) ? p.items : [];
        if (!todoItem) { todoItem = { key: 'todos', kind: 'todos', ev, items: todos }; items.push(todoItem); } else todoItem.items = todos;
        break;
      case 'usage': usage = p; break;
      case 'state': state = p.state; break;
      default:
        if (!FOLDED.has(ev.type)) items.push({ key: 'e' + ev.seq, kind: ev.type, ev });
    }
  }
  // Streaming text and thinking of steps not stored yet (transient `delta` events).
  const stored = new Set((events || []).filter(e => e.type === 'assistant' || e.type === 'thinking').map(e => e.type + ':' + e.payload?.step));
  for (const [step, d] of Object.entries(live.deltas || {})) {
    if (d.thinking && !stored.has('thinking:' + step)) items.push({ key: 'dt' + step, kind: 'thinking', streaming: true, ev: { type: 'thinking', payload: { text: d.thinking, step, since: d.t0 } } });
    if (d.text && !stored.has('assistant:' + step)) items.push({ key: 'da' + step, kind: 'assistant', streaming: true, ev: { type: 'assistant', payload: { text: d.text, step } } });
  }
  for (const it of calls.values()) {
    const pr = live.progress?.[it.call.id];
    if (pr && !it.result) it.progress = pr;
  }
  const pending = items.filter(i => (i.kind === 'question' && !i.answer && !i.result) || (i.kind === 'approval' && !i.decision && !i.result));
  return { items, todos, state, usage, outputs, pending, lastSeq, gpu: live.gpu || null };
}

/** Folds one transient stream event (seq null) into the live state `{deltas, progress, meter}`. */
export function applyTransient(live, ev) {
  const p = ev.payload || {};
  if (ev.type === 'delta') {
    const d = { ...(live.deltas[p.step] || { t0: ev.ts || Date.now() / 1000 }) };
    if (p.kind === 'thinking') d.thinking = (d.thinking || '') + (p.text || ''); else d.text = (d.text || '') + (p.text || '');
    return { ...live, deltas: { ...live.deltas, [p.step]: d }, gpu: null };   // a token came: no longer waiting for the GPU
  }
  if (ev.type === 'delta_reset') {
    const deltas = { ...live.deltas }; delete deltas[p.step];
    return { ...live, deltas };
  }
  if (ev.type === 'progress') return { ...live, progress: { ...live.progress, [p.id]: p } };
  if (ev.type === 'context') return { ...live, meter: p };
  if (ev.type === 'gpu_wait') return { ...live, gpu: p.text ? p : null };   // plan 31.4: the model call waits for the GPU slot
  return live;
}

/** After a stored event arrives: drop the deltas and progress it replaces. */
export function settleLive(live, ev) {
  const p = ev.payload || {};
  if (live.gpu && (ev.type === 'state' || ev.type === 'assistant' || ev.type === 'thinking' || ev.type === 'usage')) live = { ...live, gpu: null };
  if ((ev.type === 'assistant' || ev.type === 'thinking') && live.deltas[p.step]) {
    const d = { ...live.deltas[p.step] };
    delete d[ev.type === 'assistant' ? 'text' : 'thinking'];
    const deltas = { ...live.deltas };
    if (d.text || d.thinking) deltas[p.step] = d; else delete deltas[p.step];
    return { ...live, deltas };
  }
  if (ev.type === 'tool_result' && live.progress[p.id]) {
    const progress = { ...live.progress }; delete progress[p.id];
    return { ...live, progress };
  }
  return live;
}

/** Adds stored events in seq order, ignoring ones already there (a replay after a reconnect). */
export function mergeEvents(list, incoming) {
  const have = new Set(list.map(e => e.seq));
  const add = incoming.filter(e => e.seq != null && !have.has(e.seq));
  if (!add.length) return list;
  const out = list.concat(add);
  out.sort((a, b) => a.seq - b.seq);
  return out;
}

/** A live `thread` event's thread: the agent sends the thread itself as the payload; older mocks wrapped it in `{thread}`. */
export const threadOf = p => (p?.thread && typeof p.thread === 'object' ? p.thread : p?.id ? p : null);

/** Is any item of a todo list still open? (the list stays pinned while it is). */
export const todosOpen = items => Array.isArray(items) && items.some(i => i.state !== 'done');
