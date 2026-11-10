// The repeat picker's rules (calendar plan 3.5): a choice ⇄ an RFC 5545 RRULE, and the rule in words (the same
// words as repeat.py `describe`). Pure; the editor (cal-edit.js) draws the picker.

export const DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];
const DAY_WORDS = { MO: 'Mon', TU: 'Tue', WE: 'Wed', TH: 'Thu', FR: 'Fri', SA: 'Sat', SU: 'Sun' };
export const KINDS = [['none', "Doesn't repeat"], ['daily', 'Daily'], ['weekdays', 'Every weekday'], ['weekly', 'Weekly'],
  ['monthly', 'Monthly on day N'], ['monthly_last', 'Monthly on the last day'], ['yearly', 'Yearly'], ['custom', 'Custom…']];

export function parts(rule) {
  const out = {};
  for (const p of String(rule || '').replace(/^RRULE:/i, '').split(';')) {
    const i = p.indexOf('=');
    if (i > 0) out[p.slice(0, i).toUpperCase()] = p.slice(i + 1);
  }
  return out;
}
const join = p => ['FREQ', 'INTERVAL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH', 'COUNT', 'UNTIL'].filter(k => p[k] != null && p[k] !== '').map(k => `${k}=${p[k]}`).join(';');

/** A choice {kind, interval, days, monthDay, unit, end: {type: never|until|count, until: 'YYYY-MM-DD', count}} → rule or null.
 *  `anchor`: the item's start date (its weekday and day of month fill what the choice leaves out). */
export function ruleOf(c, anchor) {
  const a = anchor ? new Date(String(anchor).slice(0, 10) + 'T00:00') : new Date();
  const wd = DAYS[(a.getDay() + 6) % 7];
  let p;
  switch (c.kind) {
    case 'none': return null;
    case 'daily': p = { FREQ: 'DAILY' }; break;
    case 'weekdays': p = { FREQ: 'WEEKLY', BYDAY: 'MO,TU,WE,TH,FR' }; break;
    case 'weekly': p = { FREQ: 'WEEKLY', BYDAY: (c.days?.length ? sortDays(c.days) : [wd]).join(',') }; break;
    case 'monthly': p = { FREQ: 'MONTHLY', BYMONTHDAY: String(c.monthDay || a.getDate()) }; break;
    case 'monthly_last': p = { FREQ: 'MONTHLY', BYMONTHDAY: '-1' }; break;
    case 'yearly': p = { FREQ: 'YEARLY' }; break;
    case 'custom': {
      const unit = c.unit || 'week';
      p = { FREQ: { day: 'DAILY', week: 'WEEKLY', month: 'MONTHLY', year: 'YEARLY' }[unit] };
      if (unit === 'week') p.BYDAY = (c.days?.length ? sortDays(c.days) : [wd]).join(',');
      if (unit === 'month' && c.monthDay) p.BYMONTHDAY = String(c.monthDay);
      break;
    }
    default: return null;
  }
  if ((c.interval || 1) > 1) p.INTERVAL = String(c.interval);
  const e = c.end || {};
  if (e.type === 'count' && e.count > 0) p.COUNT = String(e.count);
  if (e.type === 'until' && e.until) p.UNTIL = e.until.replaceAll('-', '') + (anchor && String(anchor).length > 10 ? 'T235959' : '');
  return join(p);
}

const sortDays = ds => [...new Set(ds)].sort((x, y) => DAYS.indexOf(x) - DAYS.indexOf(y));

/** A rule → the choice the picker shows. */
export function choiceOf(rule) {
  if (!rule) return { kind: 'none', interval: 1, days: [], end: { type: 'never' } };
  const p = parts(rule), n = +(p.INTERVAL || 1), days = (p.BYDAY || '').split(',').filter(Boolean).map(d => d.slice(-2));
  const end = p.COUNT ? { type: 'count', count: +p.COUNT } : p.UNTIL ? { type: 'until', until: `${p.UNTIL.slice(0, 4)}-${p.UNTIL.slice(4, 6)}-${p.UNTIL.slice(6, 8)}` } : { type: 'never' };
  const base = { interval: n, days, end };
  if (n === 1) {
    if (p.FREQ === 'DAILY' && !p.BYDAY) return { ...base, kind: 'daily' };
    if (p.FREQ === 'WEEKLY' && sortDays(days).join(',') === 'MO,TU,WE,TH,FR') return { ...base, kind: 'weekdays' };
    if (p.FREQ === 'WEEKLY') return { ...base, kind: 'weekly' };
    if (p.FREQ === 'MONTHLY' && p.BYMONTHDAY === '-1') return { ...base, kind: 'monthly_last' };
    if (p.FREQ === 'MONTHLY' && !p.BYDAY) return { ...base, kind: 'monthly', monthDay: p.BYMONTHDAY ? +p.BYMONTHDAY : undefined };
    if (p.FREQ === 'YEARLY' && !p.BYMONTH) return { ...base, kind: 'yearly' };
  }
  const unit = { DAILY: 'day', WEEKLY: 'week', MONTHLY: 'month', YEARLY: 'year' }[p.FREQ] || 'week';
  return { ...base, kind: 'custom', unit, monthDay: p.BYMONTHDAY ? +p.BYMONTHDAY : undefined };
}

/** The rule in words, as repeat.py says it: "Weekly on Tue, Thu", "Every 2 days, 5 times". */
export function words(rule) {
  if (!rule) return "Doesn't repeat";
  const p = parts(rule), n = +(p.INTERVAL || 1), freq = p.FREQ || '';
  const unit = { DAILY: 'day', WEEKLY: 'week', MONTHLY: 'month', YEARLY: 'year', HOURLY: 'hour' }[freq] || 'time';
  const days = (p.BYDAY || '').split(',').filter(Boolean).map(d => d.slice(-2));
  let s;
  if (freq === 'DAILY' && n === 1) s = 'Every day';
  else if (freq === 'WEEKLY' && n === 1 && sortDays(days).join(',') === 'MO,TU,WE,TH,FR') s = 'Every weekday';
  else if (n === 1) s = { WEEKLY: 'Weekly', MONTHLY: 'Monthly', YEARLY: 'Yearly', HOURLY: 'Hourly' }[freq] || 'Every day';
  else s = `Every ${n} ${unit}s`;
  if (freq === 'WEEKLY' && days.length && s !== 'Every weekday') s += ' on ' + sortDays(days).map(d => DAY_WORDS[d] || d).join(', ');
  if (freq === 'MONTHLY') {
    if (p.BYMONTHDAY === '-1') s += ' on the last day';
    else if (p.BYMONTHDAY) s += ` on day ${p.BYMONTHDAY}`;
  }
  if (p.COUNT) s += `, ${p.COUNT} times`;
  else if (p.UNTIL) {
    const u = p.UNTIL, d = new Date(+u.slice(0, 4), +u.slice(4, 6) - 1, +u.slice(6, 8));
    s += ` until ${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}, ${d.getFullYear()}`;
  }
  return s;
}
