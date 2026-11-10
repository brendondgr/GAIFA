// Month and agenda views (calendar plan 3.4). Month: weeks from the setting's first day, all-day and multi-day
// items as bars across days, up to three items a day then "+N more" (opens the day), today ringed, a click on
// empty space starting an all-day item. Agenda: 30 days from the date, by day, empty days left out, Load more.

import { addDays, dow, hhmm, MONTHS, sameDay, shortDay, timeText, WEEKDAYS } from './cal-dates.js';
import { agendaGroups, dayItems, layoutAllDay, weeksOf } from './cal-layout.js';
import { el } from './cal-style.js';

const ymdOf = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** v: {days, month (Date in the month), occs, settings, now, on: {open, create, day}} */
export function renderMonth(v) {
  const now = v.now || new Date(), ws = v.settings?.week_start || 0;
  const names = Array.from({ length: 7 }, (_, i) => WEEKDAYS[(i + ws) % 7]);
  const wrap = el('div.cal-month');
  const body = el('div', { style: { display: 'flex', flexDirection: 'column', minHeight: 0 } });
  body.append(el('div.cal-mhd', null, ...names.map(n => el('div', null, n))));
  for (const week of weeksOf(v.days)) {
    const ad = layoutAllDay(v.occs, week, 3);
    const row = el('div.cal-week');
    week.forEach((d, i) => {
      const barsHere = ad.bars.filter(b => b.start <= i && i < b.start + b.span).length;
      const { shown, more } = dayItems(v.occs, d, Math.min(3, barsHere), 3);
      const cell = el('div.cal-cell', { class: [d.getMonth() !== v.month.getMonth() ? 'out' : '', sameDay(d, now) ? 'today' : '', dow(d) >= 5 ? 'wkend' : ''].join(' '),
        onclick: e => { if (e.target === cell || e.target.classList.contains('spacer')) v.on.create({ start: ymdOf(d), end: ymdOf(addDays(d, 1)), all_day: true }); } },
      el('span.n', { onclick: e => { e.stopPropagation(); v.on.day(d); }, title: shortDay(d), role: 'button' }, d.getDate()),
      el('div.spacer', { style: { height: `${Math.min(3, ad.rows) * 22}px`, flex: 'none' } }),
      ...shown.map(o => chip(o, v)),
      more + ad.more[i] ? el('span.cal-more', { onclick: e => { e.stopPropagation(); v.on.day(d); } }, `+${more + ad.more[i]} more`) : null);
      row.append(cell);
    });
    for (const b of ad.bars) {
      const o = b.occ;
      row.append(el('div.cal-bar', { class: (o.kind === 'todo' ? 'todo ' : '') + (o.done ? 'done' : ''), style: { '--c': o.color || '#4F7CFF', left: `calc(100% / 7 * ${b.start} + 4px)`, width: `calc(100% / 7 * ${b.span} - 8px)`, top: `${34 + b.row * 22}px` },
        title: `${o.title} · ${timeText(o)}`, onclick: e => { e.stopPropagation(); v.on.open(o, e.currentTarget); } }, o.kind === 'todo' ? (o.done ? '✓ ' : '○ ') : '', o.title));
    }
    body.append(row);
  }
  wrap.append(body);
  return wrap;
}

function chip(o, v) {
  return el('div.cal-chip', { style: { '--c': o.color || '#4F7CFF' }, title: `${o.title} · ${timeText(o)}`, onclick: e => { e.stopPropagation(); v.on.open(o, e.currentTarget); } },
    el('span.d', { style: o.kind === 'todo' ? { borderRadius: '2px', background: 'transparent', border: `1.5px solid ${o.color}` } : null }),
    el('span.tm', null, hhmm(new Date(o.ts * 1000))), el('span.tt', { style: { textDecoration: o.done ? 'line-through' : 'none' } }, o.title));
}

/** v: {from, to, occs, now, on: {open, more}} */
export function renderAgenda(v) {
  const now = v.now || new Date(), groups = agendaGroups(v.occs, v.from, v.to);
  const wrap = el('div.cal-agenda');
  if (!groups.length) wrap.append(el('div.cal-muted', { style: { padding: '40px 0', textAlign: 'center' } }, 'Nothing in the next 30 days.'));
  for (const g of groups) {
    wrap.append(el('div.cal-aday', null,
      el('div.dd', { class: sameDay(g.day, now) ? 'today' : '' }, sameDay(g.day, now) ? 'Today' : sameDay(g.day, addDays(now, 1)) ? 'Tomorrow' : shortDay(g.day),
        g.day.getFullYear() !== now.getFullYear() ? el('div.cal-small', null, g.day.getFullYear()) : null),
      el('div', null, ...g.items.map(o => el('div.cal-arow', { onclick: e => v.on.open(o, e.currentTarget), tabIndex: 0, role: 'button' },
        el('span.cal-dot', { style: { background: o.kind === 'todo' ? 'transparent' : o.color, border: o.kind === 'todo' ? `1.5px solid ${o.color}` : 'none' } }),
        el('span.tm', null, timeText(o)),
        el('span.tt', { style: { textDecoration: o.done ? 'line-through' : 'none' } }, o.title, o.recurring ? el('span.cal-rep', null, '↻') : null),
        o.location ? el('span.cal-muted', { style: { flex: 'none', maxWidth: '30%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, o.location) : null,
          o.project_id ? el('span.cal-muted.cal-small', { style: { flex: 'none' } }, '◆ project') : null)))));
  }
  wrap.append(el('div', { style: { padding: '14px 0', textAlign: 'center' } }, el('button.cal-btn', { onclick: v.on.more }, 'Load more')));
  return wrap;
}

export { MONTHS };
