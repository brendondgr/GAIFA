// A thread's items (chat-thread.js `buildView`) → turns of steps (plan 19.2). Pure (no React, no
// DOM), tested in utils/tests/web/chat-turn.test.mjs.
//
// A turn starts at a user message, or at a tool call a button started (`by: "user"`). Its rows are
// grouped into steps by the `step` id the agent puts on thinking, text and tool calls (one model
// call each). The last step's text is the turn's **answer** when that step called no tools; text
// in a step with tools is an **update** row. The page draws a turn as the user's message, the
// activity fold (chat-activity.js), the outputs and the answer.
//
//   groupTurns(view, { running, now, tools }) → [{ kind: 'turn', … } | { kind: 'item', item }]
//   splitTurn(turn) → the turn's folds cut at each update, for the split layout
//
// turn: { key, user, action, steps: [{ id, rows }], answer, outputs, errors, pending, running,
//         start, end, elapsed, status, summary }
// row:  { type: 'thinking' | 'update' | 'tool' | 'question' | 'note' | 'memory' | 'todos' | 'other',
//         key, item, … } — tool rows add { name, status, seconds, lookup, progress }

// The agent's own lookups: drawn grey and not counted as work. `addLookup` extends it (chat-steps.js).
const LOOKUPS = new Set(['find_tools', 'load_tools', 'read_skill', 'view_output', 'read_result', 'comfy_list_workflows']);
export const addLookup = name => { LOOKUPS.add(name); };
/** A lookup: a known one, or any catalog tool whose risk is `read` (a hub_ tool counts as one when the catalog isn't known). */
export function isLookup(name, tools) {
  if (LOOKUPS.has(name)) return true;
  const t = (tools || []).find(x => x.name === name);
  if (t) return t.risk === 'read';
  return String(name).startsWith('hub_');
}

/** The hub paths that undo this turn's changes (plan 27.7): any tool result whose JSON carries `result.undo`. */
export function undoOf(toolRows) {
  const out = [];
  for (const r of toolRows) {
    const c = r.item.result?.content;
    if (r.item.result?.status !== 'done' || typeof c !== 'string' || !c.includes('"undo"')) continue;
    try { const u = JSON.parse(c)?.result?.undo; if (typeof u === 'string' && u.startsWith('/api/s/') && !out.includes(u)) out.push(u); } catch { /* not JSON */ }
  }
  return out;
}

const STANDALONE = new Set(['compact']);      // drawn between turns, never inside one: one mid-turn waits for the turn to end
const tsOf = it => it?.ev?.ts || 0;

export function groupTurns(view, { running = false, now = Date.now() / 1000, tools = null } = {}) {
  const out = [];
  let turn = null, held = [];                  // standalone items that came while a turn was open
  const flush = () => { out.push(...held); held = []; };
  const open = (it, action) => {
    flush();
    turn = { kind: 'turn', key: 'turn:' + it.key, user: action ? null : it, action: action ? it : null, steps: [], errors: [], start: tsOf(it), end: tsOf(it) };
    out.push(turn);
  };
  const stepOf = id => {
    const steps = turn.steps, last = steps[steps.length - 1];
    if (id == null) { if (last) return last; }
    else { const s = steps.find(x => x.id === id); if (s) return s; }
    const s = { id: id ?? 'anon' + steps.length, rows: [] };
    steps.push(s);
    return s;
  };
  for (const it of view.items || []) {
    // results cleared mid-turn (a compact event between a turn's steps) must not end the turn: its later steps
    // would each fall out of the fold as a card of their own
    if (STANDALONE.has(it.kind)) { (turn ? held : out).push({ kind: 'item', item: it }); continue; }
    const p = it.ev?.payload || {};
    if (it.kind === 'user') { open(it); continue; }
    if ((it.kind === 'tool' || it.kind === 'approval') && it.call?.by === 'user') open(it, true);
    if (!turn) { out.push({ kind: 'item', item: it }); continue; }
    turn.end = Math.max(turn.end, tsOf(it), it.resultTs || 0, it.decisionTs || 0, it.answerTs || 0);
    if (it.kind === 'error') { turn.errors.push(it); continue; }
    if (it.kind === 'result') continue;                        // outputs come from the tool rows
    if (it.kind === 'thinking') {
      stepOf(p.step).rows.push({ type: 'thinking', key: it.key, item: it, text: p.text || '', streaming: !!it.streaming,
        seconds: it.streaming ? Math.max(0, now - (p.since || now)) : p.seconds });
    } else if (it.kind === 'assistant') {
      stepOf(p.step).rows.push({ type: 'update', key: it.key, item: it, text: p.text || '', streaming: !!it.streaming });
    } else if (it.kind === 'tool' || it.kind === 'approval') {
      stepOf(it.call?.step).rows.push({ type: 'tool', key: it.key, item: it, name: it.call?.name, lookup: isLookup(it.call?.name, tools) });
    } else if (it.kind === 'question') {
      stepOf(null).rows.push({ type: 'question', key: it.key, item: it });
    } else if (['note', 'memory', 'todos'].includes(it.kind)) {
      stepOf(null).rows.push({ type: it.kind, key: it.key, item: it });
    } else {
      stepOf(null).rows.push({ type: 'other', key: it.key, item: it });
    }
  }
  flush();
  const turns = out.filter(b => b.kind === 'turn');
  turns.forEach((t, i) => finish(t, running && i === turns.length - 1, now, view.gpu));
  return out;
}

