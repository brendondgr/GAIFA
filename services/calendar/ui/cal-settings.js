// The Calendar's settings (calendar plan 1.6), on the mod's own tab (#/s/calendar): working hours per weekday,
// alert defaults, the week's first day, how 11/12 reads, today's agenda in chats, the default view.

import { WEEKDAYS } from './cal-dates.js';
import { alertsField } from './cal-remind.js';
import { el, ensureCss } from './cal-style.js';

export function settingsForm(root, ctx, client) {
  ensureCss();
  const box = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '18px', maxWidth: '720px' } });
  root.replaceChildren(box);
  const custom = {};                          // which alert list has its typed amount open
  const draw = s => {
    const x = JSON.parse(JSON.stringify(s));
    const row = (label, ...kids) => el('div', { style: { display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', minHeight: '32px' } },
      el('div', { style: { width: '220px', flex: 'none', fontSize: '12.5px' } }, label), ...kids);
    const sel = (k, opts, cast = String) => { const s2 = el('select.cal-input', { onchange: e => { x[k] = cast(e.target.value); } }, ...opts.map(([v, l]) => el('option', { value: v }, l))); s2.value = x[k]; return s2; };
    const hours = x.work_hours.map((d, i) => el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center' } },
      el('label', { style: { width: '54px', display: 'flex', gap: '5px', alignItems: 'center', fontSize: '12.5px' } },
        el('input', { type: 'checkbox', checked: !!d, onchange: e => { x.work_hours[i] = e.target.checked ? ['09:00', '17:00'] : null; draw(x); } }), WEEKDAYS[i]),
      d ? el('input.cal-input', { type: 'time', value: d[0], oninput: e => { x.work_hours[i][0] = e.target.value; } }) : el('span.cal-muted', null, 'day off'),
      d ? el('span.cal-muted', null, '–') : null,
      d ? el('input.cal-input', { type: 'time', value: d[1], oninput: e => { x.work_hours[i][1] = e.target.value; } }) : null));
    const multi = (k, kind) => {            // the editor's chips, presets and Custom… (cal-remind.js)
      const y = { alerts: x[k], kind, all_day: false, _customAlert: custom[k] };
      const wrap = el('div');
      const redraw = () => { x[k] = y.alerts; custom[k] = y._customAlert; wrap.replaceChildren(alertsField(y, redraw)); };
      wrap.append(alertsField(y, redraw));
      return wrap;
    };
    box.replaceChildren(
      el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, el('strong', { style: { flex: 1, fontSize: '15px' } }, 'Calendar settings'),
        el('a.cal-btn', { href: '#/calendar', style: { textDecoration: 'none' } }, 'Open the Calendar')),
      row('Working hours (free time and day plans use them)', el('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px' } }, ...hours)),
      row('Alerts on new events', multi('event_alerts', 'event')),
      row('Alerts on new to-dos', multi('todo_alerts', 'todo')),
      row('An all-day item’s alert', el('input.cal-input', { type: 'time', value: x.allday_alert, oninput: e => { x.allday_alert = e.target.value; } }), el('span.cal-muted', null, 'on the day, or the days before that an all-day item’s alerts name')),
      row('Weeks start on', sel('week_start', [[0, 'Monday'], [6, 'Sunday']], Number)),
      row('11/12 means', sel('date_order', [['mdy', 'November 12 (month first)'], ['dmy', '11 December (day first)']])),
      row('Opens in', sel('default_view', [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['agenda', 'Agenda']])),
      row('Today’s agenda in chats', el('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '12.5px' } },
        el('input', { type: 'checkbox', checked: x.agenda_in_prompt, onchange: e => { x.agenda_in_prompt = e.target.checked; } }), 'Every chat’s prompt has today’s and tomorrow’s items')),
      el('div', null, el('button.cal-btn.pri', { onclick: async () => {
        try { draw(await client.patchSettings(x)); ctx.toast?.('Calendar settings saved', 'success'); } catch (e) { ctx.toast?.(e?.detail || String(e), 'error'); }
      } }, 'Save')));
  };
  client.settings().then(draw).catch(e => box.replaceChildren(el('div', null, e?.detail || String(e))));
}
