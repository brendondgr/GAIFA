// Alerts and snoozing (calendar plan 2.3, 3.5): an item's alerts as chips with presets and a typed amount
// ("45 minutes", "3 days"), and the snooze menu a reminder offers (presets, Tomorrow morning, or a typed amount).
// The words are pure (tests/ui/remind.test.mjs).

import { el, icon, I } from './cal-style.js';

export const UNITS = [['min', 'minutes', 1], ['h', 'hours', 60], ['d', 'days', 1440], ['w', 'weeks', 10080]];
export const MAX_ALERT = 40320, MAX_SNOOZE = 43200, MAX_ALERTS = 8;
export const TIMED = [0, 5, 10, 15, 30, 60, 120, 1440, 2880, 10080];
export const ALLDAY = [0, 1440, 2880, 4320, 10080];
export const SNOOZE = [5, 10, 30, 60, 180];

/** "45 min", "2 hours", "1 day", "1 week" (an amount of minutes, its largest whole unit). */
export function amount(m) {
  const [, word, per] = [...UNITS].reverse().find(([, , per]) => m >= per && m % per === 0) || UNITS[0];
  const n = m / per, one = { minutes: 'min', hours: 'hour', days: 'day', weeks: 'week' }[word];
  return word === 'minutes' ? `${n} min` : `${n} ${n === 1 ? one : one + 's'}`;
}

/** An alert's words. All-day items: whole days before, at the settings' time (`at`). */
export function alertLabel(m, { kind = 'event', allDay = false, at = '' } = {}) {
  const time = at ? ` at ${at}` : '';
  if (allDay) {
    const days = Math.ceil(m / 1440);
    return days === 0 ? `On the day${time}` : `${days === 7 ? '1 week' : days === 1 ? '1 day' : `${days} days`} before${time}`;
  }
  return m === 0 ? (kind === 'todo' ? 'At the time' : 'When it starts') : `${amount(m)} before`;
}

/** A typed amount in minutes, or an error's words. n: the number typed, unit: UNITS' first column. */
export function minutesOf(n, unit, max) {
  const per = (UNITS.find(u => u[0] === unit) || UNITS[0])[2], v = Number(n);
  if (!Number.isFinite(v) || v <= 0 || Math.round(v * per) !== v * per) return { error: 'a whole number above 0' };
  const m = v * per;
  return m > max ? { error: `at most ${amount(max)}` } : { minutes: m };
}

/** An item's alerts with one more (none twice, at most MAX_ALERTS), sorted. */
export function withAlert(list, m) {
  return list.includes(m) || list.length >= MAX_ALERTS ? [...list].sort((p, q) => p - q) : [...list, m].sort((p, q) => p - q);
}

/** A number box and a unit, and a button: calls pick(minutes). Units: which of UNITS. */
export function amountInput({ button, max, units = ['min', 'h', 'd', 'w'], unit = units[0], pick }) {
  const n = el('input.cal-input', { type: 'number', min: 1, step: 1, placeholder: '45', 'aria-label': 'How many', style: { width: '68px' } });
  const u = el('select.cal-input', { 'aria-label': 'Unit', style: { width: 'auto' } }, ...UNITS.filter(x => units.includes(x[0])).map(([v, w]) => el('option', { value: v }, w)));
  u.value = unit;
  const err = el('span.cal-small', { style: { color: 'var(--rd,#F85149)' } });
  const go = () => { const r = minutesOf(n.value, u.value, max); if (r.error) { err.textContent = r.error; n.focus(); return; } err.textContent = ''; n.value = ''; pick(r.minutes); };
  n.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  return el('span', { style: { display: 'inline-flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' } }, n, u, el('button.cal-btn', { type: 'button', onclick: go }, button), err);
}