function finish(turn, live, now, gpu = null) {
  turn.running = live;
  // the answer: the last step's text when that step called no tools
  const last = turn.steps[turn.steps.length - 1];
  turn.answer = null;
  if (last && !last.rows.some(r => r.type === 'tool' || r.type === 'question')) {
    const i = last.rows.map(r => r.type).lastIndexOf('update');
    if (i >= 0) { turn.answer = last.rows[i]; last.rows.splice(i, 1); }
  }
  turn.steps = turn.steps.filter(s => s.rows.length);
  const rows = turn.steps.flatMap(s => s.rows), toolRows = rows.filter(r => r.type === 'tool');
  let firstOpen = true;
  for (const r of toolRows) {
    const it = r.item, from = it.decisionTs || tsOf(it);
    r.progress = it.progress || null;
    r.status = toolState(it, live, r.lookup || !!it.run || !!it.progress || firstOpen);
    if (!it.result && !(it.approval && !it.decision)) firstOpen = false;
    r.seconds = it.result ? Math.max(0, (it.resultTs || from) - from) : live && r.status === 'running' ? Math.max(0, now - from) : null;
  }
  // pages the web tools saved are hidden outputs (plan 30.9): the reply bar's Sources lists them, so they stay out of the strip
  turn.outputs = toolRows.filter(r => !/^web_/.test(r.name || '')).flatMap(r => (r.item.result?.outputs || [])
    .filter(o => !o.hidden).map(o => ({ ...o, tool: r.name })));
  turn.undo = undoOf(toolRows);
  turn.pending = rows.filter(r => (r.type === 'tool' && r.status === 'waiting') || (r.type === 'question' && !r.item.answer && !r.item.result)).map(r => r.item);
  if (turn.pending.length) turn.running = live = true;          // waiting for you is still a live turn
  turn.elapsed = Math.max(0, (live ? now : turn.end) - turn.start);
  turn.status = live ? status(turn, rows, gpu) : null;
  turn.summary = summaryOf(rows);
}

/** "Ran 2 tools" (lookups aren't counted), "Looked something up", "Thought it through" or "Done". */
export function summaryOf(rows) {
  const toolRows = rows.filter(r => r.type === 'tool'), work = toolRows.filter(r => !r.lookup).length, looks = toolRows.length - work;
  return { work, lookups: looks, text: work ? `Ran ${work} tool${work === 1 ? '' : 's'}` : looks ? 'Looked something up' : rows.length ? 'Thought it through' : 'Done' };
}

/** A turn cut at each of the agent's updates (Settings → Agent → Steps between messages: Split at each
 *  message): `[{ key, steps, message, running, status, elapsed, summary, last }]`, each part a turn-shaped fold of
 *  the rows before its message. The last part holds what came after the last update and the answer (null when the
 *  last step called tools); only it carries the live status. Times run from the previous message to this one. */
export function splitTurn(turn) {
  const parts = [];
  let rows = [], from = turn.start;
  const push = (message, end, last) => parts.push({ key: 'p' + parts.length, steps: rows.length ? [{ id: 'p' + parts.length, rows }] : [], message, last,
    running: last && turn.running, status: last ? turn.status : null, elapsed: Math.max(0, end - from), summary: summaryOf(rows) });
  for (const r of turn.steps.flatMap(s => s.rows)) {
    if (r.type !== 'update') { rows.push(r); continue; }
    const at = Math.max(from, tsOf(r.item));
    push(r, at, false);
    rows = []; from = at;
  }
  push(turn.answer, Math.max(from, turn.start + turn.elapsed), true);   // elapsed counts to now while the turn runs
  return parts;
}

/** A tool row's state: done | error | denied | cancelled | skipped | waiting | running | queued | stopped. */
export function toolState(it, live, started) {
  const r = it.result;
  if (r) return r.error && (!r.status || r.status === 'done') ? 'error' : r.status || 'done';
  if (it.approval && !it.decision) return 'waiting';
  if (it.decision && !it.decision.approve) return 'cancelled';
  if (!live) return 'stopped';
  return started ? 'running' : 'queued';
}

/** What the live header says, in order: waiting for you → a running tool → waiting for the GPU → writing → thinking → working. */
function status(turn, rows, gpu = null) {
  const wait = turn.pending[0];
  if (wait) return { kind: 'waiting', item: wait, question: wait.kind === 'question' };
  const tools = rows.filter(r => r.type === 'tool' && r.status === 'running');
  const tool = tools.find(r => !r.lookup) || tools[0];
  if (tool) return { kind: tool.lookup ? 'lookup' : 'tool', row: tool, pct: tool.progress?.progress ?? null, note: tool.progress?.note || null };
  if (gpu?.text) return { kind: 'gpu', text: gpu.text };       // the model call waits for the GPU slot (plan 31.4)
  if (turn.answer?.streaming || rows.some(r => r.type === 'update' && r.streaming)) return { kind: 'writing' };
  const th = rows.filter(r => r.type === 'thinking' && r.streaming).pop();
  if (th) return { kind: 'thinking', row: th };
  return { kind: 'working' };
}

/** The Auto judge's verdict on a tool step (plan 30.5): on its result, its running call or its card; null if not judged. */
export function judgeOf(it) {
  const j = it?.result?.judge || it?.run?.judge || it?.approval?.judge || null;
  if (!j) return null;
  return { ...j, why: j.why || (j.verdict === 'allow' ? `Auto: ran (judged safe: ${j.reason})` : `Auto: asked you (${j.reason})`) };
}
