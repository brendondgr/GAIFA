// The Calendar page's client (calendar plan 3.2): the mod's routes through the hub (`ctx.call`, which goes to
// /api/s/calendar/…), or the in-memory mock (cal-mock.js) on ?mock and in the tests. Every method answers JSON.

const qs = o => {
  const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + p.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&') : '';
};

/** `call(method, path, opts)` → `{ json }` (ctx.call). */
export function createClient(call) {
  const j = async (m, p, o) => (await call(m, p, o))?.json;
  const scope = o => qs({ occurrence: o?.occurrence, scope: o?.scope });
  return {
    status: () => j('GET', '/v1/status'),
    settings: () => j('GET', '/v1/settings'),
    patchSettings: body => j('PATCH', '/v1/settings', { json: body }),
    calendars: () => j('GET', '/v1/calendars'),
    addCalendar: body => j('POST', '/v1/calendars', { json: body }),
    patchCalendar: (id, body) => j('PATCH', `/v1/calendars/${encodeURIComponent(id)}`, { json: body }),
    deleteCalendar: (id, items) => j('DELETE', `/v1/calendars/${encodeURIComponent(id)}${qs({ items })}`),
    range: (from, to, o = {}) => j('GET', `/v1/range${qs({ from, to, ...o })}`),
    todos: () => j('GET', '/v1/todos'),
    item: (id, occurrence) => j('GET', `/v1/items/${encodeURIComponent(id)}${qs({ occurrence })}`),
    add: body => j('POST', '/v1/items', { json: body }),
    patch: (id, body, o) => j('PATCH', `/v1/items/${encodeURIComponent(id)}${scope(o)}`, { json: body }),
    remove: (id, o) => j('DELETE', `/v1/items/${encodeURIComponent(id)}${scope(o)}`),
    done: (id, occurrence, undone = false) => j('POST', `/v1/items/${encodeURIComponent(id)}/done${qs({ occurrence, undone: undone || undefined })}`, { json: {} }),
    parse: (text, kind = 'event') => j('GET', `/v1/parse${qs({ text, kind })}`),
    search: q => j('GET', `/v1/search${qs({ q })}`),
    trash: () => j('GET', '/v1/trash'),
    restore: id => j('POST', `/v1/trash/${encodeURIComponent(id)}/restore`, { json: {} }),
    undo: path => j('POST', String(path).replace(/^\/api\/s\/calendar/, ''), { json: {} }),
    alerts: (state = 'all') => j('GET', `/v1/alerts${qs({ state })}`),
    alert: (fid, act, minutes, at) => j('POST', `/v1/alerts/${encodeURIComponent(fid)}/${act}${qs({ minutes, at })}`, { json: {} }),
    seenAll: () => j('POST', '/v1/alerts/seen-all', { json: {} }),
    importIcs: file => typeof file === 'string' ? j('POST', '/v1/import', { json: { ics: file } }) : j('POST', '/v1/import', { form: { file } }),
    proposal: id => j('GET', `/v1/proposals/${encodeURIComponent(id)}`),
    accept: (id, body) => j('POST', `/v1/proposals/${encodeURIComponent(id)}/accept`, { json: body || {} }),
    plan: date => j('POST', '/v1/plan', { json: { date } }),
    exportUrl: calendars => `/api/s/calendar/v1/export.ics${qs({ calendars })}`,
  };
}

/** Whether the page should use the mock: the hub's proxy isn't live (?mock). */
export const useMock = ctx => !!ctx?.api?.isLive && !ctx.api.isLive('proxy');
