// In-app notifications (calendar plan 2.2): a mod's `notification` event as a toast with its title, body, an
// Open link and up to three actions (each a route of that mod, called through the hub's proxy). Pure, so
// utils/tests/web/notify.test.mjs tests it; Hub.dc.html draws the toasts.

export const MAX_TOASTS = 5;

/** The toast for a `notification` event. Notifications stay until closed (other toasts close after 4 s). */
export function toastOf(ev) {
  return {
    id: 'n' + (ev.id || Math.random().toString(36).slice(2)), key: ev.key ? `${ev.service}:${ev.key}` : null,
    level: ev.level === 'warn' ? 'warn' : 'info', sticky: true, service: ev.service,
    title: String(ev.title || ''), body: String(ev.body || ''), route: ev.route || null,
    actions: (ev.actions || []).slice(0, 3).map(a => ({ label: a.label, ...actionCall(ev.service, a.op) })).filter(a => a.url),
  };
}

/** `POST /v1/alerts/f_1/snooze` of mod `calendar` → { method: 'POST', path: '/v1/alerts/f_1/snooze',
 *  url: '/api/s/calendar/v1/alerts/f_1/snooze' } (the shell calls it with api.callService). */
export function actionCall(service, op) {
  const m = /^(POST|PATCH) (\/\S+)$/.exec(String(op || ''));
  if (!m || !/^[a-z][a-z0-9-]{1,31}$/.test(service || '')) return { method: null, path: null, url: null };
  return { method: m[1], path: m[2], url: `/api/s/${service}${m[2]}` };
}

/** The toast list with `t` added: one with the same key is replaced in place; at most MAX_TOASTS, newest kept. */
export function addToast(list, t) {
  const i = t.key ? list.findIndex(x => x.key === t.key) : -1;
  const next = i >= 0 ? list.map((x, k) => (k === i ? t : x)) : [...list, t];
  return next.slice(-MAX_TOASTS);
}

/** The services list with one mod's badge changed (a `badge` event). */
export function withBadge(services, ev) {
  return (services || []).map(s => (s.id === ev.service ? { ...s, badge: ev.unread || null } : s));
}
