// The Overview's tiles from the agent and calendar mods (plan overview-bento 2.2): Today (the calendar's
// items, overdue to-dos and scheduled tasks due today) and Recent chats, read through the hub's proxy.
// The pure parts (todayRows, chatRows, ago, nextTask) are tested in utils/tests/web/overview-tiles.test.mjs.
// Written by us (web/PATCHES.md).

import { h, MONO, MUT, TONE } from './chart-kit.js';
import { useData } from './views.js';
import { Row, Muted, Calm, dotSt, PATHS, NUM_ST } from './overview-tiles.js';
import { useTileSize } from './bento.js';

const running = (services, id) => ['ready', 'degraded'].includes(services.find(s => s.id === id)?.state);
export const hasMod = running;

// ---------- pure ----------
const pad = n => String(n).padStart(2, '0');
const hm = ts => { const d = new Date(ts * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
// "2026-11-10T15:30" (local, as the calendar writes it) → unix seconds; a date alone has no time (null).
const localTs = s => (typeof s === 'string' && s.length > 10 ? new Date(s.slice(0, 16)).getTime() / 1000 : null);
export function endOfDay(now) { const d = new Date(now * 1000); d.setHours(24, 0, 0, 0); return d.getTime() / 1000; }

// Today's rows: overdue to-dos, all-day items, then everything with a time in order. `past` once it ended,
// `now` while it runs. Scheduled tasks count when on and due before midnight.
export function todayRows({ agenda, tasks = [], now = Date.now() / 1000 }) {
  const rows = [], end = endOfDay(now);
  for (const it of agenda?.overdue_todos || []) rows.push({ key: 'o:' + it.id, kind: 'overdue', title: it.title, time: 'overdue', rank: 0, href: '#/calendar' });
  for (const it of agenda?.items || []) {
    const key = 'i:' + it.id + (it.occurrence || '');
    if (it.kind === 'todo') {
      if (it.done) continue;
      const ts = localTs(it.due);
      rows.push({ key, kind: 'todo', title: it.title, time: ts == null ? 'to-do' : hm(ts), ts, rank: ts == null ? 1 : 2, past: false, href: '#/calendar' });
      continue;
    }
    const s = localTs(it.start), e = localTs(it.end);
    if (it.all_day || s == null) { rows.push({ key, kind: 'event', title: it.title, time: 'all day', rank: 1, cal: it.calendar, href: '#/calendar' }); continue; }
    rows.push({ key, kind: 'event', title: it.title, time: hm(s), ts: s, rank: 2, cal: it.calendar, past: e != null && e <= now, now: s <= now && (e == null || e > now), href: '#/calendar' });
  }
  for (const t of tasks) {
    if (!t.enabled || !t.next_due || t.next_due >= end || t.next_due < now - 300) continue;
    rows.push({ key: 't:' + t.id, kind: 'task', title: t.name, time: hm(t.next_due), ts: t.next_due, rank: 2, href: '#/chat/tasks/' + encodeURIComponent(t.id) });
  }
  return rows.sort((a, b) => a.rank - b.rank || (a.ts ?? 0) - (b.ts ?? 0));
}

// The next scheduled task to run: {name, ts, id} or null.
export function nextTask(tasks = [], now = Date.now() / 1000) {
  const t = tasks.filter(x => x.enabled && x.next_due && x.next_due >= now - 60).sort((a, b) => a.next_due - b.next_due)[0];
  return t ? { id: t.id, name: t.name, ts: t.next_due } : null;
}

// "now", "4m", "3h", "2d", "Nov 5"
export function ago(ts, now = Date.now() / 1000) {
  const s = Math.max(0, now - ts);
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  if (s < 7 * 86400) return Math.floor(s / 86400) + 'd';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Recent chats, top-level only, with their state from the thread and the running jobs.
export function chatRows(threads = [], jobs = [], n = 8) {
  const busy = new Set(jobs.filter(j => j.service === 'agent' && j.state === 'running').map(j => j.id));
  return threads.filter(t => !t.parent_id && !t.archived).slice(0, n).map(t => {
    const state = t.running || t.state === 'running' || busy.has(t.id) ? 'running' : ['waiting', 'error'].includes(t.state) ? t.state : null;
    return { id: t.id, title: t.title || 'New chat', state, updated: t.updated || t.created || 0 };
  });
}

// ---------- data ----------
function useMod(ctx, id, path, every, deps = []) {
  const on = running(ctx.services, id);
  return useData(() => (on ? ctx.api.callService(id, 'GET', path).then(r => r.json) : Promise.resolve(null)), [ctx.api, id, path, on, ...deps], on ? every : 0);
}
export const useTasks = ctx => useMod(ctx, 'agent', '/v1/tasks', 60000);

// ---------- Today ----------
const KIND_DOT = { event: 'var(--cy,#58C4DD)', todo: 'var(--gr,#3FB950)', task: 'var(--pu,#BC8CFF)', overdue: 'var(--rd,#F85149)' };
export function TodayW({ ctx }) {
  const day = new Date().toDateString();
  const agenda = useMod(ctx, 'calendar', '/v1/agenda?day=today', 60000, [day]), tasks = useTasks(ctx);
  if (agenda.state === 'loading' && tasks.state === 'loading') return h(Calm, { text: 'Loading…', tone: 'dim' });
  const rows = todayRows({ agenda: agenda.data, tasks: Array.isArray(tasks.data) ? tasks.data : [] });
  const err = agenda.state === 'error' ? 'Calendar didn’t answer' : null;
  if (!rows.length) return h(Calm, { icon: PATHS.calendar, text: err || 'Nothing else today', tone: err ? 'red' : 'dim' });
  return h('div', null, rows.map((r, i) => h(Row, { key: r.key, first: i === 0, href: r.href, dim: r.past, title: r.cal ? `${r.title} · ${r.cal}` : r.title,
    lead: h('span', { style: { width: 42, flex: 'none', fontFamily: MONO, fontSize: 11, color: r.kind === 'overdue' ? TONE.red : r.now ? TONE.accent : MUT } }, r.time),
    text: h('span', null, h('span', { style: { ...dotSt(KIND_DOT[r.kind]), display: 'inline-block', marginRight: 7, verticalAlign: 1 } }), r.title),
    right: r.now ? h(Muted, { style: { color: TONE.accent } }, 'now') : r.kind === 'task' ? h(Muted, null, 'task') : null })));
}
export function todayCount(rows) { const left = rows.filter(r => !r.past).length; return left || null; }

// ---------- Recent chats ----------
const STATE_DOT = { running: 'var(--acc,#FFB224)', waiting: 'var(--pu,#BC8CFF)', error: 'var(--rd,#F85149)' };
export function ChatsW({ ctx }) {
  const busy = ctx.jobs.filter(j => j.service === 'agent').map(j => j.id).join();
  const d = useMod(ctx, 'agent', '/v1/threads?limit=12', 30000, [busy]);
  if (d.state === 'loading') return h(Calm, { text: 'Loading…', tone: 'dim' });
  if (d.state === 'error') return h(Calm, { text: 'The agent didn’t answer', tone: 'red' });
  const { h: H } = useTileSize(), rows = chatRows(d.data || [], ctx.jobs, H ? Math.max(1, Math.floor((H + 1) / 27)) : 8);   // as many as fit
  if (!rows.length) return h(Calm, { icon: PATHS.chat, text: 'No chats yet', tone: 'dim' });
  return h('div', null, rows.map((r, i) => h(Row, { key: r.id, first: i === 0, href: '#/chat/' + encodeURIComponent(r.id), title: r.title,
    lead: h('span', { style: dotSt(STATE_DOT[r.state] || 'var(--bds,#2A3547)') }), text: r.title,
    right: h(Muted, { mono: true, style: { color: r.state ? STATE_DOT[r.state] : MUT } }, r.state === 'running' ? 'working' : r.state === 'waiting' ? 'waiting' : ago(r.updated)) })));
}

// ---------- the next task, as a number tile ----------
export function NextTaskNum({ ctx }) {
  const d = useTasks(ctx), t = nextTask(Array.isArray(d.data) ? d.data : []);
  const today = t && new Date(t.ts * 1000).toDateString() === new Date().toDateString();
  const when = t ? (today ? hm(t.ts) : new Date(t.ts * 1000).toLocaleDateString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })) : '—';
  return h('a', { href: t ? '#/chat/tasks/' + encodeURIComponent(t.id) : '#/chat/tasks', style: NUM_ST, 'aria-label': t ? `Next task: ${t.name} at ${when}` : 'No scheduled tasks' },
    h('span', { style: { fontFamily: MONO, fontSize: 17, lineHeight: '20px', fontWeight: 600, whiteSpace: 'nowrap' } }, when),
    h('span', { style: { fontSize: 11, lineHeight: '20px', color: MUT, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 } }, t ? t.name : 'none scheduled'));
}
