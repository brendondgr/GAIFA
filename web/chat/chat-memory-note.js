// "Remembered: …" under a chat's last turn (plan memory-auto-learning 3.3): what the agent's learner took from this
// chat once it went quiet, read when the chat opens. Saved facts first; what waits for review is counted.
import { h, T } from './chat-ui.js';

const R = () => globalThis.React;

/** The note's parts from the chat's learned facts: { first, more, waiting } or null when there's nothing. */
export function noteOf(facts) {
  const saved = (facts || []).filter(f => f.state === 'active'), waiting = (facts || []).filter(f => f.state === 'proposed');
  if (!saved.length && !waiting.length) return null;
  return { first: saved[0]?.text || '', more: Math.max(0, saved.length - 1), waiting: waiting.length };
}

export function MemoryNote({ api, tid }) {
  const React = R(), [note, setNote] = React.useState(null);
  React.useEffect(() => {
    setNote(null);
    if (!tid || !api.callService) return undefined;
    let live = true;
    api.callService('agent', 'GET', '/v1/memory/facts', { query: { thread: tid, source: 'inferred', limit: 50 } })
      .then(r => { if (live) setNote(noteOf(Array.isArray(r.json) ? r.json : [])); }).catch(() => {});
    return () => { live = false; };
  }, [tid]);
  if (!note) return null;
  const link = (href, label) => h('a', { href, style: { color: T.acct } }, label);
  return h('div', { role: 'note', style: { fontSize: 12, color: T.mut, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'baseline', padding: '0 2px' } },
    note.first ? h('span', null, `Remembered: ${note.first}`) : null,
    note.more ? h('span', null, `· +${note.more}`) : null,
    note.waiting ? h('span', null, `${note.first ? '· ' : ''}${note.waiting} to review`) : null,
    h('span', null, '·'), link('#/s/agent/review', 'Review'));
}
