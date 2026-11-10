// The calendar's chat module (calendar plan 4.4; docs/mods.md "Chat cards"): its tools' cards under a turn's fold.
// - an item the agent added, changed, completed or deleted: a chip with its colour, day and time, repeat and calendar,
//   and Open in Calendar (the turn's Undo reverses it);
// - a day's agenda and free time as short lists;
// - a proposal (dates from a document, an .ics, a day plan): every item to tick, the calendar, Add N, then Undo.
// Clicks here are yours (the card calls the mod's routes through the hub), not the agent's.

import { proposalList } from './cal-files.js';
import { parse, timeText } from './cal-dates.js';
import { ensureCss } from './cal-style.js';

const STEPS = {
  calendar_agenda: ['Reading the calendar', 'Read the calendar', 'calendar'], calendar_search: ['Searching the calendar', 'Searched the calendar', 'search'],
  calendar_when: ['Reading the date', 'Read the date', 'clock'], calendar_free: ['Finding free time', 'Found free time', 'clock'],
  calendar_add: ['Adding to the calendar', 'Added to the calendar', 'calendar'], calendar_update: ['Changing the calendar', 'Changed the calendar', 'calendar'],
  calendar_done: ['Completing a to-do', 'Completed a to-do', 'check'], calendar_delete: ['Deleting from the calendar', 'Deleted from the calendar', 'trash'],
  calendar_propose: ['Proposing dates', 'Proposed dates', 'calendar'], calendar_plan_day: ['Planning the day', 'Planned the day', 'clock'],
};

/** The tool's answer on a card (the chat keeps it whole as `result`, or as JSON text). */
export function resultOf(ctx) {
  const ev = ctx?.liveCard?.row?.item?.result;
  if (ev?.result && typeof ev.result === 'object') return ev.result;
  try { const b = JSON.parse(ev?.content || 'null'); return b && typeof b === 'object' ? (b.result && typeof b.result === 'object' ? b.result : b) : null; } catch { return null; }
}

/** An item's line: "Fri Nov 13 · 13:00–14:30 · Weekly on Fri · Personal". */
export function itemLine(it) {
  if (!it) return '';
  const s = it.start || it.due;
  const day = s ? parse(s).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) : 'no date';
  const t = timeText({ kind: it.kind, all_day: it.all_day, start: it.start, end: it.end, due: it.due });
  return [day, t, it.repeat, it.calendar].filter(Boolean).join(' · ');
}

