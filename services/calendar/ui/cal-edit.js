// The editor (calendar plan 3.5): a popover for a quick look (Edit, Delete, Done), a side sheet to edit or make
// an event or a to-do (when, repeat, alerts, calendar, busy, place, link, notes, project, priority, estimate),
// the This / This and following / All question for a repeating item, and a snackbar with Undo.

import { addDays, parse, timeText, wall, ymd } from './cal-dates.js';
import { DAYS, KINDS, choiceOf, ruleOf, words } from './cal-repeat.js';
import { I, el, icon } from './cal-style.js';

/** The body a save sends, from the sheet's fields (pure: tests/ui/edit.test.mjs). */
export function bodyOf(f) {
  const b = { kind: f.kind, title: (f.title || '').trim() };
  if (f.kind === 'event') {
    if (f.all_day) { b.start = f.date; b.end = ymd(addDays(parse(f.endDate || f.date), 1)); }
    else { b.start = `${f.date}T${f.time}`; b.end = `${f.endDate || f.date}T${f.endTime}`; }
    b.busy = f.busy || 'busy';
    b.location = f.location || '';
  } else {
    b.due = f.date ? (f.all_day || !f.time ? f.date : `${f.date}T${f.time}`) : null;
    b.priority = +f.priority || 0;
    if (f.estimate) b.estimate_min = +f.estimate;
  }
  b.rrule = f.repeat && f.repeat.kind !== 'none' ? ruleOf(f.repeat, b.start || b.due) : null;
  b.alerts = (f.alerts || []).map(Number).filter(n => n >= 0);
  if (f.calendar) b.calendar = f.calendar;
  b.notes = f.notes || '';
  b.url = f.url || '';
  b.project_id = f.project_id || null;
  return b;
}

/** The sheet's fields for an item (or a new one from a slot). */
export function fieldsOf(item, slot = {}) {
  const it = item || {}, kind = it.kind || slot.kind || 'event';
  const s = parse(it.start || it.due || slot.start || ymd(new Date())), e = parse(it.end || slot.end || wall(new Date(s.getTime() + 3600000)));
  const allDay = item ? !!it.all_day : !!slot.all_day;
  const endDay = allDay ? addDays(e, -1) : e;
  const pad = n => String(n).padStart(2, '0');
  return { id: it.id, kind, title: it.title || slot.title || '', date: ymd(s), time: `${pad(s.getHours())}:${pad(s.getMinutes())}`,
    endDate: ymd(endDay), endTime: `${pad(e.getHours())}:${pad(e.getMinutes())}`, all_day: allDay || (kind === 'todo' && String(it.due || slot.due || '').length === 10),
    repeat: choiceOf(it.rrule || slot.rrule), alerts: (it.alerts || slot.alerts || []).map(a => a.before_min ?? a), calendar: it.calendar_id || slot.calendar,
    busy: it.busy || 'busy', location: it.location || '', url: it.url || '', notes: it.notes || '', project_id: it.project_id || slot.project_id || null,
    priority: it.priority || 0, estimate: it.estimate_min || '' };
}

/** Whether a change to a repeating item must ask which occurrences it's for. */
export const asksScope = (item, occurrence) => !!(item?.rrule && occurrence);

// ---- DOM ----------------------------------------------------------------------------------------------------

