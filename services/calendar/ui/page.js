// The Calendar's page module (calendar plan 3.1–3.2; brief §5): `main` is the Calendar in the main view
// (#/calendar, after Chat in the sidebar); the mod's own tab (#/s/calendar) holds its settings.

import { requireRunning, store } from '/mod-kit.js';
import { createClient, useMock } from './cal-api.js';
import { createMockClient } from './cal-mock.js';
import { mountCalendar } from './cal-shell.js';
import { settingsForm } from './cal-settings.js';

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
      return mountCalendar(el, { ...ctx, projects: () => projects(ctx) }, clientFor(ctx), store);
    },
  },
};
