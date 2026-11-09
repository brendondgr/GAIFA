// Day and week views (calendar plan 3.3): day headers, the all-day row, hour rows of 48 px with working hours
// shaded, events laid out side by side (cal-layout.js), timed to-dos as chips, the now-line, and drags:
// on empty space to create (15-minute steps), an event to move it (across days too), its bottom edge to resize.

import { addDays, dow, hhmm, minutesOf, sameDay, startOfDay, timeText, WEEKDAYS, wall } from './cal-dates.js';
import { HOUR_PX, layoutAllDay, layoutDay, minutesAt } from './cal-layout.js';
import { el } from './cal-style.js';

const GUTTER = 56;

/** v: {days, occs, settings, now, on: {open(occ, node), create({start, end, all_day}), move(occ, start, end), day(date)}} */
export function renderGrid(v) {
  const n = v.days.length, cols = `${GUTTER}px repeat(${n}, minmax(0, 1fr))`, now = v.now || new Date();
  const wrap = el('div.cal-body');
  // day headers
  wrap.append(el('div.cal-days', { style: { gridTemplateColumns: cols } }, el('div'),
    ...v.days.map(d => el('div.cal-dayhd', { class: [sameDay(d, now) ? 'today' : '', dow(d) >= 5 ? 'wkend' : ''].join(' '), onclick: () => v.on.day(d), title: 'Open this day' },
      WEEKDAYS[dow(d)], el('b', null, d.getDate())))));
  // the all-day row
  const ad = layoutAllDay(v.occs, v.days, 3), rows = Math.max(1, ad.rows) + (ad.more.some(Boolean) ? 1 : 0);
  const allday = el('div.cal-allday', { style: { gridTemplateColumns: cols, height: `${rows * 22 + 6}px` } },
    el('div.cal-gutter', { style: { fontSize: '10.5px', paddingTop: '6px' } }, 'all day'), ...v.days.map(d => el('div', { style: { borderLeft: '1px solid var(--cal-line)' }, ondblclick: () => v.on.create({ start: ymdOf(d), end: ymdOf(addDays(d, 1)), all_day: true }) })));
  const colW = `((100% - ${GUTTER}px) / ${n})`;
  for (const b of ad.bars) {
    const o = b.occ;
    allday.append(el('div.cal-bar', { class: (o.kind === 'todo' ? 'todo ' : '') + (o.done ? 'done' : ''), style: { '--c': o.color || '#4F7CFF', left: `calc(${GUTTER}px + ${colW} * ${b.start} + 2px)`, width: `calc(${colW} * ${b.span} - 4px)`, top: `${3 + b.row * 22}px` },
      title: `${o.title} · ${timeText(o)}`, onclick: e => v.on.open(o, e.currentTarget) }, o.kind === 'todo' ? (o.done ? '✓ ' : '○ ') : '', o.title, o.recurring ? el('span.cal-rep', null, '↻') : null));
  }
  ad.more.forEach((m, i) => { if (m) allday.append(el('div.cal-more', { style: { position: 'absolute', left: `calc(${GUTTER}px + ${colW} * ${i} + 6px)`, top: `${3 + Math.max(1, ad.rows) * 22}px` }, onclick: () => v.on.day(v.days[i]) }, `+${m} more`)); });
  wrap.append(allday);
  // hours
  const scroll = el('div.cal-scroll'), grid = el('div.cal-grid', { style: { gridTemplateColumns: cols, height: `${24 * HOUR_PX}px` } });
  grid.append(el('div.cal-gutter', null, ...Array.from({ length: 24 }, (_, hr) => el('div', null, hr ? `${String(hr).padStart(2, '0')}:00` : ''))));
  const colEls = v.days.map(d => {
    const col = el('div.cal-col', { class: dow(d) >= 5 ? 'wkend' : '' });
    col.dataset.day = ymdOf(d);
    const wh = v.settings?.work_hours?.[dow(d)];
    if (wh) { const [a, b] = wh.map(t => +t.slice(0, 2) * 60 + +t.slice(3)); col.append(el('div.cal-work', { style: { top: `${a * HOUR_PX / 60}px`, height: `${(b - a) * HOUR_PX / 60}px` } })); }
    for (const box of layoutDay(v.occs, d)) col.append(eventBox(box, v));
    for (const o of v.occs.filter(o => o.kind === 'todo' && !o.all_day && sameDay(new Date(o.ts * 1000), d)))
      col.append(el('div.cal-todo', { style: { top: `${minutesOf(new Date(o.ts * 1000)) * HOUR_PX / 60 - 9}px`, '--c': o.color }, title: `${o.title} · ${timeText(o)}`, onclick: e => v.on.open(o, e.currentTarget) },
        el('span', { style: { color: o.color } }, o.done ? '✓' : '○'), el('span', { style: { textDecoration: o.done ? 'line-through' : 'none' } }, o.title)));
    if (sameDay(d, now)) col.append(el('div.cal-now', { style: { top: `${minutesOf(now) * HOUR_PX / 60}px` } }));
    return col;
  });
  grid.append(...colEls);
  scroll.append(grid);
  wrap.append(scroll);
  dragging(scroll, grid, colEls, v);
  // 07:00, or an hour and a half before now on a view with today (calendar plan 3.3); the shell calls it once mounted
  wrap.scrollToStart = () => { scroll.scrollTop = Math.max(0, (v.days.some(d => sameDay(d, now)) ? minutesOf(now) - 90 : 7 * 60) * HOUR_PX / 60); };
  return wrap;
}

