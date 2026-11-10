// Prep tasks (calendar plan 6.3): in the event sheet, **Prep task** makes a scheduled task in the agent that runs N
// minutes before each occurrence of the event ({kind: "event"}), named "Prep: <title>", and the item keeps
// `prep: {task_id, before_min}`. Its page in Chat (#/chat/tasks/<id>) is where it's changed after.

import { el } from './cal-style.js';

export const BEFORE = [[15, '15 min'], [30, '30 min'], [60, '1 hour'], [120, '2 hours'], [1440, '1 day']];

/** The agent's task body for an event's prep. */
export function prepBody(item, x) {
  const title = (x.title || item?.title || '').trim();
  return { name: `Prep: ${title}`.slice(0, 120), instructions: String(x.prepText || '').trim(), enabled: true, mode: 'auto',
    schedule: { kind: 'event', item: item.id, before_min: +x.prepBefore || 30, title }, ...(item.project_id ? { project_id: item.project_id } : {}) };
}

/** The sheet's Prep task section. `item`: the saved item (null for a new one). */
export function prepFields(x, item) {
  if (item?.prep?.task_id) {
    return el('div.cal-field', null, el('span', null, 'Prep task'),
      el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', fontSize: '12.5px' } },
        el('span', null, `Runs ${BEFORE.find(b => b[0] === item.prep.before_min)?.[1] || item.prep.before_min + ' min'} before, each time`),
        el('a.cal-btn', { href: `#/chat/tasks/${encodeURIComponent(item.prep.task_id)}`, style: { textDecoration: 'none' } }, 'Open its task')));
  }
  x.prepBefore = x.prepBefore || 30;
  const body = el('div', { style: { display: x.prepOn ? 'flex' : 'none', flexDirection: 'column', gap: '8px' } },
    el('textarea.cal-input', { rows: 3, placeholder: 'What the agent should do before it: gather my notes on…, write a short brief to…', oninput: e => { x.prepText = e.target.value; } }, x.prepText || ''),
    el('label.cal-field', null, el('span', null, 'How long before'), (() => {
      const s = el('select.cal-input', { onchange: e => { x.prepBefore = +e.target.value; } }, ...BEFORE.map(([v, l]) => el('option', { value: v }, l)));
      s.value = String(x.prepBefore); return s;
    })()),
    el('div.cal-muted.cal-small', null, 'A scheduled task in Chat runs this before each occurrence, in Auto, with no one watching: what it would ask about is refused. Test it from its page.'));
  return el('div.cal-field', null, el('span', null, 'Prep task'),
    el('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '12.5px' } },
      el('input', { type: 'checkbox', checked: !!x.prepOn, onchange: e => { x.prepOn = e.target.checked; body.style.display = x.prepOn ? 'flex' : 'none'; } }),
      'Have the agent prepare before it'), body);
}

/** After a save: make the task and tie it to the item. `agent(method, path, json)` calls the agent mod. */
export async function savePrep(item, x, agent, client) {
  if (!item || item.kind !== 'event' || item.prep?.task_id || !x.prepOn || !String(x.prepText || '').trim()) return null;
  const t = await agent('POST', '/v1/tasks', prepBody(item, x));
  await client.patch(item.id, { prep: { task_id: t.id, before_min: +x.prepBefore || 30 } });
  return t;
}