/** An item's alerts: chips with ×, a preset list and "Custom…" (a typed amount). x: {alerts, kind, all_day}; at: the all-day time. */
export function alertsField(x, draw, at = '') {
  const opt = { kind: x.kind, allDay: !!x.all_day, at };
  const presets = (x.all_day ? ALLDAY : TIMED).filter(m => !x.alerts.includes(m));
  const custom = x._customAlert;
  const add = el('select.cal-input', { style: { width: 'auto' }, 'aria-label': 'Add an alert', onchange: e => {
    if (e.target.value === 'custom') x._customAlert = true; else if (e.target.value !== '') x.alerts = withAlert(x.alerts, +e.target.value);
    draw();
  } }, el('option', { value: '' }, '+ Alert'), ...presets.map(m => el('option', { value: m }, alertLabel(m, opt))), el('option', { value: 'custom' }, 'Custom…'));
  const full = x.alerts.length >= MAX_ALERTS;
  return el('div.cal-field', null, el('span', null, 'Alerts (in the app)'),
    el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' } },
      ...[...x.alerts].sort((p, q) => p - q).map(m => el('span.cal-btn', { style: { cursor: 'default' } }, icon(I.bell, 12), alertLabel(m, opt),
        el('button.cal-btn.icon.ghost', { type: 'button', style: { width: '20px', height: '20px' }, onclick: () => { x.alerts = x.alerts.filter(y => y !== m); draw(); }, 'aria-label': `Remove the alert ${alertLabel(m, opt)}` }, icon(I.x, 11)))),
      full ? el('span.cal-muted.cal-small', null, `${MAX_ALERTS} at most`) : custom ? null : add),
    custom && !full ? el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', marginTop: '6px' } },
      amountInput({ button: 'Add', max: MAX_ALERT, units: x.all_day ? ['d', 'w'] : ['min', 'h', 'd', 'w'], pick: m => { x.alerts = withAlert(x.alerts, m); x._customAlert = false; draw(); } }),
      el('span.cal-muted.cal-small', null, 'before'),
      el('button.cal-btn.ghost', { type: 'button', onclick: () => { x._customAlert = false; draw(); } }, 'Cancel')) : null);
}

/** "until 14:30", "until tomorrow 09:00", "until Fri Nov 13 09:00" (a snoozed reminder's line). */
export function untilWords(ts, now = new Date()) {
  const d = new Date(ts * 1000), hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  const day0 = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const gap = Math.round((day0(d) - day0(now)) / 86400000);
  return `until ${gap === 0 ? '' : gap === 1 ? 'tomorrow ' : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).replace(',', '') + ' '}${hm}`;
}

/** The snooze menu under a button: presets, Tomorrow morning, a typed amount. pick({minutes} | {at: 'tomorrow'}). */
export function snoozeMenu(anchor, { pick, at = '09:00' }) {
  document.querySelector('.cal-snooze')?.remove();
  const r = anchor.getBoundingClientRect();
  const close = () => { box.remove(); document.removeEventListener('pointerdown', away, true); };
  const away = e => { if (!box.contains(e.target) && e.target !== anchor) close(); };
  const choose = v => { close(); pick(v); };
  const box = el('div.cal-pop.cal-snooze', { role: 'menu', 'aria-label': 'Snooze for', style: { width: '250px', left: `${Math.max(8, Math.min(r.left, innerWidth - 258))}px`, top: `${Math.min(r.bottom + 4, innerHeight - 230)}px`, padding: '10px', gap: '6px' } },
    el('div.cal-muted.cal-small', null, 'Remind me again in'),
    el('div', { style: { display: 'flex', gap: '4px', flexWrap: 'wrap' } },
      ...SNOOZE.map(m => el('button.cal-btn', { role: 'menuitem', style: { height: '24px', padding: '0 8px', fontSize: '12px' }, onclick: () => choose({ minutes: m }) }, amount(m))),
      el('button.cal-btn', { role: 'menuitem', style: { height: '24px', padding: '0 8px', fontSize: '12px' }, onclick: () => choose({ at: 'tomorrow' }) }, `Tomorrow ${at}`)),
    el('div.cal-muted.cal-small', null, 'Or'),
    amountInput({ button: 'Snooze', max: MAX_SNOOZE, pick: m => choose({ minutes: m }) }));
  box.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  document.body.append(box);
  setTimeout(() => document.addEventListener('pointerdown', away, true), 0);
  box.querySelector('button')?.focus();
  return box;
}

/** A reminder's buttons: Seen, Snooze ▾ (the menu above) and, for a to-do, Done. */
export function reminderActs(a, client, refresh, fail, at = '09:00', { seen = true } = {}) {
  const st = { height: '22px', padding: '0 7px', fontSize: '11px' };
  const run = fn => async () => { try { await fn(); refresh(); } catch (e) { fail(e); } };
  return el('div', { style: { display: 'flex', gap: '4px', flexWrap: 'wrap' } },
    seen && a.state === 'unread' ? el('button.cal-btn', { style: st, onclick: run(() => client.alert(a.id, 'seen')) }, 'Seen') : null,
    el('button.cal-btn', { style: st, 'aria-haspopup': 'menu', title: 'Remind me again later', onclick: e => snoozeMenu(e.currentTarget, { at,
      pick: v => run(() => client.alert(a.id, 'snooze', v.minutes, v.at))() }) }, icon(I.clock, 11), 'Snooze ▾'),
    a.kind === 'todo' ? el('button.cal-btn', { style: st, onclick: run(() => client.alert(a.id, 'done')) }, 'Done') : null);
}
