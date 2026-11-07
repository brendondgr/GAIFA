// The queue strip above the composer (plan chat-responsive 2.2): messages sent while a turn runs are held by the agent
// and sent together, answered by one reply, when the turn ends (or at once on Stop). Each row can be edited, sent now
// (the running turn reads it at its next step), removed, or dragged to another place. A failed turn pauses the queue
// (Resume, Clear); while a card waits, the queue waits for it.
//
// queueRows(state, pending) merges the agent's queue ({items, paused}) with messages this page queued that the agent
// hasn't listed yet (pending, by client_id); both are pure and tested in utils/tests/web/chat-queue.test.mjs.

import { h, T, Icon, Btn, label11, inputSt } from './chat-ui.js';

const R = () => globalThis.React;

/** The rows to draw: the agent's held messages, then this page's not yet listed (`sending`). */
export function queueRows(state, pending = []) {
  const items = state?.items || [], have = new Set(items.map(i => i.client_id).filter(Boolean));
  return [...items.map(i => ({ ...i, key: i.id })),
    ...pending.filter(m => !have.has(m.cid)).map(m => ({ key: 'p' + m.cid, id: null, text: m.text, attachments: m.attachments, quotes: m.quotes, sending: true }))];
}

/** The strip's heading. */
export function queueLabel({ count, paused, waiting }) {
  if (paused) return 'Paused after an error';
  if (waiting) return `Queued · ${count} · waits for your answer`;
  return `Queued · ${count} · sent when this reply ends`;
}

export function QueueStrip({ rows, paused, waiting, onEdit, onRemove, onSendNow, onMove, onResume, onClear }) {
  const React = R(), { useState } = React;
  const [editing, setEditing] = useState(null), [text, setText] = useState(''), [drag, setDrag] = useState(null);
  if (!rows.length) return null;
  const save = id => { const t = text.trim(); setEditing(null); if (t) onEdit(id, t); };
  return h('div', { role: 'region', 'aria-label': 'Queued messages', 'data-queue': '',
    style: { display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8, padding: '7px 8px 8px', borderRadius: 9, border: '1px solid ' + (paused ? T.rd : T.bd), background: T.inset, maxHeight: '35vh', overflowY: 'auto', minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 } },
      h('span', { style: { ...label11, color: paused ? T.rd : T.mut, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
        queueLabel({ count: rows.length, paused, waiting })),
      !paused && !waiting ? h('span', { style: { fontSize: 11, color: T.dim, whiteSpace: 'nowrap' } }, 'Stop sends them now') : null,
      paused ? h(Btn, { kind: 'pri', sm: true, onClick: onResume }, 'Resume') : null,
      h(Btn, { kind: 'ghost', sm: true, onClick: onClear, title: 'Remove every queued message' }, 'Clear')),
    rows.map((r, i) => h('div', { key: r.key, 'data-queued': r.id || 'sending', draggable: !!r.id && editing !== r.id,
      onDragStart: e => { setDrag(r.id); e.dataTransfer.effectAllowed = 'move'; },
      onDragOver: e => { if (drag && r.id && drag !== r.id) e.preventDefault(); },
      onDrop: e => { e.preventDefault(); if (drag && r.id && drag !== r.id) onMove(drag, i); setDrag(null); },
      onDragEnd: () => setDrag(null),
      style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, padding: '4px 4px 4px 6px', borderRadius: 6, background: T.card, border: '1px solid ' + T.bd,
        opacity: r.sending || drag === r.id ? 0.6 : 1, cursor: r.id ? 'grab' : 'default' } },
      h('span', { 'aria-hidden': 'true', style: { color: T.dim, fontSize: 11, width: 14, textAlign: 'right', flex: 'none' } }, i + 1),
      r.id && editing === r.id
        ? h('input', { value: text, autoFocus: true, 'aria-label': 'Edit the queued message', onChange: e => setText(e.target.value), onBlur: () => save(r.id),
          onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); save(r.id); } else if (e.key === 'Escape') { e.preventDefault(); setEditing(null); } },
          style: { ...inputSt, flex: 1, height: 26 } })
        : h('span', { title: r.text, style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5 } }, r.text || '(replies only)'),
      r.attachments?.length ? h('span', { title: `${r.attachments.length} attached`, style: { display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, color: T.mut, flex: 'none' } }, h(Icon, { d: 'clip', size: 11 }), r.attachments.length) : null,
      r.quotes?.length ? h('span', { title: `${r.quotes.length} quote-repl${r.quotes.length === 1 ? 'y' : 'ies'}`, style: { display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, color: T.mut, flex: 'none' } }, h(Icon, { d: 'reply', size: 11 }), r.quotes.length) : null,
      r.sending ? h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, 'queuing…') : h('span', { style: { display: 'flex', gap: 1, flex: 'none' } },
        h(Btn, { kind: 'ghost', sm: true, icon: 'edit', title: 'Edit', onClick: () => { setEditing(r.id); setText(r.text || ''); } }),
        h(Btn, { kind: 'ghost', sm: true, icon: 'send', title: waiting ? 'Send now (dismisses the card that waits)' : 'Send now: the agent reads it at its next step', onClick: () => onSendNow(r.id) }),
        h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Remove', onClick: () => onRemove(r.id) })))));
}