const ymdOf = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function eventBox(box, v) {
  const o = box.occ, short = box.height < 34;
  const node = el('div.cal-ev', { class: [o.busy === 'focus' ? 'focus' : '', o.busy === 'free' ? 'free' : ''].join(' '),
    style: { '--c': o.color || '#4F7CFF', top: `${box.top}px`, height: `${box.height - 2}px`, left: `calc(${box.col} * 100% / ${box.cols} + 2px)`, width: `calc(100% / ${box.cols} - 4px)` },
    title: `${o.title} · ${timeText(o)}${o.location ? ' · ' + o.location : ''}`, tabIndex: 0, role: 'button', 'aria-label': `${o.title}, ${timeText(o)}` },
  el('div.t', null, o.title, o.recurring ? el('span.cal-rep', null, '↻') : null), short ? null : el('div.s', null, timeText(o) + (o.location ? ' · ' + o.location : '')), el('div.rs'));
  node.dataset.occ = o.id;
  node.addEventListener('keydown', e => { if (e.key === 'Enter') v.on.open(o, node); });
  return node;
}

/** Pointer drags on the grid: create, move, resize. A press that doesn't move is a click (opens the event). */
function dragging(scroll, grid, cols, v) {
  let drag = null;
  const colAt = x => cols.findIndex(c => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right; });
  const yIn = (c, y) => y - c.getBoundingClientRect().top;
  grid.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const evn = e.target.closest('.cal-ev'), ci = colAt(e.clientX);
    if (ci < 0 && !evn) return;
    if (evn) {
      const o = v.occs.find(x => x.id === evn.dataset.occ);
      if (!o) return;
      drag = { kind: e.target.classList.contains('rs') ? 'resize' : 'move', o, node: evn, x0: e.clientX, y0: e.clientY, moved: false,
        start: new Date(o.ts * 1000), end: new Date(o.end_ts * 1000), ci0: colAt(e.clientX) };
    } else {
      const m = minutesAt(yIn(cols[ci], e.clientY));
      drag = { kind: 'create', ci, m0: m, m1: m + 30, x0: e.clientX, y0: e.clientY, moved: false };
    }
    grid.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  grid.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.abs(e.clientY - drag.y0) < 4 && Math.abs(e.clientX - drag.x0) < 4) return;
    drag.moved = true;
    if (drag.kind === 'create') {
      const m = minutesAt(yIn(cols[drag.ci], e.clientY));
      drag.m1 = Math.max(drag.m0 + 15, m);
      ghost(drag, cols[drag.ci], drag.m0, drag.m1, 'New event');
    } else {
      const dy = Math.round((e.clientY - drag.y0) / (HOUR_PX / 4)) * 15, ci = drag.kind === 'move' ? Math.max(0, colAt(e.clientX)) : drag.ci0;
      const dd = drag.kind === 'move' ? (ci < 0 ? 0 : ci - drag.ci0) : 0;
      const s = drag.kind === 'move' ? new Date(drag.start.getTime() + dy * 60000 + dd * 86400000) : drag.start;
      const en = drag.kind === 'move' ? new Date(drag.end.getTime() + dy * 60000 + dd * 86400000) : new Date(Math.max(drag.start.getTime() + 15 * 60000, drag.end.getTime() + dy * 60000));
      drag.ns = s; drag.ne = en;
      drag.node.style.opacity = '.35';
      const col = cols[Math.max(0, Math.min(cols.length - 1, drag.ci0 + dd))], base = startOfDay(s);
      ghost(drag, col, Math.round((s - base) / 60000), Math.round((en - base) / 60000), `${drag.o.title} · ${hhmm(s)}–${hhmm(en)}`, drag.o.color);
    }
  });
  const end = e => {
    if (!drag) return;
    const d = drag; drag = null;
    d.ghostEl?.remove();
    if (d.node) d.node.style.opacity = '';
    try { grid.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (!d.moved) { if (d.o) v.on.open(d.o, d.node); else { const day = v.days[d.ci], s = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, d.m0); v.on.create({ start: wall(s), end: wall(new Date(s.getTime() + 3600000)), all_day: false }); } return; }
    if (d.kind === 'create') {
      const day = v.days[d.ci], s = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, d.m0), en = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, d.m1);
      v.on.create({ start: wall(s), end: wall(en), all_day: false });
    } else if (d.ns && (d.ns.getTime() !== d.start.getTime() || d.ne.getTime() !== d.end.getTime())) v.on.move(d.o, wall(d.ns), wall(d.ne));
  };
  grid.addEventListener('pointerup', end);
  grid.addEventListener('pointercancel', end);
}

function ghost(drag, col, m0, m1, label, color = 'var(--acc,#FFB224)') {
  if (!drag.ghostEl) drag.ghostEl = el('div.cal-ev.ghost', { style: { '--c': color, left: '2px', right: '2px' } }, el('div.t'));
  if (drag.ghostEl.parentNode !== col) col.append(drag.ghostEl);
  drag.ghostEl.style.top = `${m0 * HOUR_PX / 60}px`;
  drag.ghostEl.style.height = `${Math.max(14, (m1 - m0) * HOUR_PX / 60 - 2)}px`;
  drag.ghostEl.firstChild.textContent = label;
}
