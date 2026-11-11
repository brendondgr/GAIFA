// The Calendar's side panel in Chat (calendar plan 7.2; `[ui] chat_panel`): Day · Week, ‹ Today ›, a mini month
// folded under the date; Day as a compact hour column (36 px rows from the first item or 08:00, the now-line), Week
// as seven days of items; then to-dos due and overdue (a tick completes one) and unread reminders. A click opens the
// item's popover, whose Mention puts it into the composer. It follows the mod's `rev`.

import { addDays, hhmm, minutesOf, parse, rangeOf, sameDay, shortDay, startOfDay, timeText, WEEKDAYS, MONTHS } from './cal-dates.js';
import { createClient, useMock } from './cal-api.js';
import { createMockClient } from './cal-mock.js';
import { layoutDay } from './cal-layout.js';
import { popover } from './cal-edit.js';
import { reminderActs } from './cal-remind.js';
import { I, el, ensureCss, icon } from './cal-style.js';

export const ROW_PX = 36;

/** The hour the day column starts at: the first timed item's hour, else 8 (7 at the latest when something's before 8). */
export function firstHour(occs) {
  const timed = occs.filter(o => !o.all_day && o.kind === 'event').map(o => new Date(o.ts * 1000).getHours());
  return timed.length ? Math.min(8, Math.min(...timed)) : 8;
}

/** What Mention puts in the message: the item's title, when and id, so the agent can find it. */
export function mentionText(o) {
  const d = new Date(o.ts * 1000);
  return `“${o.title}” (calendar item ${o.item_id}, ${shortDay(d)}${o.all_day ? '' : ' ' + hhmm(d)})`;
}

/** Week: seven days from the date's week start, each with its items in order. */
export function weekDays(occs, date, weekStart = 0) {
  return rangeOf('week', date, weekStart).days.map(d => ({ day: d, items: occs.filter(o => o.all_day
    ? parse(o.start) <= d && d < (o.kind === 'todo' ? addDays(parse(o.start), 1) : parse(o.end))
    : sameDay(new Date(o.ts * 1000), d)).sort((a, b) => (b.all_day - a.all_day) || a.ts - b.ts) }));
}

