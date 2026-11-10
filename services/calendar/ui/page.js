// The Calendar's page module (calendar plan 3.1–3.2; brief §5): `main` is the Calendar in the main view
// (#/calendar, after Chat in the sidebar); the mod's own tab (#/s/calendar) holds its settings.

import { requireRunning, store } from '/mod-kit.js';
import { createClient, useMock } from './cal-api.js';
import { createMockClient } from './cal-mock.js';
import { mountCalendar } from './cal-shell.js';
import { settingsForm } from './cal-settings.js';
import { prepFields, savePrep } from './cal-prep.js';
import { historyLayer, scheduleHere, tasksLayer } from './cal-layers.js';
import { el } from './cal-style.js';

const clientFor = ctx => (useMock(ctx) ? createMockClient() : createClient((m, p, o) => ctx.call(m, p, o)));

/** The agent's projects (for an item's project), when the agent mod is there. */
async function projects(ctx) {
  try { const r = await ctx.api.callService('agent', 'GET', '/v1/projects'); return (r.json?.projects || r.json || []).map(p => ({ id: p.id, name: p.name })); } catch { return []; }
}

export default {
  tabs: [{ id: 'settings-cal', label: 'Calendar settings' }],
  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the calendar')) return;
    return settingsForm(el, ctx, clientFor(ctx));
  },
  main: {
    mount(el, ctx) {
      if (!useMock(ctx) && !requireRunning(el, ctx, 'the calendar')) return;
      const client = clientFor(ctx), agentUp = () => !useMock(ctx);
      const agent = async (m, p, json) => (await ctx.api.callService('agent', m, p, { json })).json;
      return mountCalendar(el, { ...ctx, projects: () => projects(ctx),
        // calendar 6.3: an event's prep task, made in the agent's scheduled tasks
        layers: agentUp() ? [tasksLayer(ctx), historyLayer(ctx)] : [],               // calendar 6.4, 8.2
        sheetExtra: (x, item) => (x.kind !== 'event' || !agentUp() ? null : item ? prepFields(x, item)
          : el('div', { style: { display: 'flex', flexDirection: 'column', gap: '12px' } }, prepFields(x, item),
            el('a.cal-btn.ghost', { href: scheduleHere(x), style: { textDecoration: 'none', alignSelf: 'flex-start' } }, 'Or schedule a task at this time'))),
        afterSave: (item, x) => (agentUp() ? savePrep(item, x, agent, client) : null),
        removePrep: id => agent('DELETE', `/v1/tasks/${encodeURIComponent(id)}`) }, client, store);
    },
  },
};
