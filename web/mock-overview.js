// The agent and calendar mods on the mock (plan overview-bento 2.2): only what the Overview's tiles read, so
// `?mock` shows Today, Recent chats and the next scheduled task. The Chat page keeps its own scripted agent
// (chat/chat-mock.js) in `?mock`; these are separate. Written by us, not Claude Design.

export const AGENT_SVC = { id: 'agent', name: 'Agent', description: 'The chat agent: chats, memory, projects and scheduled tasks', icon: 'chat', port: 5100,
  used: 0.1 * 2 ** 30, stats: [{ label: 'Chats today', value: 6 }], priority: 8 };
export const CALENDAR_SVC = { id: 'calendar', name: 'Calendar', description: 'Events, to-dos and reminders', icon: 'calendar', port: 5110,
  used: 0.06 * 2 ** 30, stats: [{ label: 'Today', value: 4 }], priority: 9 };

const pad = n => String(n).padStart(2, '0');
// "YYYY-MM-DDTHH:MM" in local time, as the calendar writes it
const local = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

export function agentMock({ ok, now }) {
  const t = now(), thread = (id, title, agoS, state = 'idle') => ({ id, title, state, updated: t - agoS, created: t - agoS - 600, archived: false, parent_id: null, children: 0, settings: {} });
  const threads = [thread('t_m1', 'Plan the Overview redesign', 90, 'running'), thread('t_m2', 'Approve the web fetch for the paper', 1500, 'waiting'),
    thread('t_m3', 'Blender scene: low-poly treehouse', 3 * 3600), thread('t_m4', 'Summarize the lab meeting notes', 5 * 3600),
    thread('t_m5', 'Tacos in Tallahassee', 26 * 3600), thread('t_m6', 'Draft the JOSS submission', 3 * 86400), thread('t_m7', 'Voice for the narrator', 6 * 86400)];
  const tonight = new Date(); tonight.setHours(21, 0, 0, 0);
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); tomorrow.setHours(7, 30, 0, 0);
  const tasks = [{ id: 'k_m1', name: 'News digest', enabled: true, next_due: tonight.getTime() / 1000 }, { id: 'k_m2', name: 'Morning brief', enabled: true, next_due: tomorrow.getTime() / 1000 }];
  return {
    'GET /health': () => ok({ status: 'ok' }),
    'GET /v1/threads': ({ query }) => ok(threads.slice(0, Number(query.limit) || 50)),
    'GET /v1/tasks': () => ok(tasks),
    'GET /v1/memory/tree': () => ok({ entities: [], proposed: 2 }),
  };
}

export function calendarMock({ ok }) {
  const at = (h, m = 0) => { const d = new Date(); d.setHours(h, m, 0, 0); return local(d); };
  const items = [
    { id: 'c_m1', kind: 'event', title: 'Lab meeting', start: at(10), end: at(11), calendar: 'Work' },
    { id: 'c_m2', kind: 'event', title: 'Office hours', start: at(14), end: at(15, 30), calendar: 'Work' },
    { id: 'c_m3', kind: 'todo', title: 'Send the draft to the committee', due: at(17) },
    { id: 'c_m4', kind: 'event', title: 'Gym', start: at(19), end: at(20), calendar: 'Personal' },
  ];
  return {
    'GET /health': () => ok({ status: 'ok' }),
    'GET /v1/agenda': () => ok({ items, undated_todos: [], overdue_todos: [{ id: 'c_m0', kind: 'todo', title: 'Renew the parking permit', due: at(9) }] }),
  };
}