export function popover(o, anchor, a) {
  const r = anchor?.getBoundingClientRect?.() || { left: innerWidth / 2 - 150, right: innerWidth / 2 + 150, top: 120, bottom: 120 };
  const left = Math.max(8, Math.min(r.right + 8 + 300 > innerWidth ? r.left - 308 : r.right + 8, innerWidth - 308));
  const top = Math.max(8, Math.min(r.top, innerHeight - 260));
  const box = el('div.cal-pop', { role: 'dialog', 'aria-label': o.title, style: { left: `${left}px`, top: `${top}px` } },
    el('h4', null, el('span.cal-dot', { style: { background: o.color, marginTop: '4px' } }), el('span', { style: { flex: 1 } }, o.title),
      el('button.cal-btn.icon.ghost', { onclick: a.close, 'aria-label': 'Close' }, icon(I.x, 14))),
    el('div.cal-muted', null, `${o.all_day ? '' : new Date(o.ts * 1000).toDateString().slice(0, 10) + ' · '}${timeText(o)}`),
    o.recurring ? el('div.cal-muted', null, '↻ ', words(o.rrule)) : null,
    o.location ? el('div.cal-muted', { style: { display: 'flex', gap: '5px', alignItems: 'center' } }, icon(I.pin, 13), o.location) : null,
    o.notes ? el('div', { style: { fontSize: '12.5px', whiteSpace: 'pre-wrap', maxHeight: '120px', overflow: 'auto' } }, o.notes) : null,
    el('div.cal-muted.cal-small', null, o.calendar, o.by_agent ? ' · made by the agent' : '', o.prep ? ' · has a prep task' : ''),
    el('div', { style: { display: 'flex', gap: '6px', marginTop: '4px', flexWrap: 'wrap' } },
      el('button.cal-btn.pri', { onclick: () => a.edit(o) }, 'Edit'),
      o.kind === 'todo' ? el('button.cal-btn', { onclick: () => a.done(o) }, o.done ? 'Not done' : 'Done') : null,
      a.mention ? el('button.cal-btn', { onclick: () => a.mention(o) }, 'Mention') : null,
      el('button.cal-btn.ghost', { onclick: () => a.remove(o) }, icon(I.trash, 14), 'Delete')));
  return box;
}

/** The sheet. a: {calendars, projects, settings, save(body, f), remove(f), close, parse(text, kind) → Promise} */
export function sheet(f, a) {
  const x = { ...f, repeat: { ...f.repeat }, alerts: [...f.alerts] };
  const root = el('div.cal-sheet', { role: 'dialog', 'aria-label': f.id ? 'Edit' : 'New' });
  const draw = () => {
    root.replaceChildren(
      el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px', borderBottom: '1px solid var(--cal-line)' } },
        el('div.cal-seg', null, ...[['event', 'Event'], ['todo', 'To-do']].map(([k, l]) => el('button', { 'aria-pressed': String(x.kind === k), onclick: () => { x.kind = k; draw(); } }, l))),
        el('span', { style: { flex: 1 } }), el('button.cal-btn.icon.ghost', { onclick: a.close, 'aria-label': 'Close' }, icon(I.x, 14))),
      el('div.bd', null,
        field('Title', inp(x, 'title', { placeholder: x.kind === 'todo' ? 'What to do' : 'What it is', autofocus: true })),
        whenFields(x, a, draw),
        repeatFields(x, draw),
        alertFields(x, draw),
        el('div.cal-two', null,
          field('Calendar', sel(x, 'calendar', (a.calendars || []).map(c => [c.id, c.name]))),
          x.kind === 'event' ? field('Shows as', sel(x, 'busy', [['busy', 'Busy'], ['free', 'Free'], ['focus', 'Focus block']]))
            : field('Priority', sel(x, 'priority', [[0, 'None'], [1, 'Low'], [2, 'Medium'], [3, 'High']]))),
        x.kind === 'todo' ? field('Takes (minutes, for planning a day)', inp(x, 'estimate', { type: 'number', min: 5, step: 5 })) : field('Place', inp(x, 'location')),
        a.projects?.length ? field('Project', sel(x, 'project_id', [['', 'None'], ...a.projects.map(p => [p.id, p.name])])) : null,
        field('Link', inp(x, 'url', { placeholder: 'https://…' })),
        field('Notes', el('textarea.cal-input', { rows: 4, oninput: e => { x.notes = e.target.value; } }, x.notes)),
        a.extra ? a.extra(x) : null),
      el('div.ft', null,
        el('button.cal-btn.pri', { onclick: () => { if (!x.title.trim()) { root.querySelector('input')?.focus(); return; } a.save(bodyOf(x), x); } }, f.id ? 'Save' : 'Add'),
        el('button.cal-btn', { onclick: a.close }, 'Cancel'), el('span', { style: { flex: 1 } }),
        f.id ? el('button.cal-btn.ghost', { onclick: () => a.remove(x) }, icon(I.trash, 14), 'Delete') : null));
    setTimeout(() => root.querySelector('[autofocus]')?.focus(), 0);
  };
  draw();
  root.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); a.close(); } });
  return root;
}

