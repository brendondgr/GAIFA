// The Calendar's layers (calendar plan 6.4, 8.2): things that aren't calendar items, drawn among them and opened
// elsewhere. Scheduled tasks: each task's next times as marks and its runs as chips coloured by how they went (a
// click opens the task, or the run's chat). Each layer is `{id, load(from, to) → occurrences}`; an occurrence has
// `layer` and `open()`, and can't be dragged.

export const RUN_COLOR = { done: '#2BB673', failed: '#E5484D', skipped: '#8A94A6', running: '#F2994A', queued: '#F2994A' };
const MARK_S = 15 * 60;

/** A tasks answer (`GET /api/s/agent/v1/tasks/calendar`) as occurrences. `go(hash)` opens things. */
export function taskOccs(tasks, go) {
  const out = [];
  for (const t of tasks || []) {
    for (const due of t.due || []) {
      out.push({ id: `task:${t.id}@${due}`, item_id: null, layer: 'tasks', kind: 'event', all_day: false, ts: due, end_ts: due + MARK_S,
        start: '', end: '', title: `◷ ${t.name}`, location: t.when || '', color: '#8A94A6', busy: 'free', recurring: false,
        open: () => go(`#/chat/tasks/${encodeURIComponent(t.id)}`) });
    }
    for (const r of t.runs || []) {
      const word = r.state === 'done' ? (r.refused ? `done · ${r.refused} refused` : 'done') : r.state;
      out.push({ id: `run:${r.id}`, item_id: null, layer: 'tasks', kind: 'event', all_day: false, ts: r.due, end_ts: r.due + MARK_S,
        start: '', end: '', title: `${r.seen ? '' : '● '}${t.name} · ${word}${r.late ? ' (late)' : ''}`, color: RUN_COLOR[r.state] || '#8A94A6', busy: 'free',
        recurring: false, open: () => go(r.thread_id ? `#/chat/${encodeURIComponent(r.thread_id)}` : `#/chat/tasks/${encodeURIComponent(t.id)}`) });
    }
  }
  return out;
}

/** The scheduled tasks layer, through the agent mod. */
export function tasksLayer(ctx) {
  return {
    id: 'tasks',
    async load(from, to) {
      const r = await ctx.api.callService('agent', 'GET', `/v1/tasks/calendar?from=${from.getTime() / 1000}&to=${to.getTime() / 1000}`);
      return taskOccs(r?.json?.tasks, h => ctx.navigate(h));
    },
  };
}

/** "Schedule a task here": a new once task at the sheet's time (#/chat/tasks?new=once&at=…). */
export const scheduleHere = x => `#/chat/tasks?new=once&at=${encodeURIComponent(`${x.date}T${x.time}`)}${x.project_id ? `&project=${encodeURIComponent(x.project_id)}` : ''}`;

const MIN_BLOCK_S = 15 * 60, OUT_S = 10 * 60, MUTED = '#5D6778';

/** The History layer (calendar 8.2): your chats each day as muted blocks from their first to their last message (at
 *  least 15 minutes) and outputs as small marks at their time; a click opens the chat or the output. Task runs are
 *  the Scheduled tasks layer's. */
export function historyOccs(chats, outputs, go) {
  const out = [];
  for (const c of chats || []) {
    const end = Math.max(c.last, c.first + MIN_BLOCK_S);
    out.push({ id: `chat:${c.thread_id}@${c.day}`, item_id: null, layer: 'history', kind: 'event', all_day: false, ts: c.first, end_ts: end, start: '', end: '',
      title: `${c.task ? '◷ ' : ''}${c.title}`, location: `${c.turns} message${c.turns === 1 ? '' : 's'}`, color: MUTED, busy: 'free', recurring: false,
      open: () => go(`#/chat/${encodeURIComponent(c.thread_id)}`) });
  }
  for (const o of outputs || []) {
    out.push({ id: `out:${o.id}`, item_id: null, layer: 'history', kind: 'event', all_day: false, ts: o.created_ts, end_ts: o.created_ts + OUT_S, start: '', end: '',
      title: `▣ ${o.title}`, location: o.service || '', color: MUTED, busy: 'free', recurring: false, open: () => go(`#/outputs/${encodeURIComponent(o.id)}`) });
  }
  return out;
}

/** The History layer: the agent's /v1/history and the hub's outputs in the range. */
export function historyLayer(ctx) {
  return {
    id: 'history',
    async load(from, to) {
      const f = from.getTime() / 1000, t = to.getTime() / 1000;
      const [h, o] = await Promise.all([
        ctx.api.callService('agent', 'GET', `/v1/history?from=${f}&to=${t}`).then(r => r?.json?.chats || []).catch(() => []),
        Promise.resolve(ctx.api.listOutputs?.({ from: f, to: t, limit: 200 })).then(p => p?.items || []).catch(() => [])]);
      return historyOccs(h, o, x => ctx.navigate(x));
    },
  };
}
