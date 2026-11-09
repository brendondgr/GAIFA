// Schedules in the browser (plan scheduled-tasks 4.3): the agent's tasks/when.py in JavaScript, for the editor's
// words and next-run preview and for the mock. In local time; a monthly day past the month's end is its last day.
// Written by us (web/PATCHES.md).

export const KINDS = [['hourly', 'Hourly'], ['daily', 'Every day'], ['weekdays', 'Weekdays'], ['weekly', 'Weekly'], ['monthly', 'Monthly']];
export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/;
const hm = v => { const m = HHMM.exec(String(v || '')); return m ? [+m[1], +m[2]] : null; };
const int = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
const wd = d => (d.getDay() + 6) % 7;                // Monday 0, as Python's weekday()

/** What's wrong with a schedule ([] when it's fine), in the agent's words. */
export function check(s) {
  if (!s || typeof s !== 'object') return ['the schedule must be an object'];
  if (!KINDS.some(k => k[0] === s.kind)) return [`kind must be one of ${KINDS.map(k => k[0]).join(', ')}`];
  const out = [];
  if (s.kind === 'hourly') {
    if (!int(s.every ?? 1, 1, 24)) out.push('every must be a whole number of hours, 1 to 24');
    if (!int(s.minute ?? 0, 0, 59)) out.push('minute must be 0 to 59');
    for (const k of ['from', 'to']) if (s[k] && !hm(s[k])) out.push(`${k} must be a time, HH:MM`);
    if (!!s.from !== !!s.to) out.push('a window needs both from and to');
    else if (s.from && hm(s.from) && hm(s.to) && s.from > s.to) out.push('the window’s from must come before its to');
    else if (!out.length && !times(s).length) out.push('no hour of the day falls inside the window');
  } else {
    if (!hm(s.time)) out.push('time must be HH:MM (24-hour)');
    if (s.kind === 'weekly' && !int(s.day, 0, 6)) out.push('day must be 0 (Monday) to 6 (Sunday)');
    if (s.kind === 'monthly' && !int(s.day, 1, 31)) out.push('day must be 1 to 31');
  }
  return out;
}

function times(s) {
  const every = s.every || 1, minute = s.minute || 0, out = [];
  for (let h = 0; h < 24; h += every) out.push([h, minute]);
  const lo = hm(s.from), hi = hm(s.to);
  const key = t => t[0] * 60 + t[1];
  return lo && hi ? out.filter(t => key(t) >= key(lo) && key(t) <= key(hi)) : out;
}
function on(s, d) {
  if (s.kind === 'hourly') return s.weekdays && wd(d) >= 5 ? [] : times(s);
  const t = hm(s.time);
  if (s.kind === 'daily' || (s.kind === 'weekdays' && wd(d) < 5)) return [t];
  if (s.kind === 'weekly' && wd(d) === s.day) return [t];
  if (s.kind === 'monthly') {
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    if (d.getDate() === Math.min(s.day, last)) return [t];
  }
  return [];
}

/** The first time (unix seconds) the schedule is due strictly after `t`; null for a schedule with problems. */
export function nextAfter(s, t = Date.now() / 1000) {
  if (check(s).length) return null;
  const d0 = new Date(t * 1000);
  const d = new Date(d0.getFullYear(), d0.getMonth(), d0.getDate() - 1);
  for (let i = 0; i < 400; i++, d.setDate(d.getDate() + 1)) {
    for (const [h, m] of on(s, d)) {
      const ts = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m).getTime() / 1000;
      if (ts > t) return ts;
    }
  }
  return null;
}

const ord = n => n + ((n % 100 >= 10 && n % 100 <= 20) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'));

/** The schedule in words: "Weekdays at 07:00", "Every 2 hours at :15, 08:00–18:00". */
export function describe(s) {
  if (!s) return '?';
  if (s.kind === 'hourly') {
    const every = s.every || 1, minute = String(s.minute || 0).padStart(2, '0');
    let out = (every === 1 ? 'Every hour' : `Every ${every} hours`) + ` at :${minute}`;
    if (s.from && s.to) out += `, ${s.from}–${s.to}`;
    return out + (s.weekdays ? ', weekdays' : '');
  }
  const at = s.time || '?';
  if (s.kind === 'daily') return `Every day at ${at}`;
  if (s.kind === 'weekdays') return `Weekdays at ${at}`;
  if (s.kind === 'weekly') return `${DAYS[s.day || 0]}s at ${at}`;
  if (s.kind === 'monthly') return `Monthly on the ${ord(s.day || 1)} at ${at}` + ((s.day || 1) > 28 ? ' (or the month’s last day)' : '');
  return '?';
}

/** "Tue 10 Nov 07:00", or "today 07:00" / "tomorrow 07:00" when it is. */
export function whenWords(ts, now = Date.now() / 1000) {
  if (!ts) return '';
  const d = new Date(ts * 1000), n = new Date(now * 1000);
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  const day0 = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day0(d) - day0(n)) / 86400000);
  if (days === 0) return `today ${time}`;
  if (days === 1) return `tomorrow ${time}`;
  if (days === -1) return `yesterday ${time}`;
  return `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()]} ${d.getDate()} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]} ${time}`;
}