const field = (label, control) => el('label.cal-field', null, el('span', null, label), control);
const inp = (x, k, o = {}) => el('input.cal-input', { value: x[k] ?? '', ...o, oninput: e => { x[k] = e.target.value; } });
const sel = (x, k, opts) => {
  const s = el('select.cal-input', { onchange: e => { x[k] = e.target.value; } }, ...opts.map(([v, l]) => el('option', { value: v }, l)));
  s.value = x[k] ?? opts[0]?.[0] ?? '';
  return s;
};

function whenFields(x, a, draw) {
  const words = el('input.cal-input', { placeholder: 'Or type it: Fri 1pm for 90 min, every Tuesday at 9', onkeydown: async e => {
    if (e.key !== 'Enter' || !words.value.trim()) return;
    e.preventDefault();
    try {
      const p = await a.parse(words.value, x.kind);
      const g = fieldsOf({ ...p, kind: x.kind, title: x.title || p.title });
      Object.assign(x, { date: g.date, time: g.time, endDate: g.endDate, endTime: g.endTime, all_day: g.all_day, title: x.title || p.title });
      if (p.rrule) x.repeat = choiceOf(p.rrule);
      draw();
    } catch (err) { words.setCustomValidity(err?.detail || 'Couldn’t read that'); words.reportValidity(); setTimeout(() => words.setCustomValidity(''), 2500); }
  } });
  const allDay = el('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '12.5px' } },
    el('input', { type: 'checkbox', checked: x.all_day, onchange: e => { x.all_day = e.target.checked; draw(); } }), x.kind === 'todo' ? 'No time' : 'All day');
  const date = k => el('input.cal-input', { type: 'date', value: x[k], oninput: e => { x[k] = e.target.value; if (k === 'date' && x.endDate < x.date) { x.endDate = x.date; draw(); } } });
  const time = k => el('input.cal-input', { type: 'time', step: 300, value: x[k], oninput: e => { x[k] = e.target.value; } });
  const rows = x.kind === 'todo'
    ? [el('div.cal-two', null, field('Due', date('date')), x.all_day ? el('div') : field('At', time('time')))]
    : x.all_day ? [el('div.cal-two', null, field('From', date('date')), field('To', date('endDate')))]
      : [el('div.cal-two', null, field('Starts', date('date')), field('At', time('time'))), el('div.cal-two', null, field('Ends', date('endDate')), field('At', time('endTime')))];
  return el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } }, words, ...rows, allDay);
}

function repeatFields(x, draw) {
  const c = x.repeat;
  const anchorDay = DAYS[(new Date(`${x.date}T00:00`).getDay() + 6) % 7];
  const kindSel = el('select.cal-input', { onchange: e => { c.kind = e.target.value; if ((c.kind === 'weekly' || c.kind === 'custom') && !(c.days || []).length) c.days = [anchorDay]; draw(); } }, ...KINDS.map(([k, l]) => el('option', { value: k }, l)));
  kindSel.value = c.kind;
  const parts = [field('Repeats', kindSel)];
  if (c.kind === 'weekly' || (c.kind === 'custom' && (c.unit || 'week') === 'week'))
    parts.push(el('div.cal-days-pick', null, ...DAYS.map(d => el('button', { type: 'button', 'aria-pressed': String((c.days || []).includes(d)),
      onclick: () => { c.days = (c.days || []).includes(d) ? c.days.filter(y => y !== d) : [...(c.days || []), d]; draw(); } }, d[0] + d[1].toLowerCase()))));
  if (c.kind === 'custom') {
    const unit = el('select.cal-input', { onchange: e => { c.unit = e.target.value; draw(); } }, ...[['day', 'days'], ['week', 'weeks'], ['month', 'months'], ['year', 'years']].map(([k, l]) => el('option', { value: k }, l)));
    unit.value = c.unit || 'week';
    parts.push(el('div.cal-two', null, field('Every', el('input.cal-input', { type: 'number', min: 1, value: c.interval || 1, oninput: e => { c.interval = Math.max(1, +e.target.value || 1); } })), field('Unit', unit)));
  }
  if (c.kind !== 'none') {
    const e = c.end || (c.end = { type: 'never' });
    const endSel = el('select.cal-input', { onchange: ev => { e.type = ev.target.value; draw(); } }, el('option', { value: 'never' }, 'Never'), el('option', { value: 'until' }, 'On a date'), el('option', { value: 'count' }, 'After a number of times'));
    endSel.value = e.type;
    parts.push(el('div.cal-two', null, field('Ends', endSel),
      e.type === 'until' ? field('On', el('input.cal-input', { type: 'date', value: e.until || '', oninput: ev => { e.until = ev.target.value; } }))
        : e.type === 'count' ? field('Times', el('input.cal-input', { type: 'number', min: 1, value: e.count || 10, oninput: ev => { e.count = +ev.target.value; } })) : el('div')));
    parts.push(el('div.cal-muted.cal-small', null, '↻ ', words(ruleOf(c, x.date))));
  }
  return el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } }, ...parts);
}