export default {
  mount(root, ctx) {
    ensureCss();
    const client = useMock(ctx) ? createMockClient() : createClient((m, p, o) => ctx.api.callService('calendar', m, p, o));
    const st = { view: ctx.store?.get('hub.chat.calendar.view', 'day') || 'day', date: new Date(), occs: [], todos: [], alerts: [], settings: null, rev: -1, mini: false };
    const box = el('div.cal', { style: { flexDirection: 'column', overflow: 'hidden' } });
    root.replaceChildren(box);
    let pop = null, timer = 0, alive = true;
    const closePop = () => { pop?.remove(); pop = null; };
    const fail = e => ctx.toast?.(e?.detail || e?.message || String(e), 'error');

    async function load() {
      const r = rangeOf(st.view === 'day' ? 'day' : 'week', st.date, st.settings?.week_start || 0);
      const [range, todos, alerts] = await Promise.all([client.range(r.from.toISOString(), r.to.toISOString()), client.todos(), client.alerts('unread').catch(() => ({ alerts: [] }))]);
      st.occs = range.occurrences; st.rev = range.rev; st.todos = todos.todos.filter(t => !t.done && t.ts != null && (t.overdue || sameDay(new Date(t.ts * 1000), new Date())));
      st.alerts = alerts.alerts || [];
      draw();
    }
    const refresh = () => load().catch(fail);
    const open = (o, anchor) => {
      closePop();
      pop = popover(o, anchor, { close: closePop, edit: x => { closePop(); ctx.navigate?.(`#/calendar?item=${encodeURIComponent(x.id)}`); },
        done: async x => { closePop(); try { await client.done(x.item_id, x.recurring ? x.occurrence : undefined, x.done); refresh(); } catch (e) { fail(e); } },
        remove: x => { closePop(); ctx.navigate?.(`#/calendar?item=${encodeURIComponent(x.id)}`); },
        mention: x => { closePop(); if (!ctx.insertText?.(mentionText(x))) ctx.toast?.('Open a chat to mention it', 'info'); } });
      document.body.append(pop);
    };

    function head() {
      const seg = el('div.cal-seg', null, ...[['day', 'Day'], ['week', 'Week']].map(([k, l]) => el('button', { 'aria-pressed': String(st.view === k), onclick: () => { st.view = k; ctx.store?.set('hub.chat.calendar.view', k); refresh(); } }, l)));
      const title = st.view === 'day' ? `${WEEKDAYS[(st.date.getDay() + 6) % 7]} ${st.date.getDate()} ${MONTHS[st.date.getMonth()].slice(0, 3)}` : (() => { const r = rangeOf('week', st.date, st.settings?.week_start || 0); return `${shortDay(r.from)} – ${addDays(r.to, -1).getDate()}`; })();
      return el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px', borderBottom: '1px solid var(--cal-line)', flex: 'none' } },
        el('div', { style: { display: 'flex', alignItems: 'center', gap: '4px' } }, seg, el('span', { style: { flex: '1' } }),
          el('button.cal-btn.icon.ghost', { 'aria-label': 'Previous', onclick: () => { st.date = addDays(st.date, st.view === 'day' ? -1 : -7); refresh(); } }, icon(I.left, 14)),
          el('button.cal-btn', { style: { height: '26px', padding: '0 8px' }, onclick: () => { st.date = new Date(); refresh(); } }, 'Today'),
          el('button.cal-btn.icon.ghost', { 'aria-label': 'Next', onclick: () => { st.date = addDays(st.date, st.view === 'day' ? 1 : 7); refresh(); } }, icon(I.right, 14))),
        el('button.cal-btn.ghost', { style: { justifyContent: 'flex-start', height: '24px', padding: '0 4px', fontWeight: 600 }, 'aria-expanded': String(st.mini), onclick: () => { st.mini = !st.mini; draw(); } }, title, ' ', st.mini ? '▴' : '▾'),
        st.mini ? mini() : null);
    }
    function mini() {
      const ws = st.settings?.week_start || 0, m = rangeOf('month', st.date, ws), n = new Date();
      return el('div.cal-mini', null, ...Array.from({ length: 7 }, (_, i) => el('div.wd', null, WEEKDAYS[(i + ws) % 7][0])),
        ...m.days.map(d => el('button', { class: [d.getMonth() !== st.date.getMonth() ? 'out' : '', sameDay(d, n) ? 'today' : '', sameDay(d, st.date) ? 'sel' : ''].join(' '), onclick: () => { st.date = d; st.mini = false; refresh(); } }, d.getDate())));
    }
    function dayView() {
      const d = startOfDay(st.date), h0 = firstHour(st.occs), now = new Date();
      const allDay = st.occs.filter(o => o.all_day);
      const col = el('div', { style: { position: 'relative', height: `${(24 - h0) * ROW_PX}px`, marginLeft: '40px', borderLeft: '1px solid var(--cal-line)', backgroundImage: 'linear-gradient(var(--cal-line) 1px, transparent 1px)', backgroundSize: `100% ${ROW_PX}px` } });
      const gutter = el('div', { style: { position: 'absolute', left: '0', top: '0', width: '36px', fontSize: '10px', color: 'var(--mut,#8A94A6)', textAlign: 'right' } },
        ...Array.from({ length: 24 - h0 }, (_, i) => el('div', { style: { height: `${ROW_PX}px`, transform: 'translateY(-6px)' } }, i ? `${String(h0 + i).padStart(2, '0')}` : '')));
      const shift = h0 * ROW_PX;
      for (const b of layoutDay(st.occs, d, ROW_PX)) {
        const o = b.occ;
        col.append(el('div.cal-ev', { style: { '--c': o.color || '#4F7CFF', top: `${b.top - shift}px`, height: `${Math.max(18, b.height - 2)}px`, left: `calc(${b.col} * 100% / ${b.cols} + 2px)`, width: `calc(100% / ${b.cols} - 4px)` },
          title: `${o.title} · ${timeText(o)}`, onclick: e => open(o, e.currentTarget) }, el('div.t', null, o.title), b.height > 30 ? el('div.s', null, timeText(o)) : null));
      }
      for (const o of st.occs.filter(o => o.kind === 'todo' && !o.all_day))
        col.append(el('div.cal-todo', { style: { top: `${minutesOf(new Date(o.ts * 1000)) * ROW_PX / 60 - shift - 9}px` }, onclick: e => open(o, e.currentTarget) }, o.done ? '✓ ' : '○ ', o.title));
      if (sameDay(d, now) && now.getHours() >= h0) col.append(el('div.cal-now', { style: { top: `${minutesOf(now) * ROW_PX / 60 - shift}px` } }));
      const wrap = el('div', { style: { position: 'relative' } }, gutter, col);
      return el('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px' } },
        allDay.length ? el('div', { style: { display: 'flex', flexDirection: 'column', gap: '3px' } }, ...allDay.map(o => el('div.cal-bar', { style: { position: 'static', '--c': o.color }, class: o.kind === 'todo' ? 'todo' : '', onclick: e => open(o, e.currentTarget) }, o.title))) : null,
        wrap);
    }
    function weekView() {
      const n = new Date();
      return el('div', { style: { display: 'flex', flexDirection: 'column' } }, ...weekDays(st.occs, st.date, st.settings?.week_start || 0).map(({ day, items }) =>
        el('div', { style: { padding: '6px 0', borderBottom: '1px solid var(--cal-line)' } },
          el('div', { style: { fontSize: '11.5px', fontWeight: 600, color: sameDay(day, n) ? 'var(--acc,#FFB224)' : 'var(--mut,#8A94A6)', marginBottom: '2px' } }, sameDay(day, n) ? `Today · ${shortDay(day)}` : shortDay(day)),
          ...(items.length ? items.map(o => el('div.cal-chip', { style: { '--c': o.color }, onclick: e => open(o, e.currentTarget) }, el('span.d'), el('span.tm', null, o.all_day ? 'all day' : hhmm(new Date(o.ts * 1000))), el('span.tt', null, o.title)))
            : [el('div.cal-muted.cal-small', null, '—')]))));
    }
    function lists() {
      const sec = (title, rows) => rows.length ? el('div.cal-sec', { style: { padding: '10px 12px 0' } }, el('h3', null, el('span', null, title)), ...rows) : null;
      return [
        sec('To-dos', st.todos.slice(0, 8).map(t => el('div.cal-row', null,
          el('button.cal-check', { role: 'checkbox', 'aria-checked': 'false', 'aria-label': `Done: ${t.title}`, onclick: async () => { try { await client.done(t.item_id, t.recurring ? t.occurrence : undefined); refresh(); } catch (e) { fail(e); } } }),
          el('span', { style: { flex: '1', minWidth: '0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t.title),
          el('span.cal-small', { style: { color: t.overdue ? 'var(--rd,#F85149)' : 'var(--mut,#8A94A6)' } }, t.overdue ? 'overdue' : t.all_day ? 'today' : hhmm(new Date(t.ts * 1000)))))),
        sec('Reminders', st.alerts.slice(0, 5).map(a => el('div', { style: { display: 'flex', gap: '8px', padding: '5px 6px', alignItems: 'flex-start' } }, el('span', { style: { paddingTop: '2px' } }, icon(I.bell, 12)),
          el('div', { style: { flex: '1', minWidth: '0', display: 'flex', flexDirection: 'column', gap: '3px' } }, el('span', { style: { fontSize: '12.5px' } }, a.title), el('div.cal-muted.cal-small', null, a.body),
            reminderActs(a, client, refresh, fail, st.settings?.allday_alert))))),
      ];
    }
    function draw() {
      closePop();
      const body = el('div', { style: { flex: '1', minHeight: '0', overflowY: 'auto', scrollbarWidth: 'thin' } },
        el('div', { style: { padding: '8px 12px' } }, st.view === 'day' ? dayView() : weekView()), ...lists(),
        el('div', { style: { padding: '12px', display: 'flex', gap: '6px' } }, el('a.cal-btn', { href: '#/calendar', style: { textDecoration: 'none' } }, 'Open the Calendar')));
      box.replaceChildren(head(), body);
      if (st.view === 'day') {        // near now, or the first item
        const n = new Date(), h0 = firstHour(st.occs);
        body.scrollTop = sameDay(st.date, n) ? Math.max(0, (n.getHours() - h0 - 1) * ROW_PX) : 0;
      }
    }
    const poll = async () => {
      if (!alive) return;
      if (!document.hidden) { try { const s = await client.status(); if (s.rev !== st.rev) await load(); } catch { /* restarting */ } }
      timer = setTimeout(poll, 15000);
    };
    (async () => { try { st.settings = await client.settings(); } catch { /* defaults */ } await refresh(); timer = setTimeout(poll, 15000); })();
    return () => { alive = false; clearTimeout(timer); closePop(); };
  },
};
