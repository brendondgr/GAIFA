// The Calendar page's mock (calendar plan 3.2): the client's methods in memory, for ?mock and the tests. Two
// calendars, a week of events around today (a repeating one, an all-day one, an overlap), to-dos and fired
// alerts. Repeats are expanded simply (DAILY, WEEKLY with BYDAY, MONTHLY by day, YEARLY; COUNT and UNTIL).

import { DAY_MS, addDays, parse, startOfDay, wall, ymd } from './cal-dates.js';
import { parts } from './cal-repeat.js';

const DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];

export function createMockClient(now = new Date()) {
  let seq = 1, rev = 1;
  const id = p => `${p}_${(seq++).toString(16).padStart(6, '0')}`;
  const cals = [{ id: 'cal_home', name: 'Personal', color: '#4F7CFF', is_default: true, hidden: false },
    { id: 'cal_work', name: 'Work', color: '#2BB673', is_default: false, hidden: false }];
  const items = [], undos = {}, fired = [];
  let settings = { work_hours: [['09:00', '17:00'], ['09:00', '17:00'], ['09:00', '17:00'], ['09:00', '17:00'], ['09:00', '17:00'], null, null],
    event_alerts: [10], todo_alerts: [0], allday_alert: '09:00', week_start: 0, date_order: 'mdy', agenda_in_prompt: true, default_view: 'week' };
  const t0 = startOfDay(now), at = (d, h, m = 0) => wall(new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + d, h, m));
  const add = (o) => { const it = { id: id('c'), kind: 'event', calendar_id: 'cal_home', notes: '', location: '', url: '', all_day: false, rrule: null, exdates: [], alerts: [{ before_min: 10 }],
    priority: 0, busy: 'busy', project_id: null, done_at: null, touched_by: 'you', source: { kind: 'you' }, overrides: {}, ...o }; items.push(it); rev++; return it; };
  add({ title: 'Standup', start: at(-dow(t0), 9, 15), end: at(-dow(t0), 9, 30), rrule: 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', calendar_id: 'cal_work' });
  add({ title: 'Lunch with Sam', start: at(1, 12, 30), end: at(1, 13, 30), location: 'Café Nero' });
  add({ title: 'Design review', start: at(1, 13), end: at(1, 14, 30), calendar_id: 'cal_work' });
  add({ title: 'Focus: thesis', start: at(2, 9), end: at(2, 11, 30), busy: 'focus' });
  add({ title: 'Conference', start: ymd(addDays(t0, 3)), end: ymd(addDays(t0, 5)), all_day: true, calendar_id: 'cal_work' });
  add({ title: 'Dentist', start: at(0, 16), end: at(0, 16, 45) });
  add({ title: 'Pay rent', kind: 'todo', due: ymd(addDays(t0, 2)), all_day: true, start: null, end: null, alerts: [{ before_min: 0 }] });
  add({ title: 'Call the bank', kind: 'todo', due: at(0, 10), start: null, end: null, priority: 2 });
  add({ title: 'Return library books', kind: 'todo', due: ymd(addDays(t0, -2)), all_day: true, start: null, end: null });
  fired.push({ id: 'f_mock1', item_id: items[5].id, occurrence: items[5].start, title: 'Dentist', body: 'in 10 min · 16:00–16:45', kind: 'event', state: 'unread', alert_at: now / 1000 - 300, late: 0 });

  function dow(d) { return (d.getDay() + 6) % 7; }
  const cal = cid => cals.find(c => c.id === cid) || cals[0];
  const view = it => ({ ...it, calendar: cal(it.calendar_id).name, color: cal(it.calendar_id).color, repeat: it.rrule || null, by_agent: it.touched_by === 'agent' });

  function starts(it, from, to) {
    const anchor = parse(it.kind === 'event' ? it.start : it.due);
    if (!it.rrule) return [anchor];
    const p = parts(it.rrule), n = +(p.INTERVAL || 1), until = p.UNTIL ? parse(`${p.UNTIL.slice(0, 4)}-${p.UNTIL.slice(4, 6)}-${p.UNTIL.slice(6, 8)}T23:59`) : null;
    const out = [], max = +(p.COUNT || 100000), byday = (p.BYDAY || '').split(',').filter(Boolean);
    for (let d = new Date(anchor), k = 0, c = 0; d < to && c < max && k < 3000; k++) {
      let ok = true;
      const diff = Math.round((startOfDay(d) - startOfDay(anchor)) / DAY_MS);
      if (p.FREQ === 'DAILY') ok = diff % n === 0;
      else if (p.FREQ === 'WEEKLY') ok = (byday.length ? byday.includes(DAYS[dow(d)]) : dow(d) === dow(anchor)) && Math.floor(diff / 7) % n === 0;
      else if (p.FREQ === 'MONTHLY') ok = p.BYMONTHDAY === '-1' ? addDays(d, 1).getDate() === 1 : d.getDate() === +(p.BYMONTHDAY || anchor.getDate());
      else if (p.FREQ === 'YEARLY') ok = d.getDate() === anchor.getDate() && d.getMonth() === anchor.getMonth();
      if (until && d > until) break;
      if (ok) { c++; if (d >= addDays(from, -40)) out.push(new Date(d)); }
      d = addDays(d, 1);
    }
    return out;
  }
  function occs(from, to, kinds) {
    const out = [];
    for (const it of items.filter(i => !i.deleted_at && !cal(i.calendar_id).hidden && (!kinds || kinds.includes(i.kind)))) {
      const dur = it.kind === 'event' ? parse(it.end) - parse(it.start) : 0;
      for (const s of starts(it, from, to)) {
        const key = it.all_day ? ymd(s) : wall(s);
        if (it.exdates.includes(key)) continue;
        const ov = it.overrides[key] || {};
        const st = ov.start ? parse(ov.start) : s, en = new Date(st.getTime() + dur);
        const o = { ...view(it), id: `${it.id}@${key}`, item_id: it.id, occurrence: key, title: ov.title || it.title, recurring: !!it.rrule,
          start: it.all_day ? ymd(st) : wall(st), end: it.kind === 'todo' ? null : it.all_day ? ymd(en) : wall(en), ts: st.getTime() / 1000,
          end_ts: it.kind === 'todo' ? null : en.getTime() / 1000, due: it.kind === 'todo' ? (it.all_day ? ymd(st) : wall(st)) : undefined,
          done: !!(it.rrule ? ov.done_at : it.done_at) };
        const e = (o.end_ts ?? o.ts) * 1000;
        if (st < to && (e > from || (st >= from && st < to))) out.push(o);
      }
    }
    return out.sort((a, b) => a.ts - b.ts);
  }
  const write = (ids, fn) => {
    const snap = ids.map(i => [i, JSON.parse(JSON.stringify(items.find(x => x.id === i) || null))]);
    const { made, ...r } = fn(), u = id('u');
    undos[u] = made ? [...snap, [made, null]] : snap; rev++;
    return { ...r, undo: `/api/s/calendar/v1/undo/${u}` };
  };
  const get = iid => { const it = items.find(x => x.id === iid && !x.deleted_at); if (!it) throw Object.assign(new Error('not found'), { status: 404, detail: 'not found' }); return it; };
  const norm = (b, base = {}) => {
    const o = { ...b };
    if (o.when) { const d = parse(o.when); if (!isNaN(d)) { o.start = wall(d); o.end = wall(new Date(d.getTime() + 3600000)); } delete o.when; }
    if (o.calendar) { o.calendar_id = (cals.find(c => c.id === o.calendar || c.name.toLowerCase() === String(o.calendar).toLowerCase()) || cals[0]).id; delete o.calendar; }
    if (o.alerts) o.alerts = o.alerts.map(a => typeof a === 'number' ? { before_min: a } : a);
    if ((o.start || base.start) && (o.kind || base.kind) !== 'todo') o.all_day = String(o.start || base.start).length === 10;
    return o;
  };

  return {
    mock: true,
    status: async () => ({ rev, stats: [] }),
    settings: async () => settings,
    patchSettings: async b => (settings = { ...settings, ...b }),
    calendars: async () => cals.map(c => ({ ...c })),
    addCalendar: async b => { const c = { id: id('cal'), name: b.name, color: b.color || '#9B6CFF', is_default: false, hidden: false }; cals.push(c); rev++; return c; },
    patchCalendar: async (cid, b) => { Object.assign(cal(cid), b); rev++; return cal(cid); },
    deleteCalendar: async cid => { const i = cals.findIndex(c => c.id === cid); if (i > 0) cals.splice(i, 1); rev++; return { deleted: cid }; },
    range: async (from, to, o = {}) => ({ occurrences: occs(new Date(from), new Date(to), o.kinds ? o.kinds.split(',') : null), rev }),
    todos: async () => ({ todos: occs(addDays(now, -60), addDays(now, 60), ['todo']).filter(o => !o.done)
      .concat(items.filter(i => i.kind === 'todo' && !i.due && !i.done_at && !i.deleted_at).map(i => ({ ...view(i), item_id: i.id, ts: null, done: false }))), rev }),
    item: async iid => view(get(iid)),
    add: async b => write([], () => { const it = add({ ...norm(b), touched_by: 'you' }); return { item: view(it), assumed: [], made: it.id }; }),
    patch: async (iid, b, o = {}) => write([iid], () => {
      const it = get(iid), f = norm(b, it);
      if (o.scope === 'this' && o.occurrence) it.overrides[o.occurrence] = { ...(it.overrides[o.occurrence] || {}), ...f };
      else Object.assign(it, f);
      return { item: view(it), scope: o.scope || 'all' };
    }),
    remove: async (iid, o = {}) => write([iid], () => {
      const it = get(iid);
      if (o.scope === 'this' && o.occurrence && it.rrule) it.exdates.push(o.occurrence); else it.deleted_at = Date.now();
      return { deleted: 'item', note: 'moved to the trash, kept 30 days' };
    }),
    done: async (iid, occurrence, undone) => write([iid], () => {
      const it = get(iid);
      if (it.rrule && occurrence) it.overrides[occurrence] = { ...(it.overrides[occurrence] || {}), done_at: undone ? null : Date.now() / 1000 };
      else it.done_at = undone ? null : Date.now() / 1000;
      return { item: view(it), done: !undone };
    }),
    parse: async (text, kind = 'event') => {
      const m = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)/i.exec(text), d = new Date(t0);
      if (/tomorrow/i.test(text)) d.setDate(d.getDate() + 1);
      if (!m) return { kind, title: text.trim(), all_day: true, start: ymd(d), end: ymd(addDays(d, 1)), assumed: ['no time: all day'] };
      const h = (+m[1] % 12) + (m[3].toLowerCase() === 'pm' ? 12 : 0);
      d.setHours(h, +(m[2] || 0));
      return { kind, title: text.replace(m[0], '').replace(/tomorrow/i, '').trim(), all_day: false, start: wall(d), end: wall(new Date(d.getTime() + 3600000)), due: kind === 'todo' ? wall(d) : undefined, assumed: ['no end: 1 hour'] };
    },
    search: async q => ({ items: items.filter(i => !i.deleted_at && i.title.toLowerCase().includes(q.toLowerCase())).map(view) }),
    trash: async () => ({ items: items.filter(i => i.deleted_at).map(view) }),
    restore: async iid => { const it = items.find(x => x.id === iid); delete it.deleted_at; rev++; return { item: view(it) }; },
    undo: async path => {
      const u = String(path).split('/').pop(), snap = undos[u] || [];
      for (const [iid, row] of snap) { const i = items.findIndex(x => x.id === iid); if (i >= 0) items.splice(i, 1); if (row) items.push(row); }
      delete undos[u]; rev++; return { undone: snap.map(s => s[0]) };
    },
    alerts: async () => ({ alerts: fired.slice(), unread: fired.filter(f => f.state === 'unread').length }),
    alert: async (fid, act, minutes, at) => {
      const f = fired.find(x => x.id === fid);
      if (f) { f.state = act === 'snooze' ? 'snoozed' : act; if (act === 'snooze') f.snooze_until = at === 'tomorrow' ? new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + 1, 9).getTime() / 1000 : Date.now() / 1000 + (minutes || 10) * 60; }
      return f;
    },
    seenAll: async () => { fired.forEach(f => { if (f.state === 'unread') f.state = 'seen'; }); return { seen: 1 }; },
    importIcs: async () => ({ id: 'pr_mock', kind: 'ics', items: [{ pid: '1', fields: { title: 'Imported event', start: at(6, 10), end: at(6, 11), kind: 'event' }, view: { title: 'Imported event', start: at(6, 10), end: at(6, 11), kind: 'event' } }], skipped: [], count: 1 }),
    proposal: async () => ({ id: 'pr_mock', items: [], skipped: [] }),
    accept: async () => { add({ title: 'Imported event', start: at(6, 10), end: at(6, 11) }); return { added: 1, undo: '/api/s/calendar/v1/undo/none' }; },
    plan: async () => ({ id: 'pr_plan', kind: 'plan', items: [], skipped: [], count: 0 }),
    exportUrl: () => '#',
  };
}