/** Where Open in Calendar goes for an item. */
export const openHref = it => `#/calendar?item=${encodeURIComponent(`${it.id}@${it.start || it.due || ''}`)}`;

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, React = globalThis.React;
  ensureCss();
  for (const [tool, [running, done, icon]] of Object.entries(STEPS)) chat.registerStep(tool, { running, done, icon });

  const T = chat.ui.T || {};
  const link = (href, label) => h('a', { href, style: { color: T.acc || 'var(--acc,#FFB224)', textDecoration: 'none', fontSize: 12.5 } }, label);
  const dot = color => h('span', { style: { width: 9, height: 9, borderRadius: 3, background: color || '#4F7CFF', flex: 'none' } });
  const rowSt = { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderTop: '1px solid var(--bd,#1D2430)', fontSize: 12.5, minWidth: 0 };

  const ItemCard = verb => ({ ctx }) => {
    const r = resultOf(ctx);
    if (!r) return null;
    if (r.deleted) return h(kit.LiveCard, { icon: 'trash', title: r.deleted === 'occurrence' ? 'Deleted one occurrence' : r.deleted === 'following' ? 'Deleted this and the following ones' : 'Moved to the trash', meta: 'kept 30 days', done: true });
    const it = r.item;
    if (!it) return null;
    return h(kit.LiveCard, { icon: 'calendar', title: `${verb}: ${it.title}`, meta: it.kind === 'todo' ? (it.done_at ? 'done' : 'to-do') : 'event', done: true,
      foot: [h('span', { key: 'l', style: { flex: 1, minWidth: 0 } }, itemLine(it)), h('span', { key: 'o' }, link(openHref(it), 'Open in Calendar'))] },
    h('div', { style: { ...rowSt, borderTop: 0 } }, dot(it.color), h('span', { style: { fontWeight: 600 } }, it.title),
      it.location ? h('span', { style: { color: T.mut || '#8A94A6' } }, '· ' + it.location) : null),
    (r.assumed || []).length ? h('div', { style: { ...rowSt, color: T.mut || '#8A94A6' } }, 'Assumed: ' + r.assumed.join(', ')) : null);
  };
  chat.registerCard('live:calendar_add', ItemCard('Added'));
  chat.registerCard('live:calendar_update', ItemCard('Changed'));
  chat.registerCard('live:calendar_done', ({ ctx }) => { const r = resultOf(ctx); return r?.item ? h(ItemCard(r.done ? 'Done' : 'Reopened'), { ctx }) : null; });
  chat.registerCard('live:calendar_delete', ItemCard('Deleted'));

  chat.registerCard('live:calendar_agenda', ({ ctx }) => {
    const r = resultOf(ctx);
    if (!r?.items) return null;
    const items = r.items.slice(0, 14);
    return h(kit.LiveCard, { icon: 'calendar', title: 'Calendar', meta: `${r.items.length} item${r.items.length === 1 ? '' : 's'}`, done: true,
      foot: h('span', null, link('#/calendar', 'Open the Calendar')) },
    items.length ? items.map((it, i) => h('div', { key: i, style: rowSt },
      h('span', { style: { width: 120, flex: 'none', color: T.mut || '#8A94A6', fontVariantNumeric: 'tabular-nums' } }, itemLine({ ...it, repeat: null, calendar: null }).split(' · ').slice(0, 2).join(' · ')),
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: it.done ? 'line-through' : 'none' } }, it.title))) :
      h('div', { style: { ...rowSt, borderTop: 0, color: T.mut || '#8A94A6' } }, 'Nothing on.'));
  });

  chat.registerCard('live:calendar_free', ({ ctx }) => {
    const r = resultOf(ctx);
    if (!r?.slots) return null;
    return h(kit.LiveCard, { icon: 'clock', title: 'Free time', meta: `${Math.round((r.minutes || 0) / 6) / 10} h`, done: true },
      r.slots.slice(0, 10).map((s, i) => h('div', { key: i, style: rowSt }, h('span', { style: { flex: 1 } }, itemLine({ kind: 'event', start: s.start, end: s.end })), h('span', { style: { color: T.mut || '#8A94A6' } }, `${s.minutes} min`))));
  });

  const ProposalCard = title => ({ ctx }) => {
    const r = resultOf(ctx), ref = React.useRef(null), [done, setDone] = React.useState(null), [cals, setCals] = React.useState(null);
    React.useEffect(() => { chat.api.callService('calendar', 'GET', '/v1/calendars').then(x => setCals(x.json || [])).catch(() => setCals([])); }, []);
    React.useEffect(() => {
      const el = ref.current;
      if (!el || !r?.id || done || cals === null) return;
      el.replaceChildren(proposalList(r, { calendars: cals, accept: async b => {
        try { const x = await chat.api.callService('calendar', 'POST', `/v1/proposals/${encodeURIComponent(r.id)}/accept`, { json: b }); setDone(x.json); }
        catch (e) { el.prepend(Object.assign(document.createElement('div'), { textContent: e?.detail || String(e), style: 'color:var(--rd,#F85149);font-size:12px' })); }
      } }));
    }, [r?.id, done, cals]);
    if (!r?.items) return null;
    const undo = async () => { try { await chat.api.callService('calendar', 'POST', String(done.undo).replace(/^\/api\/s\/calendar/, ''), { json: {} }); setDone({ ...done, undone: true }); } catch { /* the snackbar on the page is the other way */ } };
    return h(kit.LiveCard, { icon: 'calendar', title, meta: `${r.count} to add${r.skipped?.length ? ` · ${r.skipped.length} skipped` : ''}`, done: true,
      foot: done ? [h('span', { key: 'a' }, done.undone ? 'Undone' : `Added ${done.added}`), done.undone ? null : h('button', { key: 'u', type: 'button', onClick: undo, className: 'cal-btn', style: { height: 26 } }, 'Undo'),
        h('span', { key: 'o', style: { marginLeft: 'auto' } }, link('#/calendar', 'Open the Calendar'))] : null },
    done ? null : h('div', { ref, style: { padding: '8px 12px' } }));
  };
  chat.registerCard('live:calendar_propose', ProposalCard('Dates to add'));
  chat.registerCard('live:calendar_plan_day', ProposalCard('A plan for the day'));
}
