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