function alertFields(x, draw) {
  const label = m => m === 0 ? (x.kind === 'todo' ? 'At the time' : 'When it starts') : m % 1440 === 0 ? `${m / 1440} day${m > 1440 ? 's' : ''} before` : m % 60 === 0 ? `${m / 60} h before` : `${m} min before`;
  const add = el('select.cal-input', { style: { width: 'auto' }, onchange: e => { const m = +e.target.value; if (!x.alerts.includes(m) && x.alerts.length < 5) x.alerts.push(m); draw(); } },
    el('option', { value: '' }, '+ Alert'), ...[0, 5, 10, 15, 30, 60, 120, 1440, 2880, 10080].map(m => el('option', { value: m }, label(m))));
  return field('Alerts (in the app)', el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' } },
    ...x.alerts.sort((p, q) => p - q).map(m => el('span.cal-btn', { style: { cursor: 'default' } }, icon(I.bell, 12), label(m),
      el('button.cal-btn.icon.ghost', { style: { width: '20px', height: '20px' }, onclick: () => { x.alerts = x.alerts.filter(y => y !== m); draw(); }, 'aria-label': 'Remove alert' }, icon(I.x, 11)))), add));
}

/** Which occurrences: resolves 'this' | 'following' | 'all', or null (cancelled). */
export function askScope(verb = 'Change') {
  return new Promise(resolve => {
    const done = v => { box.remove(); resolve(v); };
    const box = el('div.cal-dialog', { onclick: e => { if (e.target === box) done(null); } },
      el('div', { role: 'dialog', 'aria-label': `${verb} a repeating item` },
        el('strong', null, `${verb} a repeating item`),
        el('div.cal-muted', null, 'Which occurrences?'),
        el('button.cal-btn', { onclick: () => done('this') }, 'This one'),
        el('button.cal-btn', { onclick: () => done('following') }, 'This and the following ones'),
        el('button.cal-btn', { onclick: () => done('all') }, 'All of them'),
        el('button.cal-btn.ghost', { onclick: () => done(null) }, 'Cancel')));
    box.addEventListener('keydown', e => { if (e.key === 'Escape') done(null); });
    document.body.append(box);
    box.querySelector('button')?.focus();
  });
}

/** A snackbar at the bottom with an optional Undo, gone after 8 s. */
export function snack(text, undo) {
  document.querySelector('.cal-snack')?.remove();
  const box = el('div.cal-snack', { role: 'status' }, el('span', null, text),
    undo ? el('button.cal-btn', { onclick: () => { box.remove(); undo(); } }, 'Undo') : null,
    el('button.cal-btn.icon.ghost', { onclick: () => box.remove(), 'aria-label': 'Dismiss' }, icon(I.x, 13)));
  document.body.append(box);
  setTimeout(() => box.remove(), 8000);
  return box;
}
