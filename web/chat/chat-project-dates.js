// A project's page's Dates panel (calendar plan 5.3): the project's calendar items in the next 14 days, from the
// calendar mod, and New (the item made in this project). Shown only when the calendar mod answers.

import { h, T, Btn } from './chat-ui.js';
import { Panel } from './chat-project-panels.js';

const R = () => globalThis.React;
export const DATES_DAYS = 14;

/** The range a project's panel asks for: today's local midnight and 14 days on. */
export function datesRange(now = new Date()) {
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return { from: a.toISOString(), to: new Date(a.getFullYear(), a.getMonth(), a.getDate() + DATES_DAYS).toISOString() };
}

/** "Thu 10 Nov · 13:00" / "Thu 10 Nov · all day" / "due Thu 10 Nov". */
export function dateWords(o) {
  const s = String(o.start || o.due || ''), d = new Date(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
  const day = `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${d.getDate()} ${d.toLocaleDateString('en-US', { month: 'short' })}`;
  if (o.kind === 'todo') return `due ${day}${o.all_day ? '' : ' ' + s.slice(11, 16)}`;
  return `${day} · ${o.all_day ? 'all day' : s.slice(11, 16)}`;
}

export function DatesPanel({ p, api }) {
  const React = R(), [list, setList] = React.useState(undefined);
  React.useEffect(() => {
    let alive = true;
    const { from, to } = datesRange();
    Promise.resolve(api?.callService?.('calendar', 'GET', `/v1/range?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&project=${encodeURIComponent(p.id)}`))
      .then(r => { if (alive) setList(r?.json?.occurrences || []); }, () => { if (alive) setList(null); });
    return () => { alive = false; };
  }, [p.id]);
  if (list === null) return null;                                // no calendar mod: no panel
  const add = () => { location.hash = `#/calendar?new=${encodeURIComponent(p.id)}`; };
  return h(Panel, { title: 'Dates', icon: 'clock', count: list ? list.length : null,
    actions: h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'New', onClick: add }) },
    list === undefined ? h('span', { style: { fontSize: 12, color: T.mut } }, 'Loading…')
      : !list.length ? h('span', { style: { fontSize: 12, color: T.mut } }, `Deadlines and events in this project's next ${DATES_DAYS} days, from the Calendar. Its chats see them.`)
        : list.map(o => h('a', { key: o.id, href: `#/calendar?item=${encodeURIComponent(o.id)}`, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px', fontSize: 12.5, color: T.tx, textDecoration: 'none', minWidth: 0 } },
          h('span', { style: { width: 8, height: 8, borderRadius: 2, background: o.color || T.acc, flex: 'none' } }),
          h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: o.done ? 'line-through' : 'none' } }, o.title),
          h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, dateWords(o)))));
}
